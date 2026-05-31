"""Tests for subscription tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.tools.subscriptions import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = FastMCP("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestRucioListSubscriptions:
    async def test_returns_subscriptions(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
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
        assert "my-sub" in result
        assert "ACTIVE" in result

    async def test_filters_by_name(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
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
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
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
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_subscriptions.return_value = iter([])
        fn = registered_tools["rucio_list_subscriptions"]
        result = await fn(ctx=mock_ctx)
        assert "No subscriptions" in result

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_subscriptions.side_effect = RuntimeError("server error")
        fn = registered_tools["rucio_list_subscriptions"]
        result = await fn(ctx=mock_ctx)
        assert result.startswith("Error:")


class TestRucioListSubscriptionRules:
    async def test_returns_rules(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
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
        assert "rule-001" in result

    async def test_passes_correct_args(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
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
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_subscription_rules.return_value = iter([])
        fn = registered_tools["rucio_list_subscription_rules"]
        result = await fn("gstark", "my-sub", ctx=mock_ctx)
        assert "No rules" in result

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_subscription_rules.side_effect = RuntimeError("error")
        fn = registered_tools["rucio_list_subscription_rules"]
        result = await fn("gstark", "my-sub", ctx=mock_ctx)
        assert result.startswith("Error:")
