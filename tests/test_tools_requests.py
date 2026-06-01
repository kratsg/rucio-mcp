"""Tests for transfer request tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.tools.rucio_requests import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = FastMCP("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestRucioListRequests:
    async def test_returns_requests(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
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
        assert "req-001" in result
        assert "SUBMITTED" in result

    async def test_passes_correct_args(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_requests.return_value = iter([])
        fn = registered_tools["rucio_list_requests"]
        await fn("SRC", "DST", "SUBMITTED,WAITING", ctx=mock_ctx)
        mock_rucio_client.list_requests.assert_called_once_with(
            "SRC", "DST", ["SUBMITTED", "WAITING"]
        )

    async def test_no_requests(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_requests.return_value = iter([])
        fn = registered_tools["rucio_list_requests"]
        result = await fn("SRC", "DST", "SUBMITTED", ctx=mock_ctx)
        assert "No requests" in result

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_requests.side_effect = RuntimeError("server error")
        fn = registered_tools["rucio_list_requests"]
        result = await fn("SRC", "DST", "SUBMITTED", ctx=mock_ctx)
        assert result.startswith("Error:")


class TestRucioListRequestsHistory:
    async def test_returns_history(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
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
        assert "req-001" in result
        assert "DONE" in result

    async def test_passes_offset_and_limit(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_requests_history.return_value = iter([])
        fn = registered_tools["rucio_list_requests_history"]
        await fn("SRC", "DST", "DONE", limit=50, offset=10, ctx=mock_ctx)
        mock_rucio_client.list_requests_history.assert_called_once_with(
            "SRC", "DST", ["DONE"], offset=10, limit=50
        )

    async def test_no_history(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_requests_history.return_value = iter([])
        fn = registered_tools["rucio_list_requests_history"]
        result = await fn("SRC", "DST", "DONE", ctx=mock_ctx)
        assert "No request history" in result

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_requests_history.side_effect = RuntimeError(
            "server error"
        )
        fn = registered_tools["rucio_list_requests_history"]
        result = await fn("SRC", "DST", "DONE", ctx=mock_ctx)
        assert result.startswith("Error:")
