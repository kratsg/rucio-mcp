"""Tests for transfer request tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from mcp.server.mcpserver import MCPServer

from rucio_mcp.tools.rucio_requests import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock

    from mcp.types import CallToolResult


@pytest.fixture
def request_tools() -> dict[str, Any]:
    mcp = MCPServer("test")
    register(mcp)
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


@pytest.fixture
def registered_tools(
    request_tools: dict[str, Any],
) -> dict[str, Callable[..., Awaitable[CallToolResult]]]:
    return {name: tool.fn for name, tool in request_tools.items()}


class TestRequestToolsRegistration:
    def test_declares_read_only_annotations(self, request_tools: dict[str, Any]) -> None:
        for tool in request_tools.values():
            assert tool.annotations is not None, tool.name
            assert tool.annotations.read_only_hint is True, tool.name
            assert tool.annotations.open_world_hint is True, tool.name

    def test_publishes_output_schemas(self, request_tools: dict[str, Any]) -> None:
        assert "requests" in request_tools["rucio_list_requests"].output_schema["properties"]
        assert (
            "requests"
            in request_tools["rucio_list_requests_history"].output_schema["properties"]
        )


class TestRucioListRequests:
    async def test_returns_requests(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_requests.return_value = iter(
            [
                {
                    "id": "req-001",
                    "state": "SUBMITTED",
                    "src_rse_id": "aaa",
                    "dst_rse_id": "bbb",
                }
            ]
        )
        fn = registered_tools["rucio_list_requests"]
        result = await fn(
            "CERN-PROD_DATADISK",
            "BNL-OSG2_DATADISK",
            "SUBMITTED",
            ctx=mock_ctx,
        )
        output = tool_text(result)
        assert "req-001" in output
        assert "SUBMITTED" in output
        assert result.structured_content is not None
        assert result.structured_content["requests"][0]["id"] == "req-001"

    async def test_passes_correct_args(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_requests.return_value = iter([])
        fn = registered_tools["rucio_list_requests"]
        await fn("SRC", "DST", "SUBMITTED,WAITING", ctx=mock_ctx)
        # Full names are mapped to single-letter codes and joined as a plain
        # string (rucio interpolates the value straight into the query string).
        mock_rucio_client.list_requests.assert_called_once_with("SRC", "DST", "S,W")

    async def test_rejects_unknown_state(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_requests.return_value = iter([])
        fn = registered_tools["rucio_list_requests"]
        result = await fn("SRC", "DST", "BOGUS", ctx=mock_ctx)
        output = tool_text(result)
        assert output.startswith("Error:")
        assert "SUBMITTED" in output  # lists valid names
        assert result.is_error is True
        mock_rucio_client.list_requests.assert_not_called()

    async def test_no_requests(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_requests.return_value = iter([])
        fn = registered_tools["rucio_list_requests"]
        result = await fn("SRC", "DST", "SUBMITTED", ctx=mock_ctx)
        assert "No requests" in tool_text(result)

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_requests.side_effect = RuntimeError("server error")
        fn = registered_tools["rucio_list_requests"]
        result = await fn("SRC", "DST", "SUBMITTED", ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True


class TestRucioListRequestsHistory:
    async def test_returns_history(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_requests_history.return_value = iter(
            [
                {
                    "id": "req-001",
                    "state": "DONE",
                    "src_rse_id": "aaa",
                    "dst_rse_id": "bbb",
                }
            ]
        )
        fn = registered_tools["rucio_list_requests_history"]
        result = await fn(
            "CERN-PROD_DATADISK",
            "BNL-OSG2_DATADISK",
            "DONE",
            ctx=mock_ctx,
        )
        output = tool_text(result)
        assert "req-001" in output
        assert "DONE" in output

    async def test_passes_offset_and_limit(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_requests_history.return_value = iter([])
        fn = registered_tools["rucio_list_requests_history"]
        await fn("SRC", "DST", "DONE", limit=50, offset=10, ctx=mock_ctx)
        mock_rucio_client.list_requests_history.assert_called_once_with(
            "SRC", "DST", "D", offset=10, limit=50
        )

    async def test_no_history(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_requests_history.return_value = iter([])
        fn = registered_tools["rucio_list_requests_history"]
        result = await fn("SRC", "DST", "DONE", ctx=mock_ctx)
        assert "No request history" in tool_text(result)

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_requests_history.side_effect = RuntimeError(
            "server error"
        )
        fn = registered_tools["rucio_list_requests_history"]
        result = await fn("SRC", "DST", "DONE", ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True
