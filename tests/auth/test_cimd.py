"""Tests for CIMD (Client ID Metadata Document) support.

draft-ietf-oauth-client-id-metadata-document: the OAuth client_id is an HTTPS
URL that dereferences to the client's OAuth metadata, removing the need for
DCR's POST /register and any server-side per-client storage.
"""

from __future__ import annotations

import socket
from typing import Any
from unittest.mock import patch

import httpx2
import pytest
from mcp.shared.auth import OAuthClientInformationFull

from rucio_mcp.auth.cimd import (
    CimdError,
    _PinnedTransport,
    assert_safe_url,
    build_client_from_document,
    client_with_requested_redirect,
    fetch_client_document,
    is_cimd_client_id,
    redirect_uri_matches,
    resolve_cimd_client,
)

_CLIENT_URL = "https://93.184.216.34/.well-known/oauth-client"
_LOOPBACK_CB = "http://localhost:51763/callback"


def _document(**overrides: object) -> dict[str, object]:
    doc: dict[str, object] = {
        "client_id": _CLIENT_URL,
        "redirect_uris": ["http://localhost/callback"],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
    }
    doc.update(overrides)
    return doc


class TestIsCimdClientId:
    @pytest.mark.parametrize(
        ("client_id", "expected"),
        [
            ("https://claude.ai/.well-known/oauth-client", True),
            ("https://example.com/client", True),
            ("be659aca-1234-5678-9abc-def012345678", False),  # DCR opaque id
            ("http://example.com/client", False),  # not https
            ("ftp://example.com/client", False),
            ("not a url", False),
            ("", False),
        ],
    )
    def test_detection(self, client_id: str, expected: bool) -> None:
        assert is_cimd_client_id(client_id) is expected


class TestRedirectUriMatches:
    def test_exact_match(self) -> None:
        assert redirect_uri_matches(_LOOPBACK_CB, _LOOPBACK_CB) is True

    def test_localhost_port_agnostic(self) -> None:
        # Claude Code declares http://localhost/callback and binds an ephemeral
        # port at runtime (RFC 8252 §8.3 / §7.3).
        assert redirect_uri_matches(_LOOPBACK_CB, "http://localhost/callback") is True

    def test_loopback_ipv4_port_agnostic(self) -> None:
        assert (
            redirect_uri_matches("http://127.0.0.1:8080/cb", "http://127.0.0.1:9090/cb")
            is True
        )

    def test_loopback_ipv6_port_agnostic(self) -> None:
        assert redirect_uri_matches("http://[::1]:8080/cb", "http://[::1]/cb") is True

    def test_different_path_rejected(self) -> None:
        assert (
            redirect_uri_matches("http://localhost:8080/cb", "http://localhost/other")
            is False
        )

    def test_non_loopback_port_mismatch_rejected(self) -> None:
        # Public hosts must match exactly — no port-agnostic leniency.
        assert (
            redirect_uri_matches(
                "https://app.example.com:8080/cb", "https://app.example.com/cb"
            )
            is False
        )

    def test_localhost_does_not_match_127(self) -> None:
        # host identity must hold; only the port is ignored.
        assert (
            redirect_uri_matches("http://localhost/cb", "http://127.0.0.1/cb") is False
        )


class TestAssertSafeUrl:
    async def test_public_ip_literal_ok(self) -> None:
        # An IP literal is returned verbatim as the sole vetted address.
        assert await assert_safe_url(_CLIENT_URL) == ["93.184.216.34"]

    async def test_http_rejected(self) -> None:
        with pytest.raises(CimdError, match="https"):
            await assert_safe_url("http://example.com/client")

    async def test_no_host_rejected(self) -> None:
        with pytest.raises(CimdError):
            await assert_safe_url("https:///client")

    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1/client",
            "https://10.0.0.5/client",
            "https://192.168.1.1/client",
            "https://169.254.1.1/client",  # link-local
            "https://[::1]/client",
        ],
    )
    async def test_private_ip_literal_rejected(self, url: str) -> None:
        with pytest.raises(CimdError, match=r"public|address"):
            await assert_safe_url(url)

    async def test_hostname_resolving_to_private_rejected(self) -> None:
        def resolver(*_args: object, **_kwargs: object) -> list[Any]:
            return [(socket.AF_INET, None, None, "", ("10.1.2.3", 443))]

        with pytest.raises(CimdError, match=r"non-public|resolves"):
            await assert_safe_url("https://evil.example.com/client", resolver=resolver)

    async def test_hostname_resolving_to_public_ok(self) -> None:
        def resolver(*_args: object, **_kwargs: object) -> list[Any]:
            return [
                (socket.AF_INET, None, None, "", ("93.184.216.34", 443)),
                (socket.AF_INET, None, None, "", ("93.184.216.35", 443)),
            ]

        # All vetted addresses are returned (deduplicated), for the fetch to pin to.
        vetted = await assert_safe_url("https://example.com/client", resolver=resolver)
        assert vetted == ["93.184.216.34", "93.184.216.35"]

    async def test_default_resolver_uses_event_loop(self) -> None:
        # With no injected resolver, resolution is offloaded to the running loop
        # so a slow OS resolver cannot block the event loop.
        async def fake_getaddrinfo(*_args: object, **_kwargs: object) -> list[Any]:
            return [(socket.AF_INET, None, None, "", ("93.184.216.34", 443))]

        with patch("asyncio.get_running_loop") as get_loop:
            get_loop.return_value.getaddrinfo = fake_getaddrinfo
            await assert_safe_url("https://example.com/client")


