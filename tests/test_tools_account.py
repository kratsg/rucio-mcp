"""Tests for account usage and limits tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from mcp.server.mcpserver import MCPServer

from rucio_mcp.tools.account import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock

    from mcp.types import CallToolResult


@pytest.fixture
def account_tools() -> dict[str, Any]:
    mcp = MCPServer("test")
    register(mcp)
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


@pytest.fixture
def registered_tools(
    account_tools: dict[str, Any],
) -> dict[str, Callable[..., Awaitable[CallToolResult]]]:
    return {name: tool.fn for name, tool in account_tools.items()}


class TestAccountToolsRegistration:
    def test_declares_read_only_annotations(
        self, account_tools: dict[str, Any]
    ) -> None:
        for tool in account_tools.values():
            assert tool.annotations is not None, tool.name
            assert tool.annotations.read_only_hint is True, tool.name
            assert tool.annotations.open_world_hint is True, tool.name

    def test_publishes_output_schemas(self, account_tools: dict[str, Any]) -> None:
        assert (
            "usage"
            in account_tools["rucio_get_local_account_usage"].output_schema[
                "properties"
            ]
        )
        assert (
            "limits"
            in account_tools["rucio_get_local_account_limits"].output_schema[
                "properties"
            ]
        )
        assert (
            "accounts"
            in account_tools["rucio_list_accounts"].output_schema["properties"]
        )
        assert (
            "account" in account_tools["rucio_get_account"].output_schema["properties"]
        )
        assert (
            "rules"
            in account_tools["rucio_list_account_rules"].output_schema["properties"]
        )


class TestRucioGetLocalAccountUsage:
    async def test_returns_usage(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
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
        fn = registered_tools["rucio_get_local_account_usage"]
        result = await fn(ctx=mock_ctx)
        assert "CERN-PROD_DATADISK" in tool_text(result)
        assert "976.56 KB" in tool_text(result)

    async def test_uses_provided_account(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_local_account_usage.return_value = iter([])
        fn = registered_tools["rucio_get_local_account_usage"]
        await fn(account="otheruser", ctx=mock_ctx)
        mock_rucio_client.get_local_account_usage.assert_called_once_with(
            "otheruser", rse=None
        )

    async def test_uses_client_account_when_empty(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_local_account_usage.return_value = iter([])
        fn = registered_tools["rucio_get_local_account_usage"]
        await fn(ctx=mock_ctx)
        mock_rucio_client.get_local_account_usage.assert_called_once_with(
            "gstark", rse=None
        )

    async def test_rse_filter(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_local_account_usage.return_value = iter([])
        fn = registered_tools["rucio_get_local_account_usage"]
        await fn(rse="CERN-PROD_DATADISK", ctx=mock_ctx)
        mock_rucio_client.get_local_account_usage.assert_called_once_with(
            "gstark", rse="CERN-PROD_DATADISK"
        )

    async def test_no_usage(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_local_account_usage.return_value = iter([])
        fn = registered_tools["rucio_get_local_account_usage"]
        result = await fn(ctx=mock_ctx)
        assert "No account usage" in tool_text(result)

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_local_account_usage.side_effect = RuntimeError("denied")
        fn = registered_tools["rucio_get_local_account_usage"]
        result = await fn(ctx=mock_ctx)
        assert "Error" in tool_text(result)
        assert result.is_error is True


class TestRucioGetLocalAccountLimits:
    async def test_returns_limits(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_local_account_limits.return_value = {
            "CERN-PROD_DATADISK": 10000000000,
            "BNL-OSG2_DATADISK": 5000000000,
        }
        fn = registered_tools["rucio_get_local_account_limits"]
        result = await fn(ctx=mock_ctx)
        assert "CERN-PROD_DATADISK" in tool_text(result)
        assert "9.31 GB" in tool_text(result)

    async def test_uses_client_account_when_empty(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_local_account_limits.return_value = {}
        fn = registered_tools["rucio_get_local_account_limits"]
        await fn(ctx=mock_ctx)
        mock_rucio_client.get_local_account_limits.assert_called_once_with("gstark")

    async def test_rse_expression_uses_get_account_limits(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_account_limits.return_value = {
            "BNL-OSG2_DATADISK": 5000000000,
        }
        fn = registered_tools["rucio_get_local_account_limits"]
        result = await fn(rse_expression="BNL-OSG2_DATADISK", ctx=mock_ctx)
        mock_rucio_client.get_account_limits.assert_called_once_with(
            "gstark", rse_expression="BNL-OSG2_DATADISK", locality="local"
        )
        assert "BNL-OSG2_DATADISK" in tool_text(result)

    async def test_none_limit_rendered_as_none(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_account_limits.return_value = {
            "BNL-OSG2_DATADISK": None,
        }
        fn = registered_tools["rucio_get_local_account_limits"]
        result = await fn(rse_expression="BNL-OSG2_DATADISK", ctx=mock_ctx)
        assert "BNL-OSG2_DATADISK" in tool_text(result)
        assert "none" in tool_text(result)

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_local_account_limits.side_effect = RuntimeError("denied")
        fn = registered_tools["rucio_get_local_account_limits"]
        result = await fn(ctx=mock_ctx)
        assert "Error" in tool_text(result)
        assert result.is_error is True


class TestRucioListAccounts:
    async def test_returns_accounts(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_accounts.return_value = iter(
            [
                {"account": "gstark", "account_type": "USER", "status": "ACTIVE"},
                {"account": "atlas", "account_type": "GROUP", "status": "ACTIVE"},
            ]
        )
        fn = registered_tools["rucio_list_accounts"]
        result = await fn(ctx=mock_ctx)
        assert "gstark" in tool_text(result)
        assert "atlas" in tool_text(result)

    async def test_account_type_filter(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_accounts.return_value = iter([])
        fn = registered_tools["rucio_list_accounts"]
        await fn(account_type="USER", ctx=mock_ctx)
        mock_rucio_client.list_accounts.assert_called_once_with(
            account_type="USER", identity=None
        )

    async def test_no_accounts(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_accounts.return_value = iter([])
        fn = registered_tools["rucio_list_accounts"]
        result = await fn(ctx=mock_ctx)
        assert "No accounts" in tool_text(result)

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_accounts.side_effect = RuntimeError("server error")
        fn = registered_tools["rucio_list_accounts"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True


class TestRucioGetAccount:
    async def test_returns_account_info(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_account.return_value = {
            "account": "gstark",
            "account_type": "USER",
            "status": "ACTIVE",
            "email": "g@example.com",
        }
        fn = registered_tools["rucio_get_account"]
        result = await fn(ctx=mock_ctx)
        assert "gstark" in tool_text(result)
        assert "USER" in tool_text(result)

    async def test_uses_provided_account(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_account.return_value = {"account": "otheruser"}
        fn = registered_tools["rucio_get_account"]
        await fn(account="otheruser", ctx=mock_ctx)
        mock_rucio_client.get_account.assert_called_once_with("otheruser")

    async def test_uses_client_account_when_empty(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_account.return_value = {"account": "gstark"}
        fn = registered_tools["rucio_get_account"]
        await fn(ctx=mock_ctx)
        mock_rucio_client.get_account.assert_called_once_with("gstark")

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.get_account.side_effect = RuntimeError("not found")
        fn = registered_tools["rucio_get_account"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True


class TestRucioListAccountRules:
    async def test_returns_rules(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.list_replication_rules.return_value = iter(
            [
                {
                    "id": "rule-001",
                    "state": "OK",
                    "rse_expression": "CERN-PROD_DATADISK",
                    "account": "gstark",
                }
            ]
        )
        fn = registered_tools["rucio_list_account_rules"]
        result = await fn(ctx=mock_ctx)
        assert "rule-001" in tool_text(result)

    async def test_uses_client_account_when_empty(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.list_replication_rules.return_value = iter([])
        fn = registered_tools["rucio_list_account_rules"]
        await fn(ctx=mock_ctx)
        mock_rucio_client.list_replication_rules.assert_called_once_with(
            filters={"account": "gstark"}
        )

    async def test_no_rules(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.list_replication_rules.return_value = iter([])
        fn = registered_tools["rucio_list_account_rules"]
        result = await fn(ctx=mock_ctx)
        assert "No replication rules" in tool_text(result)

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.list_replication_rules.side_effect = RuntimeError("denied")
        fn = registered_tools["rucio_list_account_rules"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
