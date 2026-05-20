"""Tests for RucioClientFactory and EnvBasedClientFactory."""

from __future__ import annotations

import base64
import json
import time
from unittest.mock import MagicMock, patch

import pytest


def _make_jwt_payload(sub: str, exp: float, **extra: object) -> str:
    """Create a minimal unsigned JWT (header.payload.signature) for testing."""
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=")
    claims = {"sub": sub, "exp": exp, **extra}
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=")
    return f"{header.decode()}.{payload.decode()}."


def test_env_factory_returns_same_client_each_call():
    from rucio_mcp.auth.factory import EnvBasedClientFactory

    pre_built = MagicMock(name="rucio_client")
    factory = EnvBasedClientFactory(client=pre_built)
    ctx = MagicMock()
    assert factory.get_client(ctx) is pre_built
    assert factory.get_client(ctx) is pre_built


def test_factory_is_abstract():
    from rucio_mcp.auth.factory import RucioClientFactory

    with pytest.raises(TypeError):
        RucioClientFactory()  # type: ignore[abstract]


def test_env_factory_close_is_noop():
    from rucio_mcp.auth.factory import EnvBasedClientFactory

    factory = EnvBasedClientFactory(client=MagicMock())
    factory.close()  # should not raise


class TestExtractRequestAuth:
    def _make_ctx(
        self,
        bearer: str,
        session_id: str = "sess-1",
        x_rucio_account: str | None = None,
    ) -> MagicMock:
        ctx = MagicMock()
        headers: dict[str, str] = {
            "authorization": f"Bearer {bearer}",
            "mcp-session-id": session_id,
        }
        if x_rucio_account is not None:
            headers["x-rucio-account"] = x_rucio_account
        ctx.request_context.request.headers.get.side_effect = headers.get
        return ctx

    def test_extracts_session_id_bearer_account_exp(self) -> None:
        from rucio_mcp.auth.factory import _extract_request_auth

        exp = time.time() + 3600
        token = _make_jwt_payload("user-sub", exp, preferred_username="alice")
        ctx = self._make_ctx(token, session_id="my-session")

        session_id, bearer, account, token_exp = _extract_request_auth(ctx)

        assert session_id == "my-session"
        assert bearer == token
        assert account == "alice"
        assert abs(token_exp - exp) < 1

    def test_falls_back_to_sub_when_no_preferred_username(self) -> None:
        from rucio_mcp.auth.factory import _extract_request_auth

        token = _make_jwt_payload("user-sub-42", time.time() + 3600)
        ctx = self._make_ctx(token)

        _, _, account, _ = _extract_request_auth(ctx)

        assert account == "user-sub-42"

    def test_x_rucio_account_header_takes_priority(self) -> None:
        from rucio_mcp.auth.factory import _extract_request_auth

        token = _make_jwt_payload("user-sub", time.time() + 3600, preferred_username="alice")
        ctx = self._make_ctx(token, x_rucio_account="override-account")

        _, _, account, _ = _extract_request_auth(ctx)

        assert account == "override-account"

    def test_missing_bearer_raises_permission_error(self) -> None:
        from rucio_mcp.auth.factory import _extract_request_auth

        ctx = MagicMock()
        ctx.request_context.request.headers.get.side_effect = {"mcp-session-id": "s"}.get

        with pytest.raises(PermissionError, match="Bearer"):
            _extract_request_auth(ctx)


class TestBearerTokenClientFactory:
    def _make_ctx(self, bearer: str, session_id: str = "sess-1") -> MagicMock:
        ctx = MagicMock()
        headers: dict[str, str] = {
            "authorization": f"Bearer {bearer}",
            "mcp-session-id": session_id,
        }
        ctx.request_context.request.headers.get.side_effect = headers.get
        return ctx

    def test_get_client_builds_token_injected_client(self) -> None:
        from rucio_mcp.auth.factory import BearerTokenClientFactory
        from rucio_mcp.auth.session_cache import SessionCache
        from rucio_mcp.auth.token_client import TokenInjectedClient

        exp = time.time() + 3600
        token = _make_jwt_payload("alice", exp, preferred_username="alice")
        ctx = self._make_ctx(token)

        cache = SessionCache()
        factory = BearerTokenClientFactory(cache=cache)

        with patch.object(TokenInjectedClient, "__init__", lambda self, **kw: None):
            client = factory.get_client(ctx)

        assert isinstance(client, TokenInjectedClient)

    def test_get_client_returns_cached_client_on_second_call(self) -> None:
        from rucio_mcp.auth.factory import BearerTokenClientFactory
        from rucio_mcp.auth.session_cache import SessionCache
        from rucio_mcp.auth.token_client import TokenInjectedClient

        exp = time.time() + 3600
        token = _make_jwt_payload("alice", exp, preferred_username="alice")
        ctx = self._make_ctx(token, session_id="fixed-session")

        cache = SessionCache()
        factory = BearerTokenClientFactory(cache=cache)

        with patch.object(TokenInjectedClient, "__init__", lambda self, **kw: None):
            first = factory.get_client(ctx)
            second = factory.get_client(ctx)

        assert first is second

    def test_close_delegates_to_cache(self) -> None:
        from rucio_mcp.auth.factory import BearerTokenClientFactory
        from rucio_mcp.auth.session_cache import SessionCache

        cache = MagicMock(spec=SessionCache)
        factory = BearerTokenClientFactory(cache=cache)
        factory.close()
        cache.close.assert_called_once()