class TestFetchClientDocument:
    async def test_returns_parsed_json(self) -> None:
        def handler(_request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, json=_document())

        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler)
        ) as client:
            doc = await fetch_client_document(_CLIENT_URL, client=client)
        assert doc["client_id"] == _CLIENT_URL

    async def test_non_json_raises(self) -> None:
        def handler(_request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, text="<html>not json</html>")

        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler)
        ) as client:
            with pytest.raises(CimdError, match="JSON"):
                await fetch_client_document(_CLIENT_URL, client=client)

    async def test_http_error_raises(self) -> None:
        def handler(_request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(404)

        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler)
        ) as client:
            with pytest.raises(CimdError, match="fetch"):
                await fetch_client_document(_CLIENT_URL, client=client)

    async def test_non_object_json_rejected(self) -> None:
        # A top-level JSON array (not an object) is not a valid CIMD document.
        def handler(_request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, json=["not", "an", "object"])

        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler)
        ) as client:
            with pytest.raises(CimdError, match="JSON object"):
                await fetch_client_document(_CLIENT_URL, client=client)

    async def test_oversized_document_rejected(self) -> None:
        def handler(_request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, json={"padding": "x" * 200_000})

        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler)
        ) as client:
            with pytest.raises(CimdError, match="large"):
                await fetch_client_document(_CLIENT_URL, client=client, max_bytes=1024)


class TestBuildClientFromDocument:
    def test_builds_public_client(self) -> None:
        client = build_client_from_document(_document(), _CLIENT_URL)
        assert isinstance(client, OAuthClientInformationFull)
        assert client.client_id == _CLIENT_URL
        # public client → token endpoint accepts PKCE without a secret
        assert client.token_endpoint_auth_method == "none"

    def test_not_self_referential_raises(self) -> None:
        doc = _document(client_id="https://attacker.example.com/client")
        with pytest.raises(CimdError, match="self-referential"):
            build_client_from_document(doc, _CLIENT_URL)

    def test_missing_redirect_uris_raises(self) -> None:
        doc = _document()
        del doc["redirect_uris"]
        with pytest.raises(CimdError, match="redirect_uris"):
            build_client_from_document(doc, _CLIENT_URL)

    def test_only_declared_redirect_uris(self) -> None:
        # Canonical client carries exactly the document's redirect_uris; any
        # per-request ephemeral port is applied via
        # client_with_requested_redirect, never here.
        client = build_client_from_document(_document(), _CLIENT_URL)
        registered = [str(u) for u in (client.redirect_uris or [])]
        assert registered == ["http://localhost/callback"]


class TestClientWithRequestedRedirect:
    def test_appends_port_agnostic_loopback_request(self) -> None:
        # The document declares http://localhost/callback; Claude sends the same
        # with an ephemeral port. The exact requested value must be added so the
        # SDK's exact-match validate_redirect_uri() accepts it.
        canonical = build_client_from_document(_document(), _CLIENT_URL)
        client = client_with_requested_redirect(canonical, _LOOPBACK_CB)
        registered = [str(u) for u in (client.redirect_uris or [])]
        assert _LOOPBACK_CB in registered

    def test_returns_copy_leaving_original_untouched(self) -> None:
        canonical = build_client_from_document(_document(), _CLIENT_URL)
        client_with_requested_redirect(canonical, _LOOPBACK_CB)
        registered = [str(u) for u in (canonical.redirect_uris or [])]
        assert _LOOPBACK_CB not in registered

    def test_non_matching_request_not_appended(self) -> None:
        canonical = build_client_from_document(_document(), _CLIENT_URL)
        client = client_with_requested_redirect(
            canonical, "http://localhost:51763/somewhere-else"
        )
        registered = [str(u) for u in (client.redirect_uris or [])]
        assert "http://localhost:51763/somewhere-else" not in registered

    def test_no_request_returns_client_unchanged(self) -> None:
        canonical = build_client_from_document(_document(), _CLIENT_URL)
        assert client_with_requested_redirect(canonical, None) is canonical

    def test_exact_match_returns_client_unchanged(self) -> None:
        canonical = build_client_from_document(_document(), _CLIENT_URL)
        assert (
            client_with_requested_redirect(canonical, "http://localhost/callback")
            is canonical
        )


