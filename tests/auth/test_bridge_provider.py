"""Tests for RucioBridgeProvider — OAuthAuthorizationServerProvider bridge."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.auth.provider import AuthorizationCode, AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from rucio_mcp.auth.bridge_provider import RucioBridgeProvider
from rucio_mcp.auth.bridge_state import BridgeSession, BridgeStateStore
from rucio_mcp.auth.rucio_cfg import RucioCfg

_MODULE = "rucio_mcp.auth.bridge_provider"


@pytest.fixture
def cfg() -> RucioCfg:
    return RucioCfg(
        rucio_host="https://rucio.example.com",
        auth_host="https://rucio-auth.example.com",
        account="alice",
        oidc_audience="rucio",
        oidc_scope="openid profile",
        oidc_issuer="escape",
    )


@pytest.fixture
def provider(cfg: RucioCfg) -> RucioBridgeProvider:
    return RucioBridgeProvider(rucio_cfg=cfg, resource_url="http://localhost:8000")


@pytest.fixture
def client_info() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="mcp-client-abc",
        redirect_uris=[AnyUrl("http://localhost:1234/callback")],
    )


@pytest.fixture
def auth_params() -> AuthorizationParams:
    return AuthorizationParams(
        state="csrf-state",
        scopes=["openid"],
        code_challenge="challenge-abc",
        redirect_uri=AnyUrl("http://localhost:1234/callback"),
        redirect_uri_provided_explicitly=True,
    )


def _make_session(session_id: str = "sess-1", **kwargs: Any) -> BridgeSession:
    defaults: dict[str, Any] = {
        "session_id": session_id,
        "polling_url": "https://rucio-auth.example.com/auth/oidc_redirect?state=xyz_polling",
        "code_challenge": "challenge-abc",
        "redirect_uri": "http://localhost:1234/callback",
        "redirect_uri_provided_explicitly": True,
        "client_id": "mcp-client-abc",
        "scopes": ["openid"],
        "resource": None,
        "state": "csrf-state",
        "expires_at": time.time() + 300,
    }
    defaults.update(kwargs)
    return BridgeSession(**defaults)


class TestClientRegistry:
    async def test_get_unknown_client_returns_none(
        self, provider: RucioBridgeProvider
    ) -> None:
        result = await provider.get_client("nonexistent")
        assert result is None

    async def test_register_then_get_roundtrip(
        self, provider: RucioBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        await provider.register_client(client_info)
        result = await provider.get_client("mcp-client-abc")
        assert result is client_info


class TestAuthorize:
    async def test_returns_bridge_url(
        self,
        provider: RucioBridgeProvider,
        client_info: OAuthClientInformationFull,
        auth_params: AuthorizationParams,
    ) -> None:
        with patch.object(
            provider._poller, "request_auth_url", new=AsyncMock(return_value="https://idp.example.com/login?state=xyz_polling")
        ):
            url = await provider.authorize(client_info, auth_params)

        assert url.startswith("http://localhost:8000/bridge?session=")

    async def test_authorize_creates_pending_session(
        self,
        provider: RucioBridgeProvider,
        client_info: OAuthClientInformationFull,
        auth_params: AuthorizationParams,
    ) -> None:
        with patch.object(
            provider._poller, "request_auth_url", new=AsyncMock(return_value="https://idp.example.com/login?state=xyz_polling")
        ):
            url = await provider.authorize(client_info, auth_params)

        session_id = url.split("session=")[1]
        session = provider._store.get_by_session_id(session_id)
        assert session is not None
        assert session.status == "pending"
        assert session.polling_url == "https://idp.example.com/login?state=xyz_polling"
        assert session.code_challenge == "challenge-abc"

    async def test_authorize_starts_bg_task(
        self,
        provider: RucioBridgeProvider,
        client_info: OAuthClientInformationFull,
        auth_params: AuthorizationParams,
    ) -> None:
        mock_bg = AsyncMock()
        with (
            patch.object(provider._poller, "request_auth_url", new=AsyncMock(return_value="https://idp.example.com/login")),
            patch.object(provider, "_bg_poll", mock_bg),
        ):
            await provider.authorize(client_info, auth_params)
            await asyncio.sleep(0)  # let the task scheduler run

        mock_bg.assert_called_once()


class TestBgPoll:
    async def test_bg_poll_marks_done_on_success(
        self, provider: RucioBridgeProvider
    ) -> None:
        session = _make_session("s1")
        provider._store.put(session)

        with patch.object(
            provider._poller,
            "poll_for_token",
            new=AsyncMock(return_value="rucio-session-token-xyz"),
        ):
            await provider._bg_poll("s1")

        s = provider._store.get_by_session_id("s1")
        assert s is not None
        assert s.status == "done"
        assert s.rucio_token == "rucio-session-token-xyz"
        assert s.auth_code is not None

    async def test_bg_poll_marks_error_on_timeout(
        self, provider: RucioBridgeProvider
    ) -> None:
        session = _make_session("s2")
        provider._store.put(session)

        with patch.object(
            provider._poller,
            "poll_for_token",
            new=AsyncMock(side_effect=asyncio.TimeoutError),
        ):
            await provider._bg_poll("s2")

        s = provider._store.get_by_session_id("s2")
        assert s is not None
        assert s.status == "error"
        assert s.error_message is not None

    async def test_bg_poll_noop_for_unknown_session(
        self, provider: RucioBridgeProvider
    ) -> None:
        # Must not raise
        await provider._bg_poll("ghost")


class TestLoadAuthorizationCode:
    async def test_returns_none_for_unknown_code(
        self, provider: RucioBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        result = await provider.load_authorization_code(client_info, "bad-code")
        assert result is None

    async def test_returns_none_for_pending_session(
        self, provider: RucioBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        session = _make_session("s1")
        provider._store.put(session)
        provider._store.mark_done("s1", rucio_token="tok", auth_code="code-abc")
        # Manually reset to pending to simulate race
        s = provider._store.get_by_session_id("s1")
        assert s is not None
        s.status = "pending"

        result = await provider.load_authorization_code(client_info, "code-abc")
        assert result is None

    async def test_returns_authorization_code_for_done_session(
        self, provider: RucioBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        session = _make_session("s1")
        provider._store.put(session)
        provider._store.mark_done("s1", rucio_token="tok", auth_code="code-abc")

        result = await provider.load_authorization_code(client_info, "code-abc")
        assert result is not None
        assert isinstance(result, AuthorizationCode)
        assert result.code == "code-abc"
        assert result.code_challenge == "challenge-abc"
        assert result.client_id == "mcp-client-abc"


class TestExchangeAuthorizationCode:
    async def test_returns_rucio_token_as_access_token(
        self, provider: RucioBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        session = _make_session("s1")
        provider._store.put(session)
        provider._store.mark_done("s1", rucio_token="rucio-session-tok", auth_code="code-abc")

        auth_code = AuthorizationCode(
            code="code-abc",
            scopes=["openid"],
            expires_at=time.time() + 300,
            client_id="mcp-client-abc",
            code_challenge="challenge-abc",
            redirect_uri=AnyUrl("http://localhost:1234/callback"),
            redirect_uri_provided_explicitly=True,
        )
        token = await provider.exchange_authorization_code(client_info, auth_code)
        assert isinstance(token, OAuthToken)
        assert token.access_token == "rucio-session-tok"
        assert token.token_type == "Bearer"
        assert token.refresh_token is None

    async def test_raises_on_missing_session(
        self, provider: RucioBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        from mcp.server.auth.provider import TokenError

        auth_code = AuthorizationCode(
            code="nonexistent",
            scopes=[],
            expires_at=time.time() + 300,
            client_id="mcp-client-abc",
            code_challenge="abc",
            redirect_uri=AnyUrl("http://localhost:1234/callback"),
            redirect_uri_provided_explicitly=True,
        )
        with pytest.raises(TokenError):
            await provider.exchange_authorization_code(client_info, auth_code)


class TestLoadAccessToken:
    async def test_returns_synthetic_access_token(
        self, provider: RucioBridgeProvider
    ) -> None:
        from mcp.server.auth.provider import AccessToken

        result = await provider.load_access_token("rucio-bearer-xyz")
        assert result is not None
        assert isinstance(result, AccessToken)
        assert result.token == "rucio-bearer-xyz"

    async def test_no_validation_any_string_accepted(
        self, provider: RucioBridgeProvider
    ) -> None:
        result = await provider.load_access_token("not-a-real-token")
        assert result is not None


class TestRefreshAndRevoke:
    async def test_load_refresh_token_returns_none(
        self, provider: RucioBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        result = await provider.load_refresh_token(client_info, "any-token")
        assert result is None

    async def test_exchange_refresh_token_raises(
        self, provider: RucioBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        from mcp.server.auth.provider import RefreshToken, TokenError

        rt = RefreshToken(token="rt", client_id="c", scopes=[])
        with pytest.raises(TokenError):
            await provider.exchange_refresh_token(client_info, rt, [])

    async def test_revoke_token_is_noop(
        self, provider: RucioBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        from mcp.server.auth.provider import AccessToken

        token = AccessToken(token="tok", client_id="c", scopes=[])
        await provider.revoke_token(token)  # must not raise
