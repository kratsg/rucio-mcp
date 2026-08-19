"""Broker mode: per-user Rucio access behind the AF MCP credential broker.

In broker mode this server sits behind af-mcp-platform's aggregator, which
forwards a broker-issued identity JWT (RS256, ``aud`` = this backend) as the
request bearer. The token is verified against the broker's JWKS, and the same
bearer is then redeemed at the broker for the caller's VOMS proxy, which
authenticates a fresh rucio client for exactly one tool call — the proxy file
is deleted the moment the client has authenticated (never persisted).

Requires the ``broker`` extra: ``pip install rucio-mcp[broker]``.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver.exceptions import ToolError
from rucio.client import Client

from rucio_mcp.auth.factory import RucioClientFactory

try:
    from af_credentials.mcp import mcp_token_verifier
    from af_credentials.proxy import (
        ProxyClient,
        ProxyNotAvailableError,
        ProxyRedeemError,
    )
    from af_credentials.verifier import BrokerTokenVerifier

    HAS_AF_CREDENTIALS = True
except ImportError:  # pragma: no cover - exercised only without the extra
    HAS_AF_CREDENTIALS = False

    class ProxyNotAvailableError(Exception):  # type: ignore[no-redef]
        """Placeholder so except clauses type-check; never raised without the extra."""

    class ProxyRedeemError(Exception):  # type: ignore[no-redef]
        """Placeholder so except clauses type-check; never raised without the extra."""


if TYPE_CHECKING:
    from mcp.server.auth.provider import TokenVerifier

    from rucio_mcp.auth.rucio_cfg import RucioCfg

MISSING_AF_CREDENTIALS_MSG = (
    "broker mode requires the af-credentials package. "
    "Install it via the 'broker' extra: pip install rucio-mcp[broker]"
)

_PROXY_NOT_AVAILABLE_MSG = (
    "No VOMS proxy is available for your account: {detail}. "
    "Link your grid certificate on the Analysis Facility portal "
    "(x509 credential linking), then retry this tool."
)

_PROXY_REDEEM_FAILED_MSG = (
    "The credential broker could not supply your VOMS proxy: {detail}. "
    "This may be transient — retry the tool; if it persists, contact the "
    "Analysis Facility admins."
)


def extract_bearer(ctx: Any) -> str:
    """Return the bearer token from the current request's Authorization header.

    The token has already been verified by the server's TokenVerifier before
    any tool runs; this re-reads it so it can be redeemed at the broker.

    Raises:
        PermissionError: If the header is missing or not a Bearer scheme.
    """
    auth = ctx.request_context.request.headers.get("authorization", "") or ""
    if not auth.lower().startswith("bearer "):
        msg = "Missing Bearer token in Authorization header"
        raise PermissionError(msg)
    return auth[7:].strip()


def extract_unixname(bearer: str) -> str | None:
    """Return the ``unixname`` claim of a broker-issued identity JWT, if any.

    The signature is NOT checked here — the server's TokenVerifier has
    already verified the token against the broker's JWKS before any tool
    runs; this merely re-reads a claim from the trusted payload. Returns
    ``None`` when the claim is absent (the platform's backends config did
    not set ``include_posix`` for this target) or the token is not a JWT.
    """
    parts = bearer.split(".")
    if len(parts) != 3:
        return None
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (binascii.Error, ValueError):
        return None
    unixname = claims.get("unixname") if isinstance(claims, dict) else None
    return unixname if isinstance(unixname, str) else None


def make_broker_token_verifier(
    jwks_url: str, issuer: str, audience: str
) -> TokenVerifier:
    """Build the mcp TokenVerifier that checks broker-issued identity JWTs."""
    if not HAS_AF_CREDENTIALS:
        raise ImportError(MISSING_AF_CREDENTIALS_MSG)
    verifier: TokenVerifier = mcp_token_verifier(
        BrokerTokenVerifier(jwks_url, issuer, audience)
    )
    return verifier


def make_proxy_client(broker_url: str) -> Any:
    """Build the af-credentials ProxyClient used to redeem VOMS proxies."""
    if not HAS_AF_CREDENTIALS:
        raise ImportError(MISSING_AF_CREDENTIALS_MSG)
    return ProxyClient(broker_url)


class ProxyAuthClient(Client):
    """A rucio Client authenticated by a short-lived VOMS proxy file.

    Disables the on-disk token cache BaseClient keeps under
    ``/tmp/.rucio_<user>/``: in broker mode one server process serves many
    users, so a shared cache file would hand one caller's rucio token to
    another. Every construction therefore performs a fresh
    ``/auth/x509_proxy`` round trip and nothing is written to disk.
    """

    def _BaseClient__read_token(self) -> bool:  # pylint: disable=invalid-name
        return False

    def _BaseClient__write_token(self) -> None:  # pylint: disable=invalid-name
        return


class BrokerProxyClientFactory(RucioClientFactory):
    """Back each tool call with the caller's freshly redeemed VOMS proxy.

    Every call redeems the request bearer at the broker (the broker caches
    the proxy; redeeming is a cheap in-cluster round trip), materializes the
    PEM as a private 0600 file, authenticates a fresh :class:`ProxyAuthClient`
    against it, and deletes the file as soon as authentication completes —
    success or failure. The client then carries a per-call rucio token in
    memory; nothing is cached server-side.

    The rucio account is taken from the verified JWT's ``unixname`` claim
    (present when the platform's backends config sets ``include_posix`` for
    this target); without it the account is left unset and the Rucio server
    resolves it from the proxy DN's default-account mapping.
    """

    def __init__(self, proxy_client: Any, *, cfg: RucioCfg) -> None:
        """Store the redeem client and the site config providing the rucio hosts."""
        if not HAS_AF_CREDENTIALS:
            raise ImportError(MISSING_AF_CREDENTIALS_MSG)
        self._proxy_client = proxy_client
        self._cfg = cfg
        # The redeem coroutine runs on this worker's private event loop while
        # the caller blocks on .result() (tool calls in this codebase block on
        # rucio I/O anyway), so a single worker is never contended.
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="broker-redeem"
        )

    def get_client(self, ctx: Any) -> Any:
        """Return a per-call rucio client authenticated by the caller's proxy."""
        bearer = extract_bearer(ctx)
        account = extract_unixname(bearer)
        try:
            handle = self._executor.submit(
                asyncio.run, self._proxy_client.proxy_file(bearer)
            ).result()
        except ProxyNotAvailableError as exc:
            raise ToolError(
                _PROXY_NOT_AVAILABLE_MSG.format(detail=exc.detail)
            ) from exc
        except ProxyRedeemError as exc:
            raise ToolError(_PROXY_REDEEM_FAILED_MSG.format(detail=exc.detail)) from exc
        # The handle deletes the proxy file on exit — even if authentication
        # (performed inside ProxyAuthClient.__init__) fails.
        with handle:
            return ProxyAuthClient(
                rucio_host=self._cfg.rucio_host,
                auth_host=self._cfg.auth_host,
                account=account,
                auth_type="x509_proxy",
                creds={"client_proxy": str(handle.path)},
            )

    def close(self) -> None:
        """Shut down the redeem executor; proxy files are already deleted per call."""
        self._executor.shutdown(wait=False)
