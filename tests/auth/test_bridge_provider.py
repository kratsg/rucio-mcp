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

from rucio_mcp.auth import bridge_provider as _bp
from rucio_mcp.auth.bridge_provider import (
    _DEFAULT_EXPIRES_IN,
    BridgePoller,
    RucioBridgeProvider,
    _authorize_redirect_uri,
    _jwt_expires_in,
)
from rucio_mcp.auth.bridge_state import BridgeSession
from rucio_mcp.auth.cimd import CimdError
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

    async def test_register_client_not_supported(
        self, provider: RucioBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        """DCR is disabled — register_client must raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await provider.register_client(client_info)

    async def test_non_cimd_client_id_returns_none(
        self, provider: RucioBridgeProvider
    ) -> None:
        """An opaque (non-URL) client_id is unknown without DCR → None."""
        result = await provider.get_client("opaque-dcr-style-id")
        assert result is None

    async def test_cimd_client_id_resolved_and_cached(
        self, provider: RucioBridgeProvider
    ) -> None:
        """An https-URL client_id is resolved via CIMD and cached for reuse."""
        cimd_id = "https://claude.ai/.well-known/oauth-client"
        resolved = OAuthClientInformationFull(
            client_id=cimd_id,
            redirect_uris=[AnyUrl("http://localhost/callback")],
            token_endpoint_auth_method="none",
        )
        with patch(
            f"{_MODULE}.resolve_cimd_client", AsyncMock(return_value=resolved)
        ) as mock_resolve:
            first = await provider.get_client(cimd_id)
            # Second lookup must hit the cache, not re-fetch the document.
            second = await provider.get_client(cimd_id)

        assert first is resolved
        assert second is resolved
        mock_resolve.assert_awaited_once()

    async def test_cimd_passes_authorize_redirect_uri(
        self, provider: RucioBridgeProvider
    ) -> None:
        """The /authorize redirect_uri contextvar is applied to the resolved client."""
        cimd_id = "https://claude.ai/.well-known/oauth-client"
        requested = "http://localhost:51763/callback"
        resolved = OAuthClientInformationFull(
            client_id=cimd_id,
            redirect_uris=[AnyUrl("http://localhost/callback")],
            token_endpoint_auth_method="none",
        )
        token = _authorize_redirect_uri.set(requested)
        try:
            with patch(
                f"{_MODULE}.resolve_cimd_client", AsyncMock(return_value=resolved)
            ):
                client = await provider.get_client(cimd_id)
        finally:
            _authorize_redirect_uri.reset(token)
        assert client is not None
        client.validate_redirect_uri(AnyUrl(requested))

    async def test_cimd_resolution_failure_returns_none(
        self, provider: RucioBridgeProvider
    ) -> None:
        """A CimdError during resolution yields None (no client), not an exception."""
        cimd_id = "https://claude.ai/.well-known/oauth-client"
        with patch(
            f"{_MODULE}.resolve_cimd_client",
            AsyncMock(side_effect=CimdError("bad document")),
        ):
            result = await provider.get_client(cimd_id)
        assert result is None

    async def test_cimd_second_authorize_with_new_ephemeral_port(
        self, provider: RucioBridgeProvider
    ) -> None:
        """Re-auth with a fresh loopback port must validate against the cached client.

        Claude Code binds a new ephemeral localhost port on every auth attempt
        (RFC 8252 §7.3); the client cached during the first /authorize must not
        pin the first attempt's port.  Regression test for the second-auth
        ``invalid_request: Redirect URI not registered for client``.
        """
        cimd_id = "https://claude.ai/oauth/claude-code-client-metadata"
        doc = {
            "client_id": cimd_id,
            "redirect_uris": [
                "http://localhost/callback",
                "http://127.0.0.1/callback",
            ],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
        }
        with (
            patch("rucio_mcp.auth.cimd.assert_safe_url"),
            patch(
                "rucio_mcp.auth.cimd.fetch_client_document",
                AsyncMock(return_value=doc),
            ),
        ):
            token = _authorize_redirect_uri.set("http://localhost:54321/callback")
            try:
                first = await provider.get_client(cimd_id)
            finally:
                _authorize_redirect_uri.reset(token)
            token = _authorize_redirect_uri.set("http://localhost:55985/callback")
            try:
                second = await provider.get_client(cimd_id)
            finally:
                _authorize_redirect_uri.reset(token)

        assert first is not None
        assert second is not None
        # The SDK's exact-match gate must accept each attempt's own port.
        first.validate_redirect_uri(AnyUrl("http://localhost:54321/callback"))
        second.validate_redirect_uri(AnyUrl("http://localhost:55985/callback"))

    async def test_cimd_cache_stores_canonical_client(
        self, provider: RucioBridgeProvider
    ) -> None:
        """The cached CIMD client holds only the document's declared redirect URIs.

        Per-request ephemeral ports are appended to a copy, never stored, so the
        cache neither pins the first port nor accumulates one entry per attempt.
        """
        cimd_id = "https://claude.ai/oauth/claude-code-client-metadata"
        declared = ["http://localhost/callback", "http://127.0.0.1/callback"]
        doc = {
            "client_id": cimd_id,
            "redirect_uris": declared,
            "token_endpoint_auth_method": "none",
        }
        with (
            patch("rucio_mcp.auth.cimd.assert_safe_url"),
            patch(
                "rucio_mcp.auth.cimd.fetch_client_document",
                AsyncMock(return_value=doc),
            ),
        ):
            token = _authorize_redirect_uri.set("http://localhost:54321/callback")
            try:
                await provider.get_client(cimd_id)
            finally:
                _authorize_redirect_uri.reset(token)

        cached = provider._cache_get(cimd_id)
        assert cached is not None
        assert [str(u) for u in (cached.redirect_uris or [])] == declared

    async def test_token_leg_returns_cached_client_unchanged(
        self, provider: RucioBridgeProvider
    ) -> None:
        """With the contextvar unset (/token leg) the cached client is returned as-is."""
        cimd_id = "https://claude.ai/.well-known/oauth-client"
        resolved = OAuthClientInformationFull(
            client_id=cimd_id,
            redirect_uris=[AnyUrl("http://localhost:1234/callback")],
            token_endpoint_auth_method="none",
        )
        with patch(f"{_MODULE}.resolve_cimd_client", AsyncMock(return_value=resolved)):
            tok = _authorize_redirect_uri.set("http://localhost:1234/callback")
            try:
                await provider.get_client(cimd_id)
            finally:
                _authorize_redirect_uri.reset(tok)
            # /token leg: no contextvar → identical cached object.
            assert await provider.get_client(cimd_id) is resolved


class TestCimdClientCache:
    """The resolved-CIMD-client cache is TTL- and size-bounded (issue #44)."""

    def _client(self, cid: str) -> OAuthClientInformationFull:
        return OAuthClientInformationFull(
            client_id=cid,
            redirect_uris=[AnyUrl("http://localhost/callback")],
            token_endpoint_auth_method="none",
        )

    def test_expired_entry_evicted(self, provider: RucioBridgeProvider) -> None:
        cid = "https://claude.ai/a"
        provider._cache_put(cid, self._client(cid))
        assert provider._cache_get(cid) is not None
        # Force expiry by rewriting the stored deadline into the past.
        client, _ = provider._clients[cid]
        provider._clients[cid] = (client, time.time() - 1)
        assert provider._cache_get(cid) is None
        assert cid not in provider._clients

    def test_size_cap_evicts_oldest(
        self, provider: RucioBridgeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_bp, "_CIMD_CACHE_MAX", 2)
        for name in ("a", "b", "c"):
            cid = f"https://claude.ai/{name}"
            provider._cache_put(cid, self._client(cid))
        assert provider._cache_get("https://claude.ai/a") is None  # oldest evicted
        assert provider._cache_get("https://claude.ai/b") is not None
        assert provider._cache_get("https://claude.ai/c") is not None


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


class TestAclose:
    async def test_authorize_tracks_bg_task(
        self,
        provider: RucioBridgeProvider,
        mock_poller: AsyncMock,
        client_info: OAuthClientInformationFull,
        auth_params: AuthorizationParams,
    ) -> None:
        mock_poller.request_auth_url.return_value = "https://idp.example.com/login"
        started = asyncio.Event()

        async def _never_returns(*_a: Any, **_kw: Any) -> str:
            started.set()
            await asyncio.Event().wait()  # never fires
            return "unreachable"

        mock_poller.poll_for_token.side_effect = _never_returns
        await provider.authorize(client_info, auth_params)
        await started.wait()
        assert len(provider._bg_tasks) == 1
        await provider.aclose()

    async def test_aclose_cancels_pending_poll_tasks(
        self,
        provider: RucioBridgeProvider,
        mock_poller: AsyncMock,
        client_info: OAuthClientInformationFull,
        auth_params: AuthorizationParams,
    ) -> None:
        mock_poller.request_auth_url.return_value = "https://idp.example.com/login"
        started = asyncio.Event()

        async def _never_returns(*_a: Any, **_kw: Any) -> str:
            started.set()
            await asyncio.Event().wait()
            return "unreachable"

        mock_poller.poll_for_token.side_effect = _never_returns
        await provider.authorize(client_info, auth_params)
        await started.wait()
        task = next(iter(provider._bg_tasks))

        await provider.aclose()
        assert task.cancelled()
        assert not provider._bg_tasks

    async def test_aclose_noop_without_tasks(
        self, provider: RucioBridgeProvider
    ) -> None:
        await provider.aclose()  # must not raise


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

    async def test_authorization_code_is_single_use(
        self, provider: RucioBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        """OAuth 2.1: a replayed /token request with the same code must fail."""
        session = _make_session("s-once")
        provider.store.put(session)
        provider.store.mark_done(
            "s-once", rucio_token="rucio-tok", auth_code="once-code"
        )
        auth_code = AuthorizationCode(
            code="once-code",
            scopes=["openid"],
            expires_at=time.time() + 300,
            client_id="mcp-client-abc",
            code_challenge="challenge-abc",
            redirect_uri=AnyUrl("http://localhost:1234/callback"),
            redirect_uri_provided_explicitly=True,
        )
        first = await provider.exchange_authorization_code(client_info, auth_code)
        assert first.access_token == "rucio-tok"
        # Second exchange with the captured code must be rejected.
        with pytest.raises(TokenError) as exc_info:
            await provider.exchange_authorization_code(client_info, auth_code)
        assert exc_info.value.error == "invalid_grant"


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


def _make_test_jwt(payload: dict[str, object]) -> str:
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
        provider.store.mark_done(
            "exp-s1", rucio_token=rucio_token, auth_code="exp-code"
        )

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
        provider.store.mark_done(
            "exp-s2", rucio_token="opaque-token", auth_code="exp-code2"
        )

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
