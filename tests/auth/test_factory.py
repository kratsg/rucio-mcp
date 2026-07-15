"""Tests for RucioClientFactory and EnvBasedClientFactory."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from rucio_mcp.auth.factory import (
    BearerTokenClientFactory,
    EnvBasedClientFactory,
    RucioClientFactory,
    _extract_request_auth,
)
from rucio_mcp.auth.session_cache import SessionCache
from rucio_mcp.auth.token_client import TokenInjectedClient


def test_env_factory_returns_same_client_each_call():
    pre_built = MagicMock(name="rucio_client")
    factory = EnvBasedClientFactory(client=pre_built)
    ctx = MagicMock()
    assert factory.get_client(ctx) is pre_built
    assert factory.get_client(ctx) is pre_built


def test_factory_is_abstract():
    with pytest.raises(TypeError):
        RucioClientFactory()  # type: ignore[abstract]


def test_env_factory_close_is_noop():
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

    def test_extracts_session_id_bearer_account(self) -> None:
        ctx = self._make_ctx("rucio-session-tok", session_id="my-session")
        session_id, bearer, account = _extract_request_auth(
            ctx, default_account="alice"
        )
        assert session_id == "my-session"
        assert bearer == "rucio-session-tok"
        assert account == "alice"

    def test_x_rucio_account_header_overrides_default(self) -> None:
        ctx = self._make_ctx("tok", x_rucio_account="override-account")
        _, _, account = _extract_request_auth(ctx, default_account="default-alice")
        assert account == "override-account"

    def test_falls_back_to_default_account_when_header_absent(self) -> None:
        ctx = self._make_ctx("tok")
        _, _, account = _extract_request_auth(ctx, default_account="cfg-account")
        assert account == "cfg-account"

    def test_missing_bearer_raises_permission_error(self) -> None:
        ctx = MagicMock()
        ctx.request_context.request.headers.get.side_effect = {
            "mcp-session-id": "s"
        }.get
        with pytest.raises(PermissionError, match="Bearer"):
            _extract_request_auth(ctx)


def _make_rucio_cfg(
    rucio_host: str = "https://rucio.example.com",
    auth_host: str = "https://rucio-auth.example.com",
    account: str = "alice",
    auth_type: str = "oidc",
) -> MagicMock:
    cfg = MagicMock()
    cfg.rucio_host = rucio_host
    cfg.auth_host = auth_host
    cfg.account = account
    cfg.auth_type = auth_type
    return cfg


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
        ctx = self._make_ctx("rucio-session-tok")
        cache = SessionCache()
        factory = BearerTokenClientFactory(cache=cache, cfg=_make_rucio_cfg())
        with patch.object(TokenInjectedClient, "__init__", lambda _s, **_kw: None):
            client = factory.get_client(ctx)
        assert isinstance(client, TokenInjectedClient)

    def test_get_client_returns_cached_client_on_second_call(self) -> None:
        ctx = self._make_ctx("rucio-session-tok", session_id="fixed-session")
        cache = SessionCache()
        factory = BearerTokenClientFactory(cache=cache, cfg=_make_rucio_cfg())
        with patch.object(TokenInjectedClient, "__init__", lambda _s, **_kw: None):
            first = factory.get_client(ctx)
            second = factory.get_client(ctx)
        assert first is second

    def test_get_client_uses_fixed_ttl(self) -> None:
        ctx = self._make_ctx("rucio-session-tok", session_id="ttl-session")
        cache = MagicMock(spec=SessionCache)
        cache.get.return_value = None
        factory = BearerTokenClientFactory(cache=cache, cfg=_make_rucio_cfg())
        before = time.time()
        with patch.object(TokenInjectedClient, "__init__", lambda _s, **_kw: None):
            factory.get_client(ctx)
        _, call_args, _ = cache.put.mock_calls[0]
        expires_at = call_args[2]
        assert before + 290 < expires_at < before + 310

    def test_get_client_passes_cfg_to_token_client(self) -> None:
        ctx = self._make_ctx("rucio-session-tok")
        cache = SessionCache()
        cfg = _make_rucio_cfg(
            rucio_host="https://custom-rucio.example.com",
            auth_host="https://custom-auth.example.com",
            auth_type="oidc",
        )
        factory = BearerTokenClientFactory(cache=cache, cfg=cfg)
        captured: dict[str, object] = {}

        def fake_init(_self: object, **kw: object) -> None:
            captured.update(kw)

        with patch.object(TokenInjectedClient, "__init__", fake_init):
            factory.get_client(ctx)

        assert captured["rucio_host"] == "https://custom-rucio.example.com"
        assert captured["auth_host"] == "https://custom-auth.example.com"
        assert captured["auth_type"] == "oidc"

    def test_close_delegates_to_cache(self) -> None:
        cache = MagicMock(spec=SessionCache)
        factory = BearerTokenClientFactory(cache=cache, cfg=_make_rucio_cfg())
        factory.close()
        cache.close.assert_called_once()

    def test_same_session_different_bearer_not_cached(self) -> None:
        """A stale session id with a different bearer must not reuse the old client."""
        cache = SessionCache()
        factory = BearerTokenClientFactory(cache=cache, cfg=_make_rucio_cfg())
        ctx1 = self._make_ctx("real-token", session_id="fixed-session")
        ctx2 = self._make_ctx("garbage", session_id="fixed-session")
        with patch.object(TokenInjectedClient, "__init__", lambda _s, **_kw: None):
            first = factory.get_client(ctx1)
            second = factory.get_client(ctx2)
        assert first is not second

    def test_same_session_same_bearer_hits_cache(self) -> None:
        cache = SessionCache()
        factory = BearerTokenClientFactory(cache=cache, cfg=_make_rucio_cfg())
        ctx1 = self._make_ctx("real-token", session_id="fixed-session")
        ctx2 = self._make_ctx("real-token", session_id="fixed-session")
        with patch.object(TokenInjectedClient, "__init__", lambda _s, **_kw: None):
            first = factory.get_client(ctx1)
            second = factory.get_client(ctx2)
        assert first is second

    def test_reauth_with_fresh_bearer_rebuilds_client(self) -> None:
        """A client that re-authenticates mid-session must not keep the stale token."""
        cache = SessionCache()
        factory = BearerTokenClientFactory(cache=cache, cfg=_make_rucio_cfg())
        ctx_old = self._make_ctx("old-token", session_id="fixed-session")
        ctx_new = self._make_ctx("new-token", session_id="fixed-session")
        captured: list[dict[str, object]] = []

        def fake_init(_self: object, **kw: object) -> None:
            captured.append(dict(kw))

        with patch.object(TokenInjectedClient, "__init__", fake_init):
            factory.get_client(ctx_old)
            factory.get_client(ctx_new)
        assert captured[0]["bearer_token"] == "old-token"
        assert captured[1]["bearer_token"] == "new-token"

    def test_missing_session_id_skips_cache(self) -> None:
        """Empty mcp-session-id must never be cached (no cross-tenant sharing)."""
        cache = SessionCache()
        factory = BearerTokenClientFactory(cache=cache, cfg=_make_rucio_cfg())
        ctx1 = self._make_ctx("tok", session_id="")
        ctx2 = self._make_ctx("tok", session_id="")
        with patch.object(TokenInjectedClient, "__init__", lambda _s, **_kw: None):
            first = factory.get_client(ctx1)
            second = factory.get_client(ctx2)
        assert first is not second
        assert cache.size() == 0
