"""Rucio client factory: abstracts how the rucio.Client is obtained per-request."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from rucio_mcp.auth.token_client import TokenInjectedClient

if TYPE_CHECKING:
    from rucio.client import Client

    from rucio_mcp.auth.rucio_cfg import RucioCfg
    from rucio_mcp.auth.session_cache import SessionCache


class RucioClientFactory(ABC):
    """Returns the rucio.Client appropriate for the current request/session."""

    @abstractmethod
    def get_client(self, ctx: Any) -> Client:
        """Return the rucio Client for the given request context."""

    @abstractmethod
    def close(self) -> None:
        """Release any cached clients or resources."""


class EnvBasedClientFactory(RucioClientFactory):
    """Stdio-mode factory: wraps a single Client built from process env vars."""

    def __init__(self, client: Client) -> None:
        """Store the pre-built client."""
        self._client = client

    def get_client(self, _ctx: Any) -> Client:
        """Return the single shared client regardless of context."""
        return self._client

    def close(self) -> None:
        """No-op: stdio client holds no resources to release."""


def _extract_request_auth(
    ctx: Any, *, default_account: str = ""
) -> tuple[str, str, str]:
    """Extract (session_id, bearer_token, rucio_account) from the request.

    The bearer token IS the rucio session token — no JWT decode is performed.
    Account comes from the X-Rucio-Account header, falling back to default_account.
    """
    req = ctx.request_context.request
    session_id: str = req.headers.get("mcp-session-id", "")
    auth: str = req.headers.get("authorization", "") or ""
    if not auth.lower().startswith("bearer "):
        msg = "Missing Bearer token in Authorization header"
        raise PermissionError(msg)
    bearer = auth[7:].strip()
    account: str = req.headers.get("x-rucio-account") or default_account
    return session_id, bearer, account


class BearerTokenClientFactory(RucioClientFactory):
    """HTTP-mode factory: builds and caches one TokenInjectedClient per MCP session.

    Site-bound: one factory per site, with cfg providing rucio_host, auth_host,
    auth_type, and the default account. The bearer token is extracted per-request.
    """

    def __init__(self, cache: SessionCache, cfg: RucioCfg) -> None:
        """Store the session cache and the site configuration."""
        self._cache = cache
        self._cfg = cfg

    def get_client(self, ctx: Any) -> Client:
        """Return a cached or newly built TokenInjectedClient for this session."""
        session_id, bearer, account = _extract_request_auth(
            ctx, default_account=self._cfg.account
        )
        cached = self._cache.get(session_id)
        if cached is not None:
            return cached
        client = TokenInjectedClient(
            bearer_token=bearer,
            account=account,
            rucio_host=self._cfg.rucio_host,
            auth_host=self._cfg.auth_host,
            auth_type=self._cfg.auth_type,
        )
        self._cache.put(session_id, client, time.time() + 300)
        return client

    def close(self) -> None:
        """Evict all cached clients."""
        self._cache.close()
