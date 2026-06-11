"""Tests for RucioBridgeProvider — OAuthAuthorizationServerProvider bridge."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from prometheus_client import REGISTRY
from pydantic import AnyUrl

from rucio_mcp.auth.bridge_provider import (
    BridgePoller,
    RucioBridgeProvider,
    _DEFAULT_EXPIRES_IN,
    _jwt_expires_in,
)
from rucio_mcp.auth.bridge_state import BridgeSession
from rucio_mcp.auth.rucio_cfg import RucioCfg

_MODULE = "rucio_mcp.auth.bridge_provider"


@pytest.fixture
def cfg() -> RucioCfg:
    return RucioCfg(
        rucio_host="https://rucio.example.com",
        auth_host="https://rucio-auth.example.com",
        account="alice",
        auth_type="oidc",
        oidc_audience="rucio",
        oidc_scope="openid profile",
        oidc_issuer="escape",
    )


@pytest.fixture
def mock_poller() -> AsyncMock:
    poller = AsyncMock(spec=BridgePoller)
    poller.auth_host = "https://rucio-auth.example.com"
    return poller


@pytest.fixture
def provider(mock_poller: AsyncMock) -> RucioBridgeProvider:
    return RucioBridgeProvider(poller=mock_poller, resource_url="http://localhost:8000")


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
        mock_poller: AsyncMock,
        client_info: OAuthClientInformationFull,
        auth_params: AuthorizationParams,
    ) -> None:
        mock_poller.request_auth_url.return_value = (
            "https://idp.example.com/login?state=xyz_polling"
        )
        url = await provider.authorize(client_info, auth_params)
        assert url.startswith("http://localhost:8000/bridge?session=")

    async def test_authorize_creates_pending_session(
        self,
        provider: RucioBridgeProvider,
        mock_poller: AsyncMock,
        client_info: OAuthClientInformationFull,
        auth_params: AuthorizationParams,
    ) -> None:
        mock_poller.request_auth_url.return_value = (
            "https://idp.example.com/login?state=xyz_polling"
        )
        url = await provider.authorize(client_info, auth_params)

        session_id = url.split("session=")[1]
        session = provider.store.get_by_session_id(session_id)
        assert session is not None
        assert session.status == "pending"
        assert session.polling_url == "https://idp.example.com/login?state=xyz_polling"
        assert session.code_challenge == "challenge-abc"

    async def test_authorize_starts_bg_task(
        self,
        provider: RucioBridgeProvider,
        mock_poller: AsyncMock,
        client_info: OAuthClientInformationFull,
        auth_params: AuthorizationParams,
    ) -> None:
        mock_poller.request_auth_url.return_value = "https://idp.example.com/login"
        mock_bg = AsyncMock()
        with patch.object(provider, "_bg_poll", mock_bg):
            await provider.authorize(client_info, auth_params)
            await asyncio.sleep(0)

        mock_bg.assert_called_once()

    async def test_account_extracted_from_resource_url_stored_in_session(
        self,
        provider: RucioBridgeProvider,
        mock_poller: AsyncMock,
        client_info: OAuthClientInformationFull,
    ) -> None:
        mock_poller.request_auth_url.return_value = "https://idp.example.com/login"
        params = AuthorizationParams(
            state="csrf-state",
            scopes=["openid"],
            code_challenge="challenge-abc",
            redirect_uri=AnyUrl("http://localhost:1234/callback"),
            redirect_uri_provided_explicitly=True,
            resource="http://localhost:8000/site/escape/?account=alice",
        )
        url = await provider.authorize(client_info, params)
        session_id = url.split("session=")[1]
        session = provider.store.get_by_session_id(session_id)
        assert session is not None
        assert session.account == "alice"

    async def test_account_passed_to_request_auth_url(
        self,
        provider: RucioBridgeProvider,
        mock_poller: AsyncMock,
        client_info: OAuthClientInformationFull,
    ) -> None:
        mock_poller.request_auth_url.return_value = "https://idp.example.com/login"
        params = AuthorizationParams(
            state="csrf-state",
            scopes=["openid"],
            code_challenge="challenge-abc",
            redirect_uri=AnyUrl("http://localhost:1234/callback"),
            redirect_uri_provided_explicitly=True,
            resource="http://localhost:8000/site/escape/?account=alice",
        )
        await provider.authorize(client_info, params)
        mock_poller.request_auth_url.assert_called_once_with(account="alice")

    async def test_account_empty_when_resource_has_no_account_param(
        self,
        provider: RucioBridgeProvider,
        mock_poller: AsyncMock,
        client_info: OAuthClientInformationFull,
        auth_params: AuthorizationParams,
    ) -> None:
        mock_poller.request_auth_url.return_value = "https://idp.example.com/login"
        url = await provider.authorize(client_info, auth_params)
        session_id = url.split("session=")[1]
        session = provider.store.get_by_session_id(session_id)
        assert session is not None
        assert session.account == ""


class TestBgPoll:
    async def test_bg_poll_marks_done_on_success(
        self, provider: RucioBridgeProvider, mock_poller: AsyncMock
    ) -> None:
        session = _make_session("s1")
        provider.store.put(session)
        mock_poller.poll_for_token.return_value = "rucio-session-token-xyz"
        await provider._bg_poll("s1")

        s = provider.store.get_by_session_id("s1")
        assert s is not None
        assert s.status == "done"
        assert s.rucio_token == "rucio-session-token-xyz"
        assert s.auth_code is not None

    async def test_bg_poll_marks_error_on_timeout(
        self, provider: RucioBridgeProvider, mock_poller: AsyncMock
    ) -> None:
        session = _make_session("s2")
        provider.store.put(session)
        mock_poller.poll_for_token.side_effect = asyncio.TimeoutError
        await provider._bg_poll("s2")

        s = provider.store.get_by_session_id("s2")
        assert s is not None
        assert s.status == "error"
        assert s.error_message is not None

    async def test_bg_poll_noop_for_unknown_session(
        self, provider: RucioBridgeProvider
    ) -> None:
        # Must not raise
        await provider._bg_poll("ghost")

    async def test_bg_poll_passes_session_account_to_poll_for_token(
        self, provider: RucioBridgeProvider, mock_poller: AsyncMock
    ) -> None:
        session = _make_session("s-acct", account="alice")
        provider.store.put(session)
        mock_poller.poll_for_token.return_value = "rucio-session-token-xyz"
        await provider._bg_poll("s-acct")
        mock_poller.poll_for_token.assert_called_once_with(
            session.polling_url, account="alice", timeout=180.0
        )

    async def test_bg_poll_uses_configured_poll_timeout(
        self, mock_poller: AsyncMock
    ) -> None:
        provider = RucioBridgeProvider(
            poller=mock_poller, resource_url="http://localhost:8000", poll_timeout=30.0
        )
        session = _make_session("s-timeout")
        provider.store.put(session)
        mock_poller.poll_for_token.return_value = "tok"
        await provider._bg_poll("s-timeout")
        _, _, kwargs = mock_poller.poll_for_token.mock_calls[0]
        assert kwargs.get("timeout") == 30.0


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
        provider.store.put(session)
        provider.store.mark_done("s1", rucio_token="tok", auth_code="code-abc")
        # Manually reset to pending to simulate race
        s = provider.store.get_by_session_id("s1")
        assert s is not None
        s.status = "pending"

        result = await provider.load_authorization_code(client_info, "code-abc")
        assert result is None

    async def test_returns_authorization_code_for_done_session(
        self, provider: RucioBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        session = _make_session("s1")
        provider.store.put(session)
        provider.store.mark_done("s1", rucio_token="tok", auth_code="code-abc")

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
        provider.store.put(session)
        provider.store.mark_done(
            "s1", rucio_token="rucio-session-tok", auth_code="code-abc"
        )

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
        rt = RefreshToken(token="rt", client_id="c", scopes=[])
        with pytest.raises(TokenError):
            await provider.exchange_refresh_token(client_info, rt, [])

    async def test_revoke_token_is_noop(self, provider: RucioBridgeProvider) -> None:
        token = AccessToken(token="tok", client_id="c", scopes=[])
        await provider.revoke_token(token)  # must not raise


class TestBridgeAuthCounter:
    """rucio_mcp_bridge_auth_total must track auth outcomes per site."""

    @pytest.fixture
    def provider_site(self, mock_poller: AsyncMock) -> RucioBridgeProvider:
        return RucioBridgeProvider(
            poller=mock_poller,
            resource_url="http://localhost:8000",
            site_name="counter_test_site",
        )

    def _counter(self, outcome: str) -> float:
        return (
            REGISTRY.get_sample_value(
                "rucio_mcp_bridge_auth_total",
                {"site": "counter_test_site", "outcome": outcome},
            )
            or 0.0
        )

    async def test_authorize_increments_started(
        self,
        provider_site: RucioBridgeProvider,
        mock_poller: AsyncMock,
        client_info: OAuthClientInformationFull,
        auth_params: AuthorizationParams,
    ) -> None:
        mock_poller.request_auth_url.return_value = "https://idp.example.com/login"
        before = self._counter("started")
        with patch.object(provider_site, "_bg_poll", AsyncMock()):
            await provider_site.authorize(client_info, auth_params)
            await asyncio.sleep(0)
        assert self._counter("started") - before == 1.0

    async def test_bg_poll_success_increments_success(
        self,
        provider_site: RucioBridgeProvider,
        mock_poller: AsyncMock,
    ) -> None:
        session = _make_session("c-s1")
        provider_site.store.put(session)
        mock_poller.poll_for_token.return_value = "tok"
        before = self._counter("success")
        await provider_site._bg_poll("c-s1")
        assert self._counter("success") - before == 1.0

    async def test_bg_poll_timeout_increments_timeout(
        self,
        provider_site: RucioBridgeProvider,
        mock_poller: AsyncMock,
    ) -> None:
        session = _make_session("c-s2")
        provider_site.store.put(session)
        mock_poller.poll_for_token.side_effect = asyncio.TimeoutError
        before = self._counter("timeout")
        await provider_site._bg_poll("c-s2")
        assert self._counter("timeout") - before == 1.0

    async def test_bg_poll_error_increments_failure(
        self,
        provider_site: RucioBridgeProvider,
        mock_poller: AsyncMock,
    ) -> None:
        session = _make_session("c-s3")
        provider_site.store.put(session)
        mock_poller.poll_for_token.side_effect = RuntimeError("network down")
        before = self._counter("failure")
        await provider_site._bg_poll("c-s3")
        assert self._counter("failure") - before == 1.0


def _make_test_jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}."


class TestJwtExpiresIn:
    def test_future_exp_returns_remaining_seconds(self) -> None:
        future = int(time.time()) + 3600
        token = _make_test_jwt({"exp": future})
        result = _jwt_expires_in(token)
        assert 3595 <= result <= 3600

    def test_past_exp_returns_zero(self) -> None:
        past = int(time.time()) - 60
        token = _make_test_jwt({"exp": past})
        assert _jwt_expires_in(token) == 0

    def test_no_exp_claim_returns_default(self) -> None:
        token = _make_test_jwt({"sub": "alice"})
        assert _jwt_expires_in(token) == _DEFAULT_EXPIRES_IN

    def test_opaque_token_returns_default(self) -> None:
        assert _jwt_expires_in("opaque-no-dots") == _DEFAULT_EXPIRES_IN

    def test_malformed_payload_returns_default(self) -> None:
        # valid header, invalid base64 body
        assert _jwt_expires_in("header.!!!.sig") == _DEFAULT_EXPIRES_IN


class TestExchangeAuthorizationCodeExpiresIn:
    async def test_expires_in_reflects_jwt_lifetime(
        self, provider: RucioBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        future_exp = int(time.time()) + 3600
        rucio_token = _make_test_jwt({"exp": future_exp, "sub": "alice"})

        session = _make_session("exp-s1")
        provider.store.put(session)
        provider.store.mark_done("exp-s1", rucio_token=rucio_token, auth_code="exp-code")

        auth_code = AuthorizationCode(
            code="exp-code",
            scopes=["openid"],
            expires_at=time.time() + 300,
            client_id="mcp-client-abc",
            code_challenge="challenge-abc",
            redirect_uri=AnyUrl("http://localhost:1234/callback"),
            redirect_uri_provided_explicitly=True,
        )
        token = await provider.exchange_authorization_code(client_info, auth_code)
        assert token.access_token == rucio_token
        assert token.expires_in is not None
        assert 3595 <= token.expires_in <= 3600

    async def test_expires_in_opaque_token_uses_default(
        self, provider: RucioBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        session = _make_session("exp-s2")
        provider.store.put(session)
        provider.store.mark_done("exp-s2", rucio_token="opaque-token", auth_code="exp-code2")

        auth_code = AuthorizationCode(
            code="exp-code2",
            scopes=["openid"],
            expires_at=time.time() + 300,
            client_id="mcp-client-abc",
            code_challenge="challenge-abc",
            redirect_uri=AnyUrl("http://localhost:1234/callback"),
            redirect_uri_provided_explicitly=True,
        )
        token = await provider.exchange_authorization_code(client_info, auth_code)
        assert token.expires_in == _DEFAULT_EXPIRES_IN
