"""Tests for ping and whoami tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.tools.ping import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    """Return a dict of tool_name -> callable for ping tools."""
    mcp = FastMCP("test")
    register(mcp)
    # Extract the registered tools by name for direct invocation
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


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