class TestResolveCimdClient:
    async def test_end_to_end(self) -> None:
        def handler(_request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, json=_document())

        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler)
        ) as client:
            resolved = await resolve_cimd_client(_CLIENT_URL, client=client)
        assert resolved.client_id == _CLIENT_URL
        assert resolved.token_endpoint_auth_method == "none"
        assert [str(u) for u in (resolved.redirect_uris or [])] == [
            "http://localhost/callback"
        ]

    async def test_unsafe_url_rejected_before_fetch(self) -> None:
        # A private-IP client_id must be rejected without any network call.
        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(
                lambda _r: pytest.fail("should not fetch unsafe URL")
            )
        ) as client:
            with pytest.raises(CimdError):
                await resolve_cimd_client("https://10.0.0.1/client", client=client)


class TestPinnedTransport:
    """The pinning transport is what closes the DNS-rebinding TOCTOU: it connects
    to a pre-vetted IP while keeping the real hostname for TLS and the Host header.
    """

    @staticmethod
    def _capturing() -> tuple[list[httpx2.Request], httpx2.MockTransport]:
        seen: list[httpx2.Request] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.append(request)
            return httpx2.Response(200, json={"ok": True})

        return seen, httpx2.MockTransport(handler)

    async def test_connects_to_vetted_ip_not_hostname(self) -> None:
        # The vetted IP is the connection target; the hostname is never re-resolved.
        seen, mock = self._capturing()
        transport = _PinnedTransport(["93.184.216.34"], "example.com", wrapped=mock)
        async with httpx2.AsyncClient(transport=transport) as client:
            await client.get("https://example.com:8443/path?q=1")
        req = seen[0]
        assert req.url.host == "93.184.216.34"
        # port and path survive the host rewrite
        assert req.url.port == 8443
        assert req.url.path == "/path"

    async def test_preserves_sni_and_host_header(self) -> None:
        # TLS verification must still target the real hostname, and the origin
        # server must see its own Host — so pinning stays transparent end to end.
        seen, mock = self._capturing()
        transport = _PinnedTransport(["93.184.216.34"], "example.com", wrapped=mock)
        async with httpx2.AsyncClient(transport=transport) as client:
            await client.get("https://example.com:8443/path")
        req = seen[0]
        assert req.extensions["sni_hostname"] == "example.com"
        assert req.headers["Host"] == "example.com:8443"

    async def test_rebinding_blocked(self) -> None:
        # Simulate rebinding: assert_safe_url vets a public IP, then the fetch is
        # pinned to it. Even if DNS would now answer with a private IP, the
        # connection targets only the vetted public address.
        def resolver(*_args: object, **_kwargs: object) -> list[Any]:
            return [(socket.AF_INET, None, None, "", ("93.184.216.34", 443))]

        vetted = await assert_safe_url(
            "https://rebind.example.com/client", resolver=resolver
        )
        seen, mock = self._capturing()
        transport = _PinnedTransport(vetted, "rebind.example.com", wrapped=mock)
        async with httpx2.AsyncClient(transport=transport) as client:
            await client.get("https://rebind.example.com/client")
        assert seen[0].url.host == "93.184.216.34"

    async def test_ipv6_vetted_ip(self) -> None:
        seen, mock = self._capturing()
        transport = _PinnedTransport(
            ["2606:2800:220:1:248:1893:25c8:1946"], "example.com", wrapped=mock
        )
        async with httpx2.AsyncClient(transport=transport) as client:
            await client.get("https://example.com/x")
        assert seen[0].url.host == "2606:2800:220:1:248:1893:25c8:1946"
        assert seen[0].extensions["sni_hostname"] == "example.com"

    async def test_failover_to_next_vetted_ip(self) -> None:
        # A dead first address must not abort the fetch; the next vetted IP is tried.
        seen: list[str] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.append(request.url.host)
            if request.url.host == "93.184.216.34":
                msg = "refused"
                raise httpx2.ConnectError(msg, request=request)
            return httpx2.Response(200, json={"ok": True})

        transport = _PinnedTransport(
            ["93.184.216.34", "93.184.216.35"],
            "example.com",
            wrapped=httpx2.MockTransport(handler),
        )
        async with httpx2.AsyncClient(transport=transport) as client:
            resp = await client.get("https://example.com/x")
        assert resp.status_code == 200
        assert seen == ["93.184.216.34", "93.184.216.35"]

    async def test_all_ips_down_raises_last_error(self) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            msg = "refused"
            raise httpx2.ConnectError(msg, request=request)

        transport = _PinnedTransport(
            ["93.184.216.34", "93.184.216.35"],
            "example.com",
            wrapped=httpx2.MockTransport(handler),
        )
        async with httpx2.AsyncClient(transport=transport) as client:
            with pytest.raises(httpx2.ConnectError):
                await client.get("https://example.com/x")
