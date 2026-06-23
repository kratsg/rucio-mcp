"""Tests for dataset lock tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.tools.locks import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = FastMCP("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestRucioGetDatasetLocks:
    async def test_returns_locks(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
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
        assert "CERN-PROD_DATADISK" in result
        assert "OK" in result

    async def test_passes_scope_and_name(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
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
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_get_dataset_locks"]
        result = await fn("a:b:c", ctx=mock_ctx)
        assert "Cannot extract scope" in result

    async def test_no_locks(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_dataset_locks.return_value = iter([])
        fn = registered_tools["rucio_get_dataset_locks"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "No locks" in result

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_dataset_locks.side_effect = RuntimeError("server error")
        fn = registered_tools["rucio_get_dataset_locks"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert result.startswith("Error:")


class TestRucioGetDatasetLocksByRse:
    async def test_returns_locks(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
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
        assert "some.dataset" in result

    async def test_passes_rse(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
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
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_dataset_locks_by_rse.return_value = iter([])
        fn = registered_tools["rucio_get_dataset_locks_by_rse"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert "No locks" in result

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_dataset_locks_by_rse.side_effect = RuntimeError("error")
        fn = registered_tools["rucio_get_dataset_locks_by_rse"]
        result = await fn("CERN-PROD_DATADISK", ctx=mock_ctx)
        assert result.startswith("Error:")
