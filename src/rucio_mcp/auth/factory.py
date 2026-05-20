"""Rucio client factory: abstracts how the rucio.Client is obtained per-request."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import jwt

from rucio_mcp.auth.token_client import TokenInjectedClient

if TYPE_CHECKING:
    from rucio.client import Client

    from rucio_mcp.auth.session_cache import SessionCache


class RucioClientFactory(ABC):
    """Returns the rucio.Client appropriate for the current request/session."""

    @abstractmethod
    def get_client(self, ctx: Any) -> Client: ...

    @abstractmethod
    def close(self) -> None:
        """Release any cached clients or resources."""


class EnvBasedClientFactory(RucioClientFactory):
    """Stdio-mode factory: wraps a single Client built from process env vars."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get_client(self, _ctx: Any) -> Client:
        return self._client

    def close(self) -> None:
        """No-op: stdio client holds no resources to release."""


def _extract_request_auth(ctx: Any) -> tuple[str, str, str, float]:
    """Extract (session_id, bearer_token, rucio_account, exp) from the request.

    Reads the MCP-Session-Id header, Authorization: Bearer header, and optionally
    the X-Rucio-Account header. Falls back to the JWT preferred_username then sub
    claim for the Rucio account name. JWT claims are decoded without signature
    verification — full verification happens upstream in the token verifier.
    """
    req = ctx.request_context.request
    session_id: str = req.headers.get("mcp-session-id", "")
    auth: str = req.headers.get("authorization", "") or ""
    if not auth.lower().startswith("bearer "):
        msg = "Missing Bearer token in Authorization header"
        raise PermissionError(msg)
    bearer = auth[7:].strip()
    claims = jwt.decode(bearer, options={"verify_signature": False})
    account: str = (
        req.headers.get("x-rucio-account")
        or claims.get("preferred_username")
        or claims["sub"]
    )
    return session_id, bearer, account, float(claims["exp"])


class BearerTokenClientFactory(RucioClientFactory):
    """HTTP-mode factory: builds and caches one TokenInjectedClient per MCP session."""

    def __init__(self, cache: SessionCache) -> None:
        self._cache = cache

    def get_client(self, ctx: Any) -> Client:
        session_id, bearer, account, exp = _extract_request_auth(ctx)
        cached = self._cache.get(session_id)
        if cached is not None:
            return cached
        client = TokenInjectedClient(bearer_token=bearer, account=account)
        self._cache.put(session_id, client, exp)
        return client

    def close(self) -> None:
        self._cache.close()
