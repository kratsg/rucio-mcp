"""Rucio client factory: abstracts how the rucio.Client is obtained per-request."""

from __future__ import annotations

import hashlib
import logging
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from rucio_mcp.auth.token_client import TokenInjectedClient

_log = logging.getLogger(__name__)

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


def _cache_key(session_id: str, bearer: str) -> str:
    """Bind a cache entry to both the session id and the bearer it was built for.

    A bare session id is a routing identifier that leaks into logs/proxies;
    hashing the bearer into the key prevents it from acting as a credential.
    """
    bearer_hash = hashlib.sha256(bearer.encode()).hexdigest()[:16]
    return f"{session_id}:{bearer_hash}"


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
        """Return a cached or newly built TokenInjectedClient for this session.

        The cache key binds the session id to a hash of the bearer, so a
        stale/guessed session id paired with a different bearer never
        returns another caller's client, and a session that re-authenticates
        with a fresh bearer rebuilds rather than reusing the stale token.
        Requests without a session id (e.g. stateless mode) are never
        cached, to avoid sharing a client across unrelated callers.
        """
        session_id, bearer, account = _extract_request_auth(
            ctx, default_account=self._cfg.account
        )
        _log.debug(
            "get_client session=%s…, bearer prefix=%s…",
            session_id[:8] if session_id else "(none)",
            bearer[:8],
        )
        cache_key = _cache_key(session_id, bearer) if session_id else None
        cached = self._cache.get(cache_key) if cache_key else None
        if cached is not None:
            _log.debug("get_client cache HIT for session=%s…", session_id[:8])
            return cached
        _log.debug(
            "get_client cache MISS for session=%s…, building new client",
            session_id[:8] if session_id else "(none)",
        )
        client = TokenInjectedClient(
            bearer_token=bearer,
            account=account,
            rucio_host=self._cfg.rucio_host,
            auth_host=self._cfg.auth_host,
            auth_type=self._cfg.auth_type,
        )
        if cache_key:
            self._cache.put(cache_key, client, time.time() + 300)
        return client

    def close(self) -> None:
        """Evict all cached clients."""
        self._cache.close()
