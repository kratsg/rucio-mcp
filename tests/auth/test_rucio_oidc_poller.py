"""Tests for RucioOidcPoller — async wrapper around rucio /auth/oidc polling."""

from __future__ import annotations

import asyncio
import ssl
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from rucio_mcp.auth.rucio_oidc_poller import RucioOidcPoller, _ssl_context

if TYPE_CHECKING:
    from pathlib import Path

_MODULE = "rucio_mcp.auth.rucio_oidc_poller"


class TestSslContext:
    def test_returns_true_when_cert_dir_not_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("X509_CERT_DIR", raising=False)
        assert _ssl_context() is True

    def test_returns_true_when_cert_dir_does_not_exist(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("X509_CERT_DIR", str(tmp_path / "nonexistent"))
        assert _ssl_context() is True

    def test_returns_ssl_context_when_cert_dir_is_valid(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("X509_CERT_DIR", str(tmp_path))
        result = _ssl_context()
        assert isinstance(result, ssl.SSLContext)


@pytest.fixture
def poller() -> RucioOidcPoller:
    return RucioOidcPoller(
        auth_host="https://rucio-auth.example.com",
        account="alice",
        oidc_audience="rucio",
        oidc_scope="openid profile offline_access",
        oidc_issuer="escape",
    )


def _mock_client(get_side_effect: Any) -> MagicMock:
    """Build a mock httpx.AsyncClient context manager."""
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False
    mock_client.get = AsyncMock(side_effect=get_side_effect)
    return mock_client


def _response(status: int = 200, headers: dict[str, str] | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    _headers = headers or {}
    r.headers.get = lambda key, default=None: _headers.get(key, default)
    r.raise_for_status = (
        MagicMock()
        if status < 400
        else MagicMock(side_effect=Exception(f"HTTP {status}"))
    )
    return r


class TestBaseHeaders:
    def test_required_headers_present(self, poller: RucioOidcPoller) -> None:
        h = poller._base_headers()
        assert h["X-Rucio-Account"] == "alice"
        assert h["X-Rucio-Client-Authorize-Auto"] == "False"
        assert h["X-Rucio-Client-Authorize-Polling"] == "True"
        assert h["X-Rucio-Client-Authorize-Scope"] == "openid profile offline_access"
        assert h["X-Rucio-Client-Authorize-Refresh-Lifetime"] == "96"

    def test_audience_header_included_when_set(self, poller: RucioOidcPoller) -> None:
        h = poller._base_headers()
        assert h["X-Rucio-Client-Authorize-Audience"] == "rucio"

    def test_issuer_header_included_when_set(self, poller: RucioOidcPoller) -> None:
        h = poller._base_headers()
        assert h["X-Rucio-Client-Authorize-Issuer"] == "escape"

    def test_audience_header_omitted_when_empty(self) -> None:
        p = RucioOidcPoller(
            auth_host="https://r",
            account="bob",
            oidc_audience="",
            oidc_scope="openid",
            oidc_issuer="",
        )
        h = p._base_headers()
        assert "X-Rucio-Client-Authorize-Audience" not in h

    def test_issuer_header_omitted_when_empty(self) -> None:
        p = RucioOidcPoller(
            auth_host="https://r",
            account="bob",
            oidc_audience="",
            oidc_scope="openid",
            oidc_issuer="",
        )
        h = p._base_headers()
        assert "X-Rucio-Client-Authorize-Issuer" not in h


class TestRequestAuthUrl:
    async def test_returns_polling_url_from_header(
        self, poller: RucioOidcPoller
    ) -> None:
        polling_url = "https://rucio-auth.example.com/auth/oidc_token?state=xyz_polling"
        mock = _mock_client(
            get_side_effect=[_response(200, {"X-Rucio-OIDC-Auth-URL": polling_url})]
        )

        with patch(f"{_MODULE}.httpx.AsyncClient", return_value=mock):
            url = await poller.request_auth_url()

        assert url == polling_url

    async def test_raises_when_header_absent(self, poller: RucioOidcPoller) -> None:
        mock = _mock_client(get_side_effect=[_response(200)])

        with (
            patch(f"{_MODULE}.httpx.AsyncClient", return_value=mock),
            pytest.raises(RuntimeError, match="X-Rucio-OIDC-Auth-URL"),
        ):
            await poller.request_auth_url()

    async def test_raises_on_http_error(self, poller: RucioOidcPoller) -> None:
        bad_resp = _response(401)
        bad_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "401", request=MagicMock(), response=MagicMock()
            )
        )
        mock = _mock_client(get_side_effect=[bad_resp])

        with (
            patch(f"{_MODULE}.httpx.AsyncClient", return_value=mock),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await poller.request_auth_url()


class TestPollForToken:
    async def test_returns_token_when_ready_on_third_poll(
        self, poller: RucioOidcPoller
    ) -> None:
        responses = [
            _response(200),
            _response(200),
            _response(200, {"X-Rucio-Auth-Token": "rucio_session_xyz"}),
        ]
        mock = _mock_client(get_side_effect=responses)

        with patch(f"{_MODULE}.httpx.AsyncClient", return_value=mock):
            token = await poller.poll_for_token(
                "https://rucio-auth.example.com/auth/oidc_redirect?state=xyz_polling",
                timeout=5.0,
                interval=0.0,
            )

        assert token == "rucio_session_xyz"
        assert mock.get.call_count == 3

    async def test_times_out_when_token_never_arrives(
        self, poller: RucioOidcPoller
    ) -> None:
        async def _always_pending(*_args: Any, **_kwargs: Any) -> MagicMock:
            return _response(200)

        mock = AsyncMock()
        mock.__aenter__.return_value = mock
        mock.__aexit__.return_value = False
        mock.get = _always_pending

        with (
            patch(f"{_MODULE}.httpx.AsyncClient", return_value=mock),
            pytest.raises(asyncio.TimeoutError),
        ):
            await poller.poll_for_token(
                "https://rucio-auth.example.com/auth/oidc_redirect?state=xyz_polling",
                timeout=0.05,
                interval=0.01,
            )

    async def test_fetch_token_header_sent(self, poller: RucioOidcPoller) -> None:
        seen_kwargs: list[dict[str, Any]] = []

        async def _capture(*_args: Any, **kwargs: Any) -> MagicMock:
            seen_kwargs.append(kwargs)
            return _response(200, {"X-Rucio-Auth-Token": "tok"})

        mock = AsyncMock()
        mock.__aenter__.return_value = mock
        mock.__aexit__.return_value = False
        mock.get = _capture

        with patch(f"{_MODULE}.httpx.AsyncClient", return_value=mock):
            await poller.poll_for_token(
                "https://rucio-auth.example.com/auth/oidc_redirect?state=xyz_polling",
                timeout=5.0,
                interval=0.0,
            )

        headers_sent = seen_kwargs[0]["headers"]
        assert headers_sent["X-Rucio-Client-Fetch-Token"] == "True"
