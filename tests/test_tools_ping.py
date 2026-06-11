"""Tests for ping and whoami tools."""

from __future__ import annotations

import base64
import json
import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.tools.ping import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def _make_jwt(payload: dict) -> str:
    """Build a minimal unsigned JWT from a payload dict."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}."


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    """Return a dict of tool_name -> callable for ping tools (stdio mode)."""
    mcp = FastMCP("test")
    register(mcp, transport="stdio")
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


@pytest.fixture
def registered_tools_http() -> dict[str, Callable[..., Awaitable[str]]]:
    """Return a dict of tool_name -> callable for ping tools (HTTP mode)."""
    mcp = FastMCP("test")
    register(mcp, transport="http")
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


def _mock_http_ctx(authorization: str = "") -> MagicMock:
    """Build a mock Context whose request carries the given Authorization header."""
    ctx: MagicMock = MagicMock()
    ctx.request_context.request.headers.get = (
        lambda key, default="": authorization if key == "authorization" else default
    )
    return ctx


class TestRucioPing:
    async def test_returns_version(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.ping.return_value = {"version": "35.6.0"}
        fn = registered_tools["rucio_ping"]
        result = await fn(ctx=mock_ctx)
        assert "35.6.0" in result

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.ping.side_effect = ConnectionError("unreachable")
        fn = registered_tools["rucio_ping"]
        result = await fn(ctx=mock_ctx)
        assert result.startswith("Error:")


class TestRucioWhoami:
    async def test_returns_account_info(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.whoami.return_value = {
            "account": "gstark",
            "type": "USER",
            "email": "kratsg@gmail.com",
            "status": "ACTIVE",
        }
        fn = registered_tools["rucio_whoami"]
        result = await fn(ctx=mock_ctx)
        assert "gstark" in result
        assert "ACTIVE" in result

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.whoami.side_effect = RuntimeError("auth failed")
        fn = registered_tools["rucio_whoami"]
        result = await fn(ctx=mock_ctx)
        assert result.startswith("Error:")


class TestRucioTokenInfo:
    def test_not_registered_in_stdio_mode(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
    ) -> None:
        assert "rucio_token_info" not in registered_tools

    def test_registered_in_http_mode(
        self,
        registered_tools_http: dict[str, Callable[..., Awaitable[str]]],
    ) -> None:
        assert "rucio_token_info" in registered_tools_http

    async def test_returns_error_when_no_bearer(
        self,
        registered_tools_http: dict[str, Callable[..., Awaitable[str]]],
    ) -> None:
        fn = registered_tools_http["rucio_token_info"]
        result = await fn(ctx=_mock_http_ctx(""))
        assert result.startswith("Error:")

    async def test_returns_opaque_message_for_non_jwt(
        self,
        registered_tools_http: dict[str, Callable[..., Awaitable[str]]],
    ) -> None:
        fn = registered_tools_http["rucio_token_info"]
        result = await fn(ctx=_mock_http_ctx("Bearer opaque-token-without-dots"))
        assert "opaque" in result.lower()

    async def test_decodes_valid_jwt_with_future_expiry(
        self,
        registered_tools_http: dict[str, Callable[..., Awaitable[str]]],
    ) -> None:
        future_exp = int(time.time()) + 3600
        token = _make_jwt(
            {
                "exp": future_exp,
                "iat": int(time.time()) - 60,
                "sub": "gstark",
                "iss": "https://atlas-auth.cern.ch",
                "aud": "rucio",
            }
        )
        fn = registered_tools_http["rucio_token_info"]
        result = await fn(ctx=_mock_http_ctx(f"Bearer {token}"))
        assert "expires_at" in result
        assert "EXPIRED" not in result
        assert "gstark" in result
        assert "atlas-auth.cern.ch" in result

    async def test_shows_expired_label_for_past_expiry(
        self,
        registered_tools_http: dict[str, Callable[..., Awaitable[str]]],
    ) -> None:
        past_exp = int(time.time()) - 300
        token = _make_jwt({"exp": past_exp, "sub": "gstark"})
        fn = registered_tools_http["rucio_token_info"]
        result = await fn(ctx=_mock_http_ctx(f"Bearer {token}"))
        assert "EXPIRED" in result

    async def test_jwt_with_no_standard_claims(
        self,
        registered_tools_http: dict[str, Callable[..., Awaitable[str]]],
    ) -> None:
        token = _make_jwt({"custom": "value"})
        fn = registered_tools_http["rucio_token_info"]
        result = await fn(ctx=_mock_http_ctx(f"Bearer {token}"))
        assert "no standard claims" in result.lower()
