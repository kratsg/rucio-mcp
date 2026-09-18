"""Tests for subscription tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from mcp.server.mcpserver import MCPServer

from rucio_mcp.tools.subscriptions import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock

    from mcp.types import CallToolResult


@pytest.fixture
def subscription_tools() -> dict[str, Any]:
    mcp = MCPServer("test")
    register(mcp)
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


@pytest.fixture
def registered_tools(
    subscription_tools: dict[str, Any],
) -> dict[str, Callable[..., Awaitable[CallToolResult]]]:
    return {name: tool.fn for name, tool in subscription_tools.items()}


class TestSubscriptionToolsRegistration:
    def test_declares_read_only_annotations(
        self, subscription_tools: dict[str, Any]
    ) -> None:
        for tool in subscription_tools.values():
            assert tool.annotations is not None, tool.name
            assert tool.annotations.read_only_hint is True, tool.name
            assert tool.annotations.open_world_hint is True, tool.name

    def test_publishes_output_schemas(self, subscription_tools: dict[str, Any]) -> None:
        assert (
            "subscriptions"
            in subscription_tools["rucio_list_subscriptions"].output_schema[
                "properties"
            ]
        )
        assert (
            "rules"
            in subscription_tools["rucio_list_subscription_rules"].output_schema[
                "properties"
            ]
        )


class TestRucioListSubscriptions:
    async def test_returns_subscriptions(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_subscriptions.return_value = iter(
            [
                {
                    "name": "my-sub",
                    "account": "gstark",
                    "state": "ACTIVE",
                    "filter": "{}",
                }
            ]
        )
        fn = registered_tools["rucio_list_subscriptions"]
        result = await fn(ctx=mock_ctx)
        output = tool_text(result)
        assert "my-sub" in output
        assert "ACTIVE" in output
        assert result.structured_content is not None
        assert result.structured_content["subscriptions"][0]["name"] == "my-sub"

    async def test_filters_by_name(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_subscriptions.return_value = iter([])
        fn = registered_tools["rucio_list_subscriptions"]
        await fn(name="my-sub", ctx=mock_ctx)
        mock_rucio_client.list_subscriptions.assert_called_once_with(
            name="my-sub", account=None
        )

    async def test_filters_by_account(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_subscriptions.return_value = iter([])
        fn = registered_tools["rucio_list_subscriptions"]
        await fn(account="gstark", ctx=mock_ctx)
        mock_rucio_client.list_subscriptions.assert_called_once_with(
            name=None, account="gstark"
        )

    async def test_no_subscriptions(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_subscriptions.return_value = iter([])
        fn = registered_tools["rucio_list_subscriptions"]
        result = await fn(ctx=mock_ctx)
        assert "No subscriptions" in tool_text(result)

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_subscriptions.side_effect = RuntimeError("server error")
        fn = registered_tools["rucio_list_subscriptions"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True


class TestRucioListSubscriptionRules:
    async def test_returns_rules(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_subscription_rules.return_value = iter(
            [
                {
                    "id": "rule-001",
                    "state": "OK",
                    "rse_expression": "CERN-PROD_DATADISK",
                    "account": "gstark",
                }
            ]
        )
        fn = registered_tools["rucio_list_subscription_rules"]
        result = await fn("gstark", "my-sub", ctx=mock_ctx)
        assert "rule-001" in tool_text(result)
        assert result.structured_content is not None
        assert result.structured_content["rules"][0]["id"] == "rule-001"

    async def test_passes_correct_args(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_subscription_rules.return_value = iter([])
        fn = registered_tools["rucio_list_subscription_rules"]
        await fn("gstark", "my-sub", ctx=mock_ctx)
        mock_rucio_client.list_subscription_rules.assert_called_once_with(
            "gstark", "my-sub"
        )

    async def test_no_rules(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_subscription_rules.return_value = iter([])
        fn = registered_tools["rucio_list_subscription_rules"]
        result = await fn("gstark", "my-sub", ctx=mock_ctx)
        assert "No rules" in tool_text(result)

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_subscription_rules.side_effect = RuntimeError("error")
        fn = registered_tools["rucio_list_subscription_rules"]
        result = await fn("gstark", "my-sub", ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True
