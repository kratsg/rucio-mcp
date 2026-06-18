"""CIMD — Client ID Metadata Document support.

Implements ``draft-ietf-oauth-client-id-metadata-document``: the OAuth
``client_id`` is itself an HTTPS URL that dereferences to the client's OAuth
metadata.  Unlike DCR (RFC 7591), there is no ``POST /register`` round-trip and
no server-side per-client database — the authorization server fetches the
``client_id`` URL at ``/authorize``, verifies the document is self-referential,
and validates the requested ``redirect_uri`` against the document's list.

This removes the DCR restart-fragility entirely (no in-memory registry to lose)
and avoids unbounded registration growth on hosted deployments.  See
https://github.com/kratsg/rucio-mcp/issues/33.

Claude selects CIMD only when the AS metadata advertises both
``client_id_metadata_document_supported: true`` and ``"none"`` in
``token_endpoint_auth_methods_supported`` (the CIMD client authenticates as a
public client — PKCE only, no secret).  Both are set in ``server.py``.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl, ValidationError

_log = logging.getLogger(__name__)

# Guards for the server-side fetch of an attacker-influenceable URL.
_MAX_DOC_BYTES = 64 * 1024
_FETCH_TIMEOUT = 10.0

# socket.getaddrinfo-compatible resolver; injectable so SSRF checks are testable
# without real DNS.
Resolver = Callable[..., list[Any]]

_LOOPBACK_HOSTS = frozenset({"localhost"})


class CimdError(Exception):
    """Raised when a CIMD client_id URL or its document is invalid or unsafe."""


def is_cimd_client_id(client_id: str) -> bool:
    """Return True if *client_id* is an ``https://`` URL (CIMD), not a DCR id.

    DCR-issued ids are opaque strings (e.g. UUIDs); CIMD ids are HTTPS URLs.
    """
    try:
        parsed = urlparse(client_id)
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.netloc)


def _is_loopback_host(host: str | None) -> bool:
    if host is None:
        return False
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def redirect_uri_matches(requested: str, declared: str) -> bool:
    """Return True if *requested* matches *declared*, ignoring the port for loopback.

    Exact string equality always matches.  For loopback / ``localhost`` redirect
    URIs the port is ignored (RFC 8252 §7.3): native apps — including Claude Code,
    which declares ``http://localhost/callback`` in its CIMD — bind an ephemeral
    loopback port at runtime.  Host identity, scheme, and path must still match.
    """
    if requested == declared:
        return True
    rp = urlparse(requested)
    dp = urlparse(declared)
    if not (_is_loopback_host(rp.hostname) and _is_loopback_host(dp.hostname)):
        return False
    return rp.scheme == dp.scheme and rp.hostname == dp.hostname and rp.path == dp.path


def _ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def assert_safe_url(
    client_id_url: str, *, resolver: Resolver = socket.getaddrinfo
) -> None:
    """Raise :class:`CimdError` unless *client_id_url* is safe to fetch server-side.

    The server dereferences a URL the client controls, so this is the SSRF
    guard: requires ``https``, and rejects hosts that are — or resolve to —
    private, loopback, link-local, multicast, reserved, or unspecified addresses.
    """
    parsed = urlparse(client_id_url)
    if parsed.scheme != "https":
        msg = "CIMD client_id must be an https URL"
        raise CimdError(msg)
    host = parsed.hostname
    if not host:
        msg = "CIMD client_id URL has no host"
        raise CimdError(msg)

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _ip_blocked(literal):
            msg = f"CIMD client_id host {host} is not a public address"
            raise CimdError(msg)
        return

    try:
        infos = resolver(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        msg = f"cannot resolve CIMD host {host}: {exc}"
        raise CimdError(msg) from exc
    for info in infos:
        addr = info[4][0]
        if _ip_blocked(ipaddress.ip_address(addr)):
            msg = f"CIMD host {host} resolves to non-public address {addr}"
            raise CimdError(msg)


async def fetch_client_document(
    client_id_url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = _FETCH_TIMEOUT,
    max_bytes: int = _MAX_DOC_BYTES,
) -> dict[str, Any]:
    """Fetch and JSON-parse the CIMD document at *client_id_url*.

    ``follow_redirects`` is disabled: a redirect after the SSRF check could
    bypass the resolved-address guard, and the self-reference check below also
    assumes the document came from the requested URL.  Raises :class:`CimdError`
    on any network, size, or parse failure.
    """
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    try:
        response = await client.get(
            client_id_url, headers={"Accept": "application/json"}
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        msg = f"failed to fetch CIMD document: {exc}"
        raise CimdError(msg) from exc
    finally:
        if owns_client:
            await client.aclose()

    # httpx buffers the full body on a non-streaming GET, so .content / .json()
    # remain available after the client is closed above.
    if len(response.content) > max_bytes:
        msg = "CIMD document too large"
        raise CimdError(msg)
    try:
        parsed = response.json()
    except ValueError as exc:
        msg = f"CIMD document is not valid JSON: {exc}"
        raise CimdError(msg) from exc
    if not isinstance(parsed, dict):
        msg = "CIMD document is not a JSON object"
        raise CimdError(msg)
    return parsed


def build_client_from_document(
    doc: dict[str, Any], client_id_url: str, requested_redirect_uri: str | None
) -> OAuthClientInformationFull:
    """Build a public-client :class:`OAuthClientInformationFull` from a CIMD doc.

    Verifies the document is self-referential (its ``client_id`` equals the URL
    it was served from).  If *requested_redirect_uri* matches one of the
    document's ``redirect_uris`` only port-agnostically (loopback), the exact
    requested value is appended so the SDK's exact-match
    ``validate_redirect_uri()`` accepts it.
    """
    if doc.get("client_id") != client_id_url:
        msg = "CIMD document is not self-referential (client_id mismatch)"
        raise CimdError(msg)
    declared = doc.get("redirect_uris")
    if not declared or not isinstance(declared, list):
        msg = "CIMD document has no redirect_uris"
        raise CimdError(msg)

    redirect_uris = [str(u) for u in declared]
    # Append the exact requested redirect_uri when it matches a declared one only
    # port-agnostically (loopback); otherwise leave it off so the SDK's
    # validate_redirect_uri() rejects /authorize with a proper OAuth error.
    if (
        requested_redirect_uri
        and requested_redirect_uri not in redirect_uris
        and any(redirect_uri_matches(requested_redirect_uri, d) for d in redirect_uris)
    ):
        redirect_uris.append(requested_redirect_uri)

    try:
        return OAuthClientInformationFull(
            client_id=client_id_url,
            redirect_uris=[AnyUrl(u) for u in redirect_uris],
            # CIMD clients are public: PKCE-only, no client secret.  The MCP SDK
            # ClientAuthenticator raises (→ 401) on a Python-None auth method.
            token_endpoint_auth_method="none",
            grant_types=doc.get("grant_types") or ["authorization_code"],
            scope=doc.get("scope"),
        )
    except ValidationError as exc:
        msg = f"invalid CIMD document: {exc}"
        raise CimdError(msg) from exc


async def resolve_cimd_client(
    client_id: str,
    requested_redirect_uri: str | None,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = _FETCH_TIMEOUT,
) -> OAuthClientInformationFull:
    """Resolve a CIMD ``client_id`` URL to an :class:`OAuthClientInformationFull`.

    Validates the URL is safe to fetch, dereferences it, and builds a public
    client.  Raises :class:`CimdError` on any failure.
    """
    assert_safe_url(client_id)
    doc = await fetch_client_document(client_id, client=client, timeout=timeout)
    resolved = build_client_from_document(doc, client_id, requested_redirect_uri)
    _log.info("Resolved CIMD client_id=%s", client_id)
    return resolved
