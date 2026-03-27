"""Tests for RSE query tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.tools.rses import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = FastMCP("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestRucioListRses:
    async def test_returns_rse_names(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_rses.return_value = iter(
            [{"rse": "CERN-PROD_DATADISK"}, {"rse": "BNL-OSG2_DATADISK"}]
        )
        fn = registered_tools["rucio_list_rses"]
        result = await fn(ctx=mock_ctx)
        assert "CERN-PROD_DATADISK" in result
        assert "BNL-OSG2_DATADISK" in result

    async def test_returns_markdown_bullet_list(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_rses.return_value = iter([{"rse": "CERN-PROD_DATADISK"}])
        fn = registered_tools["rucio_list_rses"]
        result = await fn(ctx=mock_ctx)
        assert "- `CERN-PROD_DATADISK`" in result

    async def test_no_rses(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_rses.return_value = iter([])
        fn = registered_tools["rucio_list_rses"]
        result = await fn(ctx=mock_ctx)
        assert "No RSEs" in result

    async def test_rse_expression_filter(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_rses.return_value = iter([])
        fn = registered_tools["rucio_list_rses"]
        await fn(rse_expression="tier=1", ctx=mock_ctx)
        mock_rucio_client.list_rses.assert_called_once_with(rse_expression="tier=1")

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_rses.side_effect = RuntimeError("connection failed")
        fn = registered_tools["rucio_list_rses"]
        result = await fn(ctx=mock_ctx)
        assert result.startswith("Error:")


class TestRucioListRseAttributes:
    async def test_returns_attributes(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_rse_attributes.return_value = {
            "tier": 1,
            "type": "DATADISK",
            "cloud": "US",
        }
        fn = registered_tools["rucio_list_rse_attributes"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert "tier" in result
        assert "DATADISK" in result

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_rse_attributes.side_effect = RuntimeError("not found")
        fn = registered_tools["rucio_list_rse_attributes"]
        result = await fn("NONEXISTENT", ctx=mock_ctx)
        assert result.startswith("Error:")


class TestRucioListRseUsage:
    async def test_returns_markdown_table(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_rse_usage.return_value = iter(
            [
                {"source": "rucio", "used": 1000, "free": 500, "total": 1500},
                {"source": "storage", "used": 1200, "free": 300, "total": 1500},
            ]
        )
        fn = registered_tools["rucio_list_rse_usage"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert "| source | used | free | total |" in result
        assert "| rucio | 1000 B | 500 B | 1.46 KB |" in result

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_rse_usage.side_effect = RuntimeError("not found")
        fn = registered_tools["rucio_list_rse_usage"]
        result = await fn("NONEXISTENT", ctx=mock_ctx)
        assert result.startswith("Error:")
