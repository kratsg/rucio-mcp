"""Tests for account usage and limits tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.tools.account import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = FastMCP("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestRucioListAccountUsage:
    async def test_returns_usage(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_local_account_usage.return_value = iter(
            [
                {
                    "rse": "CERN-PROD_DATADISK",
                    "bytes": 1000000,
                    "bytes_limit": 10000000,
                    "files": 42,
                }
            ]
        )
        fn = registered_tools["rucio_list_account_usage"]
        result = await fn(ctx=mock_ctx)
        assert "CERN-PROD_DATADISK" in result
        assert "1000000" in result

    async def test_uses_provided_account(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_local_account_usage.return_value = iter([])
        fn = registered_tools["rucio_list_account_usage"]
        await fn(account="otheruser", ctx=mock_ctx)
        mock_rucio_client.get_local_account_usage.assert_called_once_with(
            "otheruser", rse=None
        )

    async def test_uses_client_account_when_empty(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_local_account_usage.return_value = iter([])
        fn = registered_tools["rucio_list_account_usage"]
        await fn(ctx=mock_ctx)
        mock_rucio_client.get_local_account_usage.assert_called_once_with(
            "gstark", rse=None
        )

    async def test_rse_filter(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_local_account_usage.return_value = iter([])
        fn = registered_tools["rucio_list_account_usage"]
        await fn(rse="CERN-PROD_DATADISK", ctx=mock_ctx)
        mock_rucio_client.get_local_account_usage.assert_called_once_with(
            "gstark", rse="CERN-PROD_DATADISK"
        )

    async def test_no_usage(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_local_account_usage.return_value = iter([])
        fn = registered_tools["rucio_list_account_usage"]
        result = await fn(ctx=mock_ctx)
        assert "No account usage" in result

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_local_account_usage.side_effect = RuntimeError("denied")
        fn = registered_tools["rucio_list_account_usage"]
        result = await fn(ctx=mock_ctx)
        assert "Error" in result


class TestRucioListAccountLimits:
    async def test_returns_limits(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_account_limits.return_value = {
            "CERN-PROD_DATADISK": 10000000000,
            "BNL-OSG2_DATADISK": 5000000000,
        }
        fn = registered_tools["rucio_list_account_limits"]
        result = await fn(ctx=mock_ctx)
        assert "CERN-PROD_DATADISK" in result
        assert "10000000000" in result

    async def test_uses_client_account_when_empty(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_account_limits.return_value = {}
        fn = registered_tools["rucio_list_account_limits"]
        await fn(ctx=mock_ctx)
        mock_rucio_client.get_account_limits.assert_called_once_with(
            "gstark", rse_expression=None, locality="local"
        )

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_account_limits.side_effect = RuntimeError("denied")
        fn = registered_tools["rucio_list_account_limits"]
        result = await fn(ctx=mock_ctx)
        assert "Error" in result
