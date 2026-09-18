"""Tests for ping and whoami tools."""

from __future__ import annotations

import base64
import json
import time
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import MCPServer

from rucio_mcp.tools.ping import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mcp.types import CallToolResult


def _make_jwt(payload: dict[str, object]) -> str:
    """Build a minimal unsigned JWT from a payload dict."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}."


@pytest.fixture
def stdio_tools() -> dict[str, Any]:
    mcp = MCPServer("test")
    register(mcp, transport="stdio")
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


@pytest.fixture
def http_tools() -> dict[str, Any]:
    mcp = MCPServer("test")
    register(mcp, transport="http")
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


@pytest.fixture
def registered_tools(
    stdio_tools: dict[str, Any],
) -> dict[str, Callable[..., Awaitable[CallToolResult]]]:
    """Return a dict of tool_name -> callable for ping tools (stdio mode)."""
    return {name: tool.fn for name, tool in stdio_tools.items()}


@pytest.fixture
def registered_tools_http(
    http_tools: dict[str, Any],
) -> dict[str, Callable[..., Awaitable[CallToolResult]]]:
    """Return a dict of tool_name -> callable for ping tools (HTTP mode)."""
    return {name: tool.fn for name, tool in http_tools.items()}


def _mock_http_ctx(authorization: str = "") -> MagicMock:
    """Build a mock Context whose request carries the given Authorization header."""
    ctx: MagicMock = MagicMock()
    ctx.request_context.request.headers.get = lambda key, default="": (
        authorization if key == "authorization" else default
    )
    return ctx


class TestPingToolsRegistration:
    def test_declares_read_only_annotations(self, stdio_tools: dict[str, Any]) -> None:
        for tool in stdio_tools.values():
            assert tool.annotations is not None, tool.name
            assert tool.annotations.read_only_hint is True, tool.name
            assert tool.annotations.open_world_hint is True, tool.name

    def test_publishes_output_schemas(self, stdio_tools: dict[str, Any]) -> None:
        assert "version" in stdio_tools["rucio_ping"].output_schema["properties"]
        assert "account" in stdio_tools["rucio_whoami"].output_schema["properties"]

    def test_token_info_declares_read_only_annotations(
        self, http_tools: dict[str, Any]
    ) -> None:
        tool = http_tools["rucio_token_info"]
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is True
        assert "is_jwt" in tool.output_schema["properties"]


class TestRucioPing:
    async def test_returns_version(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.ping.return_value = {"version": "35.6.0"}
        fn = registered_tools["rucio_ping"]
        result = await fn(ctx=mock_ctx)
        assert "35.6.0" in tool_text(result)
        assert result.structured_content == {"version": "35.6.0"}

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.ping.side_effect = ConnectionError("unreachable")
        fn = registered_tools["rucio_ping"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True


class TestRucioWhoami:
    async def test_returns_account_info(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.whoami.return_value = {
            "account": "gstark",
            "type": "USER",
            "email": "kratsg@gmail.com",
            "status": "ACTIVE",
        }
        fn = registered_tools["rucio_whoami"]
        result = await fn(ctx=mock_ctx)
        output = tool_text(result)
        assert "gstark" in output
        assert "ACTIVE" in output
        assert result.structured_content is not None
        assert result.structured_content["account"] == "gstark"
        assert result.structured_content["status"] == "ACTIVE"

    async def test_returns_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.whoami.side_effect = RuntimeError("auth failed")
        fn = registered_tools["rucio_whoami"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True


class TestRucioTokenInfo:
    def test_not_registered_in_stdio_mode(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
    ) -> None:
        assert "rucio_token_info" not in registered_tools

    def test_registered_in_http_mode(
        self,
        registered_tools_http: dict[str, Callable[..., Awaitable[CallToolResult]]],
    ) -> None:
        assert "rucio_token_info" in registered_tools_http

    async def test_returns_error_when_no_bearer(
        self,
        registered_tools_http: dict[str, Callable[..., Awaitable[CallToolResult]]],
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools_http["rucio_token_info"]
        result = await fn(ctx=_mock_http_ctx(""))
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True

    async def test_returns_opaque_message_for_non_jwt(
        self,
        registered_tools_http: dict[str, Callable[..., Awaitable[CallToolResult]]],
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools_http["rucio_token_info"]
        result = await fn(ctx=_mock_http_ctx("Bearer opaque-token-without-dots"))
        assert "opaque" in tool_text(result).lower()
        assert result.is_error is not True
        assert result.structured_content is not None
        assert result.structured_content["is_jwt"] is False

    async def test_decodes_valid_jwt_with_future_expiry(
        self,
        registered_tools_http: dict[str, Callable[..., Awaitable[CallToolResult]]],
        tool_text: Callable[[CallToolResult], str],
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
        output = tool_text(result)
        assert "expires_at" in output
        assert "EXPIRED" not in output
        assert "gstark" in output
        assert "atlas-auth.cern.ch" in output
        assert result.structured_content is not None
        assert result.structured_content["subject"] == "gstark"
        assert result.structured_content["expired"] is False

    async def test_shows_expired_label_for_past_expiry(
        self,
        registered_tools_http: dict[str, Callable[..., Awaitable[CallToolResult]]],
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        past_exp = int(time.time()) - 300
        token = _make_jwt({"exp": past_exp, "sub": "gstark"})
        fn = registered_tools_http["rucio_token_info"]
        result = await fn(ctx=_mock_http_ctx(f"Bearer {token}"))
        assert "EXPIRED" in tool_text(result)
        assert result.structured_content is not None
        assert result.structured_content["expired"] is True

    async def test_jwt_with_no_standard_claims(
        self,
        registered_tools_http: dict[str, Callable[..., Awaitable[CallToolResult]]],
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        token = _make_jwt({"custom": "value"})
        fn = registered_tools_http["rucio_token_info"]
        result = await fn(ctx=_mock_http_ctx(f"Bearer {token}"))
        assert "no standard claims" in tool_text(result).lower()
        assert result.is_error is not True
        assert result.structured_content is not None
        assert result.structured_content["is_jwt"] is True
