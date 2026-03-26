"""Tests for replication rule tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.tools.rules import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = FastMCP("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestRucioListRules:
    async def test_returns_rules(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_did_rules.return_value = iter(
            [
                {
                    "id": "abc123",
                    "state": "OK",
                    "rse_expression": "CERN-PROD_DATADISK",
                    "account": "gstark",
                    "copies": 1,
                }
            ]
        )
        fn = registered_tools["rucio_list_rules"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "abc123" in result
        assert "CERN-PROD_DATADISK" in result

    async def test_passes_scope_and_name(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_did_rules.return_value = iter([])
        fn = registered_tools["rucio_list_rules"]
        await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        mock_rucio_client.list_did_rules.assert_called_once_with(
            "mc16_13TeV", "some.dataset"
        )

    async def test_no_rules(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_did_rules.return_value = iter([])
        fn = registered_tools["rucio_list_rules"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "No replication rules" in result

    async def test_invalid_did(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_list_rules"]
        result = await fn("nodidformat", ctx=mock_ctx)
        assert "scope:name" in result

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_did_rules.side_effect = RuntimeError("server error")
        fn = registered_tools["rucio_list_rules"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "Error" in result


class TestRucioRuleInfo:
    async def test_returns_rule_info(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_replication_rule.return_value = {
            "id": "abc123",
            "state": "REPLICATING",
            "rse_expression": "BNL-OSG2_DATADISK",
            "locks_ok_cnt": 0,
            "locks_replicating_cnt": 5,
        }
        fn = registered_tools["rucio_rule_info"]
        result = await fn("abc123", ctx=mock_ctx)
        assert "REPLICATING" in result
        assert "BNL-OSG2_DATADISK" in result

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_replication_rule.side_effect = RuntimeError("not found")
        fn = registered_tools["rucio_rule_info"]
        result = await fn("bad-uuid", ctx=mock_ctx)
        assert "Error" in result
