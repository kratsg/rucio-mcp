"""Tests for replica tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.tools.replicas import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = FastMCP("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestRucioListFileReplicas:
    async def test_returns_replicas(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_replicas.return_value = iter(
            [
                {
                    "scope": "mc16_13TeV",
                    "name": "file1.pool.root",
                    "pfns": {
                        "root://eosatlas.cern.ch//eos/atlas/file1.pool.root": {
                            "rse": "CERN-PROD_DATADISK",
                            "type": "DISK",
                        }
                    },
                }
            ]
        )
        fn = registered_tools["rucio_list_file_replicas"]
        result = await fn("mc16_13TeV:file1.pool.root", ctx=mock_ctx)
        assert "CERN-PROD_DATADISK" in result
        assert "eosatlas.cern.ch" in result

    async def test_passes_multiple_dids(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_replicas.return_value = iter([])
        fn = registered_tools["rucio_list_file_replicas"]
        await fn("mc16_13TeV:file1.pool.root mc16_13TeV:file2.pool.root", ctx=mock_ctx)
        call_args = mock_rucio_client.list_replicas.call_args[0][0]
        assert len(call_args) == 2
        assert call_args[0] == {"scope": "mc16_13TeV", "name": "file1.pool.root"}

    async def test_protocol_filter(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_replicas.return_value = iter([])
        fn = registered_tools["rucio_list_file_replicas"]
        await fn("mc16_13TeV:file1", protocols="root,https", ctx=mock_ctx)
        kwargs = mock_rucio_client.list_replicas.call_args[1]
        assert kwargs["schemes"] == ["root", "https"]

    async def test_invalid_did(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_list_file_replicas"]
        result = await fn("nodidformat", ctx=mock_ctx)
        assert "scope:name" in result

    async def test_no_replicas(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_replicas.return_value = iter([])
        fn = registered_tools["rucio_list_file_replicas"]
        result = await fn("mc16_13TeV:file1", ctx=mock_ctx)
        assert "No replicas" in result


class TestRucioListDatasetReplicas:
    async def test_returns_replicas(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_dataset_replicas.return_value = iter(
            [
                {
                    "rse": "CERN-PROD_DATADISK",
                    "available_bytes": 10000,
                    "available_length": 5,
                    "state": "AVAILABLE",
                }
            ]
        )
        fn = registered_tools["rucio_list_dataset_replicas"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "CERN-PROD_DATADISK" in result

    async def test_no_replicas(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_dataset_replicas.return_value = iter([])
        fn = registered_tools["rucio_list_dataset_replicas"]
        result = await fn("mc16_13TeV:nonexistent", ctx=mock_ctx)
        assert "No dataset replicas" in result
