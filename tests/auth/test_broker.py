"""Tests for broker mode: bearer extraction, claims, and the proxy-backed factory."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import mkstemp
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

af_credentials = pytest.importorskip("af_credentials")

from af_credentials.proxy import (  # noqa: E402
    ProxyHandle,
    ProxyNotAvailableError,
    ProxyRedeemError,
)

from rucio_mcp.auth.broker import (  # noqa: E402
    BrokerProxyClientFactory,
    ProxyAuthClient,
    extract_bearer,
    extract_unixname,
)
from rucio_mcp.auth.rucio_cfg import RucioCfg  # noqa: E402


def _make_ctx(headers: dict[str, str]) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context.request.headers = headers
    return ctx


def _make_cfg() -> RucioCfg:
    return RucioCfg(
        rucio_host="https://rucio.atlas.cern.ch",
        auth_host="https://atlas-rucio-auth.cern.ch",
        account="",
        auth_type="oidc",
        oidc_audience="",
        oidc_scope="",
        oidc_issuer="",
    )


def _b64url(data: dict[str, object]) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    return raw.rstrip("=")


def _make_jwt(payload: dict[str, object]) -> str:
    """Build an unsigned JWT-shaped bearer (verification happens upstream)."""
    return f"{_b64url({'alg': 'RS256'})}.{_b64url(payload)}.sig"


def _utc_soon() -> datetime:
    return datetime.now(tz=timezone.utc) + timedelta(hours=1)


class _FakeProxyClient:
    """Duck-typed stand-in for af_credentials.proxy.ProxyClient."""

    def __init__(self) -> None:
        self.seen_bearers: list[str] = []
        self.created_paths: list[Path] = []

    async def proxy_file(self, bearer: str) -> ProxyHandle:
        self.seen_bearers.append(bearer)
        fd, raw_path = mkstemp(prefix="test-proxy-", suffix=".pem")
        os.close(fd)
        path = Path(raw_path)
        path.write_text("FAKE PEM")
        self.created_paths.append(path)
        return ProxyHandle(path=path, dn="/CN=test", expires_at=_utc_soon())


class _UnavailableProxyClient:
    async def proxy_file(self, _bearer: str) -> ProxyHandle:
        detail = "no linked credential"
        raise ProxyNotAvailableError(detail)


class _FailingProxyClient:
    async def proxy_file(self, _bearer: str) -> ProxyHandle:
        raise ProxyRedeemError(503, "broker melted")


class TestExtractBearer:
    def test_returns_token(self) -> None:
        ctx = _make_ctx({"authorization": "Bearer abc123"})
        assert extract_bearer(ctx) == "abc123"

    def test_case_insensitive_scheme(self) -> None:
        ctx = _make_ctx({"authorization": "bearer abc123"})
        assert extract_bearer(ctx) == "abc123"

    def test_missing_header_raises(self) -> None:
        ctx = _make_ctx({})
        with pytest.raises(PermissionError, match="Bearer"):
            extract_bearer(ctx)

    def test_non_bearer_scheme_raises(self) -> None:
        ctx = _make_ctx({"authorization": "Basic dXNlcjpwYXNz"})
        with pytest.raises(PermissionError, match="Bearer"):
            extract_bearer(ctx)


class TestExtractUnixname:
    def test_returns_unixname_claim(self) -> None:
        token = _make_jwt({"sub": "gstark", "unixname": "gstark"})
        assert extract_unixname(token) == "gstark"

    def test_missing_claim_returns_none(self) -> None:
        token = _make_jwt({"sub": "gstark"})
        assert extract_unixname(token) is None

    def test_malformed_token_returns_none(self) -> None:
        assert extract_unixname("not-a-jwt") is None

    def test_non_string_claim_returns_none(self) -> None:
        token = _make_jwt({"unixname": 42})
        assert extract_unixname(token) is None


class TestProxyAuthClient:
    def test_disk_token_cache_read_is_disabled(self) -> None:
        client = ProxyAuthClient.__new__(ProxyAuthClient)
        assert client._BaseClient__read_token() is False

    def test_disk_token_cache_write_is_disabled(self) -> None:
        client = ProxyAuthClient.__new__(ProxyAuthClient)
        assert client._BaseClient__write_token() is None


class TestBrokerProxyClientFactory:
    def test_client_built_from_redeemed_proxy_file(self) -> None:
        proxy_client = _FakeProxyClient()
        factory = BrokerProxyClientFactory(proxy_client, cfg=_make_cfg())
        ctx = _make_ctx({"authorization": f"Bearer {_make_jwt({'unixname': 'gstark'})}"})

        with patch("rucio_mcp.auth.broker.ProxyAuthClient") as client_cls:
            # The proxy file must still exist while the client authenticates.
            client_cls.side_effect = lambda **kwargs: Path(
                kwargs["creds"]["client_proxy"]
            ).read_text()
            client = factory.get_client(ctx)
            _, kwargs = client_cls.call_args
            assert client == "FAKE PEM"
            assert kwargs["rucio_host"] == "https://rucio.atlas.cern.ch"
            assert kwargs["auth_host"] == "https://atlas-rucio-auth.cern.ch"
            assert kwargs["auth_type"] == "x509_proxy"
            assert kwargs["account"] == "gstark"

        # The never-persist rule: the proxy file is gone after get_client.
        assert not proxy_client.created_paths[0].exists()
        assert proxy_client.seen_bearers == [ctx.request_context.request.headers[
            "authorization"
        ][7:]]
        factory.close()

    def test_account_none_without_unixname_claim(self) -> None:
        proxy_client = _FakeProxyClient()
        factory = BrokerProxyClientFactory(proxy_client, cfg=_make_cfg())
        ctx = _make_ctx({"authorization": f"Bearer {_make_jwt({'sub': 'gstark'})}"})

        with patch("rucio_mcp.auth.broker.ProxyAuthClient") as client_cls:
            factory.get_client(ctx)
            _, kwargs = client_cls.call_args
            assert kwargs["account"] is None
        factory.close()

    def test_proxy_file_deleted_when_construction_fails(self) -> None:
        proxy_client = _FakeProxyClient()
        factory = BrokerProxyClientFactory(proxy_client, cfg=_make_cfg())
        ctx = _make_ctx({"authorization": f"Bearer {_make_jwt({})}"})

        with (
            patch(
                "rucio_mcp.auth.broker.ProxyAuthClient",
                side_effect=RuntimeError("auth failed"),
            ),
            pytest.raises(RuntimeError, match="auth failed"),
        ):
            factory.get_client(ctx)

        assert not proxy_client.created_paths[0].exists()
        factory.close()

    def test_proxy_not_available_becomes_actionable_tool_error(self) -> None:
        factory = BrokerProxyClientFactory(_UnavailableProxyClient(), cfg=_make_cfg())
        ctx = _make_ctx({"authorization": f"Bearer {_make_jwt({})}"})

        with pytest.raises(ToolError, match="portal"):
            factory.get_client(ctx)
        factory.close()

    def test_redeem_failure_becomes_tool_error(self) -> None:
        factory = BrokerProxyClientFactory(_FailingProxyClient(), cfg=_make_cfg())
        ctx = _make_ctx({"authorization": f"Bearer {_make_jwt({})}"})

        with pytest.raises(ToolError, match="broker"):
            factory.get_client(ctx)
        factory.close()

    def test_missing_bearer_raises_before_redeem(self) -> None:
        proxy_client = _FakeProxyClient()
        factory = BrokerProxyClientFactory(proxy_client, cfg=_make_cfg())
        ctx = _make_ctx({})

        with pytest.raises(PermissionError):
            factory.get_client(ctx)
        assert proxy_client.seen_bearers == []
        factory.close()

    def test_close_is_safe_to_call_twice(self) -> None:
        factory = BrokerProxyClientFactory(_FakeProxyClient(), cfg=_make_cfg())
        factory.close()
        factory.close()
