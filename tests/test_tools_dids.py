"""Tests for DID discovery and inspection tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.tools._helpers import parse_did
from rucio_mcp.tools.dids import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock


class TestParseDid:
    def test_valid_did(self) -> None:
        assert parse_did("mc16_13TeV:foo.bar") == ("mc16_13TeV", "foo.bar")

    def test_name_with_colon_uses_first_only(self) -> None:
        scope, name = parse_did("mc16_13TeV:foo:bar")
        assert scope == "mc16_13TeV"
        assert name == "foo:bar"

    def test_missing_colon_raises(self) -> None:
        with pytest.raises(ValueError, match="scope:name"):
            parse_did("nodidformat")


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = FastMCP("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestRucioListDids:
    async def test_returns_dids(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_dids.return_value = iter(
            [
                {"name": "mc20_13TeV.700320.Sh_2211_Zee.deriv.DAOD_PHYS.e8351_p5855"},
                {"name": "mc20_13TeV.700320.Sh_2211_Zee.deriv.DAOD_PHYS.e8351_p6026"},
            ]
        )
        fn = registered_tools["rucio_list_dids"]
        result = await fn("mc20_13TeV:mc20_13TeV.700320.*DAOD_PHYS*", ctx=mock_ctx)
        assert (
            "mc20_13TeV:mc20_13TeV.700320.Sh_2211_Zee.deriv.DAOD_PHYS.e8351_p5855"
            in result
        )

    async def test_passes_correct_args_to_client(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_dids.return_value = iter([])
        fn = registered_tools["rucio_list_dids"]
        await fn("data18_13TeV:data18*", did_type="container", ctx=mock_ctx)
        mock_rucio_client.list_dids.assert_called_once_with(
            "data18_13TeV",
            {"name": "data18*"},
            did_type="container",
            recursive=False,
        )

    async def test_empty_result(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_dids.return_value = iter([])
        fn = registered_tools["rucio_list_dids"]
        result = await fn("mc16_13TeV:nonexistent*", ctx=mock_ctx)
        assert "No DIDs found" in result

    async def test_invalid_did_format(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_list_dids"]
        result = await fn("nodidformat", ctx=mock_ctx)
        assert "scope:name" in result

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_dids.side_effect = RuntimeError("server error")
        fn = registered_tools["rucio_list_dids"]
        result = await fn("mc16_13TeV:foo*", ctx=mock_ctx)
        assert "Error" in result

    async def test_returns_markdown_bullet_list(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_dids.return_value = iter(
            [{"name": "mc20_13TeV.700320.Sh_2211_Zee.deriv.DAOD_PHYS.e8351_p5855"}]
        )
        fn = registered_tools["rucio_list_dids"]
        result = await fn("mc20_13TeV:mc20_13TeV.700320.*DAOD_PHYS*", ctx=mock_ctx)
        assert "- `mc20_13TeV:" in result


class TestRucioStat:
    async def test_returns_stat(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_did.return_value = {
            "scope": "mc16_13TeV",
            "name": "mc16_13TeV.700320.Sh_2211_Zee.deriv.DAOD_PHYS.e8351_p5855",
            "type": "CONTAINER",
            "bytes": 123456789,
            "length": 100,
        }
        fn = registered_tools["rucio_stat"]
        result = await fn(
            "mc16_13TeV:mc16_13TeV.700320.Sh_2211_Zee.deriv.DAOD_PHYS.e8351_p5855",
            ctx=mock_ctx,
        )
        assert "CONTAINER" in result
        assert "117.74 MB" in result

    async def test_invalid_did(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_stat"]
        result = await fn("invalid", ctx=mock_ctx)
        assert "scope:name" in result


class TestRucioListContent:
    async def test_returns_content(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_content.return_value = iter(
            [
                {"scope": "mc16_13TeV", "name": "dataset1", "type": "DATASET"},
            ]
        )
        fn = registered_tools["rucio_list_content"]
        result = await fn("mc16_13TeV:container1", ctx=mock_ctx)
        assert "dataset1" in result

    async def test_empty_content(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_content.return_value = iter([])
        fn = registered_tools["rucio_list_content"]
        result = await fn("mc16_13TeV:empty", ctx=mock_ctx)
        assert "No contents" in result


class TestRucioListFiles:
    async def test_returns_files_short(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_files.return_value = iter(
            [
                {"scope": "mc16_13TeV", "name": "file1.pool.root"},
                {"scope": "mc16_13TeV", "name": "file2.pool.root"},
            ]
        )
        fn = registered_tools["rucio_list_files"]
        result = await fn("mc16_13TeV:dataset1", ctx=mock_ctx)
        assert "mc16_13TeV:file1.pool.root" in result
        assert "mc16_13TeV:file2.pool.root" in result

    async def test_returns_markdown_bullet_list(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_files.return_value = iter(
            [{"scope": "mc16_13TeV", "name": "file1.pool.root"}]
        )
        fn = registered_tools["rucio_list_files"]
        result = await fn("mc16_13TeV:dataset1", ctx=mock_ctx)
        assert "- `mc16_13TeV:file1.pool.root`" in result

    async def test_long_mode(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_files.return_value = iter(
            [
                {
                    "scope": "mc16_13TeV",
                    "name": "file1.pool.root",
                    "bytes": 100,
                    "adler32": "abc",
                },
            ]
        )
        fn = registered_tools["rucio_list_files"]
        result = await fn("mc16_13TeV:dataset1", long=True, ctx=mock_ctx)
        assert "adler32" in result


class TestRucioGetMetadata:
    async def test_returns_metadata(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_metadata.return_value = {
            "datatype": "DAOD_PHYS",
            "project": "mc20_13TeV",
        }
        fn = registered_tools["rucio_get_metadata"]
        result = await fn("mc20_13TeV:somename", ctx=mock_ctx)
        assert "DAOD_PHYS" in result
