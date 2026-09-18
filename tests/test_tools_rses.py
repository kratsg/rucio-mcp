"""Tests for RSE query tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from mcp.server.mcpserver import MCPServer

from rucio_mcp.tools.rses import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock

    from mcp.types import CallToolResult


@pytest.fixture
def rse_tools() -> dict[str, Any]:
    mcp = MCPServer("test")
    register(mcp)
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


@pytest.fixture
def registered_tools(
    rse_tools: dict[str, Any],
) -> dict[str, Callable[..., Awaitable[CallToolResult]]]:
    return {name: tool.fn for name, tool in rse_tools.items()}


class TestRseToolsRegistration:
    def test_declares_read_only_annotations(self, rse_tools: dict[str, Any]) -> None:
        for tool in rse_tools.values():
            assert tool.annotations is not None, tool.name
            assert tool.annotations.read_only_hint is True, tool.name
            assert tool.annotations.open_world_hint is True, tool.name

    def test_publishes_output_schemas(self, rse_tools: dict[str, Any]) -> None:
        assert "rses" in rse_tools["rucio_list_rses"].output_schema["properties"]
        assert (
            "attributes"
            in rse_tools["rucio_list_rse_attributes"].output_schema["properties"]
        )
        assert "usage" in rse_tools["rucio_get_rse_usage"].output_schema["properties"]
        assert "details" in rse_tools["rucio_get_rse"].output_schema["properties"]
        assert "limits" in rse_tools["rucio_get_rse_limits"].output_schema["properties"]
        assert (
            "protocols"
            in rse_tools["rucio_get_rse_protocols"].output_schema["properties"]
        )
        assert (
            "distances" in rse_tools["rucio_get_distance"].output_schema["properties"]
        )
        assert (
            "limits"
            in rse_tools["rucio_list_transfer_limits"].output_schema["properties"]
        )


class TestRucioListRses:
    async def test_returns_rse_names(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_rses.return_value = iter(
            [{"rse": "CERN-PROD_DATADISK"}, {"rse": "BNL-OSG2_DATADISK"}]
        )
        fn = registered_tools["rucio_list_rses"]
        result = await fn(ctx=mock_ctx)
        assert "CERN-PROD_DATADISK" in tool_text(result)
        assert "BNL-OSG2_DATADISK" in tool_text(result)

    async def test_returns_markdown_bullet_list(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_rses.return_value = iter([{"rse": "CERN-PROD_DATADISK"}])
        fn = registered_tools["rucio_list_rses"]
        result = await fn(ctx=mock_ctx)
        assert "- `CERN-PROD_DATADISK`" in tool_text(result)

    async def test_no_rses(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_rses.return_value = iter([])
        fn = registered_tools["rucio_list_rses"]
        result = await fn(ctx=mock_ctx)
        assert "No RSEs" in tool_text(result)

    async def test_rse_expression_filter(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_rses.return_value = iter([])
        fn = registered_tools["rucio_list_rses"]
        await fn(rse_expression="tier=1", ctx=mock_ctx)
        mock_rucio_client.list_rses.assert_called_once_with(rse_expression="tier=1")

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_rses.side_effect = RuntimeError("connection failed")
        fn = registered_tools["rucio_list_rses"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")


class TestRucioListRseAttributes:
    async def test_returns_attributes(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_rse_attributes.return_value = {
            "tier": 1,
            "type": "DATADISK",
            "cloud": "US",
        }
        fn = registered_tools["rucio_list_rse_attributes"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert "tier" in tool_text(result)
        assert "DATADISK" in tool_text(result)

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_rse_attributes.side_effect = RuntimeError("not found")
        fn = registered_tools["rucio_list_rse_attributes"]
        result = await fn("NONEXISTENT", ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")

    async def test_includes_hints(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_rse_attributes.return_value = {"tier": 1}
        fn = registered_tools["rucio_list_rse_attributes"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert "rucio_get_rse_usage" in tool_text(result)


class TestRucioGetRseUsage:
    async def test_returns_markdown_table(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_rse_usage.return_value = iter(
            [
                {"source": "rucio", "used": 1000, "free": 500, "total": 1500},
                {"source": "storage", "used": 1200, "free": 300, "total": 1500},
            ]
        )
        fn = registered_tools["rucio_get_rse_usage"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert "| source | used | free | total |" in tool_text(result)
        assert "| rucio | 1000 B | 500 B | 1.46 KB |" in tool_text(result)

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_rse_usage.side_effect = RuntimeError("not found")
        fn = registered_tools["rucio_get_rse_usage"]
        result = await fn("NONEXISTENT", ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")

    async def test_includes_hints(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_rse_usage.return_value = iter(
            [{"source": "rucio", "used": 1000, "free": 500, "total": 1500}]
        )
        fn = registered_tools["rucio_get_rse_usage"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert "rucio_list_rse_attributes" in tool_text(result)


class TestRucioGetRse:
    async def test_returns_rse_details(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_rse.return_value = {
            "rse": "CERN-PROD_DATADISK",
            "rse_type": "DISK",
            "volatile": False,
            "deterministic": True,
            "staging_area": False,
        }
        fn = registered_tools["rucio_get_rse"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert "CERN-PROD_DATADISK" in tool_text(result)
        assert "DISK" in tool_text(result)

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_rse.side_effect = RuntimeError("not found")
        fn = registered_tools["rucio_get_rse"]
        result = await fn("NONEXISTENT", ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")

    async def test_includes_hints(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_rse.return_value = {"rse": "CERN-PROD_DATADISK"}
        fn = registered_tools["rucio_get_rse"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert "rucio_list_rse_attributes" in tool_text(result)


class TestRucioGetRseLimits:
    async def test_returns_limits(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        # RSEClient.get_rse_limits returns a single {name: value} dict, not an
        # iterator of {"name": ..., "value": ...} entries.
        mock_rucio_client.get_rse_limits.return_value = {
            "MaxBeingDeletedFiles": 100,
            "MinFreeSpace": 2000,
        }
        fn = registered_tools["rucio_get_rse_limits"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert "MaxBeingDeletedFiles" in tool_text(result)
        assert "100" in tool_text(result)  # the value must survive, not just the key

    async def test_empty_limits(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_rse_limits.return_value = {}
        fn = registered_tools["rucio_get_rse_limits"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert "No limits" in tool_text(result)

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_rse_limits.side_effect = RuntimeError("not found")
        fn = registered_tools["rucio_get_rse_limits"]
        result = await fn("NONEXISTENT", ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")


class TestRucioGetRseProtocols:
    async def test_returns_protocols(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_protocols.return_value = {
            "protocols": [
                {"scheme": "root", "hostname": "eosatlas.cern.ch", "port": 1094}
            ]
        }
        fn = registered_tools["rucio_get_rse_protocols"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert "root" in tool_text(result)

    async def test_returns_protocols_list(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        # rucio 39.x get_protocols returns a JSON list of protocol dicts.
        mock_rucio_client.get_protocols.return_value = [
            {"scheme": "root", "hostname": "eosatlas.cern.ch", "port": 1094},
            {"scheme": "davs", "hostname": "eosatlas.cern.ch", "port": 443},
        ]
        fn = registered_tools["rucio_get_rse_protocols"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert "root" in tool_text(result)
        assert "davs" in tool_text(result)
        assert "eosatlas.cern.ch" in tool_text(result)
        # not a raw Python repr of the list
        assert "[{" not in tool_text(result)

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_protocols.side_effect = RuntimeError("not found")
        fn = registered_tools["rucio_get_rse_protocols"]
        result = await fn("NONEXISTENT", ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")


class TestRucioGetDistance:
    async def test_returns_distance(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_distance.return_value = [
            {"src_rse_id": "aaa", "dest_rse_id": "bbb", "ranking": 10}
        ]
        fn = registered_tools["rucio_get_distance"]
        result = await fn("CERN-PROD_DATADISK", "BNL-OSG2_DATADISK", ctx=mock_ctx)
        assert "10" in tool_text(result)

    async def test_no_distance(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_distance.return_value = []
        fn = registered_tools["rucio_get_distance"]
        result = await fn("CERN-PROD_DATADISK", "BNL-OSG2_DATADISK", ctx=mock_ctx)
        assert "No distance" in tool_text(result)

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_distance.side_effect = RuntimeError("not found")
        fn = registered_tools["rucio_get_distance"]
        result = await fn("SRC", "DST", ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")


class TestRucioListTransferLimits:
    async def test_returns_limits(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_transfer_limits.return_value = iter(
            [{"rse_id": "abc", "activity": "User", "max_transfers": 100}]
        )
        fn = registered_tools["rucio_list_transfer_limits"]
        result = await fn(ctx=mock_ctx)
        assert "User" in tool_text(result)

    async def test_empty_limits(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_transfer_limits.return_value = iter([])
        fn = registered_tools["rucio_list_transfer_limits"]
        result = await fn(ctx=mock_ctx)
        assert "No transfer limits" in tool_text(result)

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_transfer_limits.side_effect = RuntimeError(
            "server error"
        )
        fn = registered_tools["rucio_list_transfer_limits"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
