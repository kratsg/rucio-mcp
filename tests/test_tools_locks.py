"""Tests for dataset lock tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from mcp.server.mcpserver import MCPServer

from rucio_mcp.tools.locks import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock

    from mcp.types import CallToolResult


@pytest.fixture
def lock_tools() -> dict[str, Any]:
    mcp = MCPServer("test")
    register(mcp)
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


@pytest.fixture
def registered_tools(
    lock_tools: dict[str, Any],
) -> dict[str, Callable[..., Awaitable[CallToolResult]]]:
    return {name: tool.fn for name, tool in lock_tools.items()}


class TestLockToolsRegistration:
    def test_declares_read_only_annotations(self, lock_tools: dict[str, Any]) -> None:
        for tool in lock_tools.values():
            assert tool.annotations is not None, tool.name
            assert tool.annotations.read_only_hint is True, tool.name
            assert tool.annotations.open_world_hint is True, tool.name

    def test_publishes_output_schemas(self, lock_tools: dict[str, Any]) -> None:
        assert "locks" in lock_tools["rucio_get_dataset_locks"].output_schema["properties"]
        assert (
            "locks" in lock_tools["rucio_get_dataset_locks_by_rse"].output_schema["properties"]
        )


class TestRucioGetDatasetLocks:
    async def test_returns_locks(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_dataset_locks.return_value = iter(
            [
                {
                    "scope": "mc16_13TeV",
                    "name": "some.dataset",
                    "rse": "CERN-PROD_DATADISK",
                    "state": "OK",
                    "account": "gstark",
                }
            ]
        )
        fn = registered_tools["rucio_get_dataset_locks"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        output = tool_text(result)
        assert "CERN-PROD_DATADISK" in output
        assert "OK" in output
        assert result.structured_content is not None
        assert result.structured_content["locks"][0]["rse"] == "CERN-PROD_DATADISK"
        assert result.structured_content["did"] == "mc16_13TeV:some.dataset"

    async def test_passes_scope_and_name(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_dataset_locks.return_value = iter([])
        fn = registered_tools["rucio_get_dataset_locks"]
        await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        mock_rucio_client.get_dataset_locks.assert_called_once_with(
            "mc16_13TeV", "some.dataset"
        )

    async def test_invalid_did(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_get_dataset_locks"]
        result = await fn("a:b:c", ctx=mock_ctx)
        assert "Cannot extract scope" in tool_text(result)
        assert result.is_error is True

    async def test_no_locks(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_dataset_locks.return_value = iter([])
        fn = registered_tools["rucio_get_dataset_locks"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "No locks" in tool_text(result)
        assert result.structured_content == {
            "did": "mc16_13TeV:some.dataset",
            "locks": [],
            "offset": 0,
            "limit": 100,
            "truncated": False,
        }

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_dataset_locks.side_effect = RuntimeError("server error")
        fn = registered_tools["rucio_get_dataset_locks"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True


class TestRucioGetDatasetLocksByRse:
    async def test_returns_locks(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_dataset_locks_by_rse.return_value = iter(
            [
                {
                    "scope": "mc16_13TeV",
                    "name": "some.dataset",
                    "rse": "CERN-PROD_DATADISK",
                    "state": "OK",
                }
            ]
        )
        fn = registered_tools["rucio_get_dataset_locks_by_rse"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert "some.dataset" in tool_text(result)
        assert result.structured_content is not None
        assert result.structured_content["rse"] == "CERN-PROD_DATADISK"

    async def test_passes_rse(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_dataset_locks_by_rse.return_value = iter([])
        fn = registered_tools["rucio_get_dataset_locks_by_rse"]
        await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        mock_rucio_client.get_dataset_locks_by_rse.assert_called_once_with(
            "CERN-PROD_DATADISK"
        )

    async def test_no_locks(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_dataset_locks_by_rse.return_value = iter([])
        fn = registered_tools["rucio_get_dataset_locks_by_rse"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert "No locks" in tool_text(result)

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_dataset_locks_by_rse.side_effect = RuntimeError("error")
        fn = registered_tools["rucio_get_dataset_locks_by_rse"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True
