"""Tests for replica tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.tools.replicas import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator
    from unittest.mock import MagicMock


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = FastMCP("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestRucioListReplicas:
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
        fn = registered_tools["rucio_list_replicas"]
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
        fn = registered_tools["rucio_list_replicas"]
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
        fn = registered_tools["rucio_list_replicas"]
        await fn("mc16_13TeV:file1", protocols="root,https", ctx=mock_ctx)
        kwargs = mock_rucio_client.list_replicas.call_args[1]
        assert kwargs["schemes"] == ["root", "https"]

    async def test_invalid_did(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_list_replicas"]
        result = await fn("a:b:c", ctx=mock_ctx)
        assert "Cannot extract scope" in result

    async def test_no_replicas(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_replicas.return_value = iter([])
        fn = registered_tools["rucio_list_replicas"]
        result = await fn("mc16_13TeV:file1", ctx=mock_ctx)
        assert "No replicas" in result

    async def test_returns_markdown_format(
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
        fn = registered_tools["rucio_list_replicas"]
        result = await fn("mc16_13TeV:file1.pool.root", ctx=mock_ctx)
        assert "### `mc16_13TeV:file1.pool.root`" in result
        assert "- **CERN-PROD_DATADISK:**" in result


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

    async def test_does_not_walk_container_children(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        """rucio_list_dataset_replicas must NOT walk list_content for containers.
        Use rucio_list_container_replicas for that."""
        mock_rucio_client.list_dataset_replicas.return_value = iter([])
        fn = registered_tools["rucio_list_dataset_replicas"]
        await fn("mc16_13TeV:some.container", ctx=mock_ctx)
        mock_rucio_client.list_content.assert_not_called()

    async def test_does_not_materialize_full_iterator(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        """Regression: pass the client iterator straight to paginate_iter
        instead of list()-ing all RSE rows up front."""
        consumed = 0

        def _huge_replicas() -> Iterator[dict[str, str]]:
            nonlocal consumed
            for i in range(100_000):
                consumed += 1
                yield {"rse": f"RSE{i}", "state": "AVAILABLE"}

        mock_rucio_client.list_dataset_replicas.return_value = _huge_replicas()
        fn = registered_tools["rucio_list_dataset_replicas"]
        await fn("mc16_13TeV:some.dataset", limit=2, ctx=mock_ctx)
        assert consumed <= 3  # offset(0) + limit(2) + 1


class TestRucioListContainerReplicas:
    async def test_walks_children_and_aggregates_replicas(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        """Container DID is walked via list_content; child dataset replicas are aggregated."""
        child_name = (
            "mc16_13TeV.538179.MGPy8EG.deriv.DAOD_SUSY5.e8545_p4172_tid40499505_00"
        )
        mock_rucio_client.list_content.return_value = iter(
            [{"scope": "mc16_13TeV", "name": child_name, "type": "DATASET"}]
        )
        mock_rucio_client.list_dataset_replicas.return_value = iter(
            [
                {
                    "rse": "IN2P3-LAPP-DCACHE_DATADISK",
                    "available_bytes": 700000000,
                    "available_length": 10,
                    "state": "AVAILABLE",
                }
            ]
        )
        fn = registered_tools["rucio_list_container_replicas"]
        result = await fn(
            "mc16_13TeV:mc16_13TeV.538179.MGPy8EG.deriv.DAOD_SUSY5.e8545_p4172",
            ctx=mock_ctx,
        )
        assert "IN2P3-LAPP-DCACHE_DATADISK" in result
        assert "AVAILABLE" in result

    async def test_no_children(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_content.return_value = iter([])
        fn = registered_tools["rucio_list_container_replicas"]
        result = await fn("mc16_13TeV:some.container", ctx=mock_ctx)
        assert "No" in result

    async def test_children_with_no_replicas(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_content.return_value = iter(
            [{"scope": "mc16_13TeV", "name": "child_ds", "type": "DATASET"}]
        )
        mock_rucio_client.list_dataset_replicas.return_value = iter([])
        fn = registered_tools["rucio_list_container_replicas"]
        result = await fn("mc16_13TeV:some.container", ctx=mock_ctx)
        assert "No" in result

    async def test_invalid_did(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_list_container_replicas"]
        result = await fn("a:b:c", ctx=mock_ctx)
        assert "Cannot extract scope" in result

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_content.side_effect = RuntimeError("server error")
        fn = registered_tools["rucio_list_container_replicas"]
        result = await fn("mc16_13TeV:some.container", ctx=mock_ctx)
        assert "Error" in result

    async def test_includes_hints(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_content.return_value = iter(
            [{"scope": "mc16_13TeV", "name": "child_ds", "type": "DATASET"}]
        )
        mock_rucio_client.list_dataset_replicas.return_value = iter(
            [
                {
                    "rse": "CERN-PROD_DATADISK",
                    "available_bytes": 1000,
                    "available_length": 1,
                    "state": "AVAILABLE",
                }
            ]
        )
        fn = registered_tools["rucio_list_container_replicas"]
        result = await fn("mc16_13TeV:some.container", ctx=mock_ctx)
        assert "rucio_list_did_rules" in result

    async def test_stops_early_once_page_is_filled(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        """Regression: a container with huge numbers of child datasets must
        not trigger a list_dataset_replicas call (an HTTP round-trip) per
        child up front — the walk should stop once the page is filled."""
        consumed_children = 0
        replica_calls = 0

        def _children() -> Iterator[dict[str, str]]:
            nonlocal consumed_children
            for i in range(100_000):
                consumed_children += 1
                yield {"scope": "mc16_13TeV", "name": f"child{i}", "type": "DATASET"}

        def _dataset_replicas(
            scope: str, name: str, deep: bool = False
        ) -> Iterator[dict[str, object]]:
            nonlocal replica_calls
            replica_calls += 1
            return iter(
                [
                    {
                        "rse": f"RSE-{scope}-{name}-{deep}",
                        "available_bytes": 1,
                        "available_length": 1,
                        "state": "AVAILABLE",
                    }
                ]
            )

        mock_rucio_client.list_content.return_value = _children()
        mock_rucio_client.list_dataset_replicas.side_effect = _dataset_replicas
        fn = registered_tools["rucio_list_container_replicas"]
        await fn("mc16_13TeV:big.container", limit=2, ctx=mock_ctx)
        assert consumed_children <= 3  # offset(0) + limit(2) + 1
        assert replica_calls <= 3
