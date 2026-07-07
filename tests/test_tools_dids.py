"""Tests for DID discovery and inspection tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.tools._helpers import parse_did
from rucio_mcp.tools.dids import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator
    from unittest.mock import MagicMock


class TestParseDid:
    def test_valid_did(self) -> None:
        assert parse_did("mc16_13TeV:foo.bar") == ("mc16_13TeV", "foo.bar")

    def test_multi_colon_raises(self) -> None:
        # rucio's canonical convention requires exactly one colon separator
        with pytest.raises(ValueError, match="exactly one colon"):
            parse_did("mc16_13TeV:foo:bar")

    def test_no_colon_dotted_did(self) -> None:
        # ATLAS-style dotted DIDs without a colon: scope is the first dot-part
        assert parse_did("mc16_13TeV.foo.bar") == ("mc16_13TeV", "mc16_13TeV.foo.bar")

    def test_no_colon_user_prefix(self) -> None:
        # user.* DIDs use the first two dot-parts as scope
        assert parse_did("user.jdoe.ds") == ("user.jdoe", "user.jdoe.ds")

    def test_no_colon_group_prefix(self) -> None:
        # group.* DIDs use the first two dot-parts as scope
        assert parse_did("group.phys-higgs.x") == (
            "group.phys-higgs",
            "group.phys-higgs.x",
        )

    def test_no_colon_trailing_slash_stripped(self) -> None:
        # rucio strips a single trailing slash from the name
        assert parse_did("mc16_13TeV.foo/")[1] == "mc16_13TeV.foo"

    def test_empty_scope_raises(self) -> None:
        with pytest.raises(ValueError, match="empty scope or name"):
            parse_did(":name")

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValueError, match="empty scope or name"):
            parse_did("scope:")


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
        result = await fn("a:b:c", ctx=mock_ctx)
        assert "Cannot extract scope" in result

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


class TestRucioGetDid:
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
        fn = registered_tools["rucio_get_did"]
        result = await fn(
            "mc16_13TeV:mc16_13TeV.700320.Sh_2211_Zee.deriv.DAOD_PHYS.e8351_p5855",
            ctx=mock_ctx,
        )
        assert "CONTAINER" in result
        assert "117.74 MB" in result

    async def test_container_hints_suggest_container_replicas(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_did.return_value = {
            "scope": "mc16_13TeV",
            "name": "some.container",
            "type": "CONTAINER",
        }
        fn = registered_tools["rucio_get_did"]
        result = await fn("mc16_13TeV:some.container", ctx=mock_ctx)
        assert "rucio_list_container_replicas" in result
        assert "rucio_list_content" not in result
        assert "rucio_get_metadata" not in result

    async def test_dataset_hints_suggest_dataset_replicas(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_did.return_value = {
            "scope": "mc16_13TeV",
            "name": "some.dataset",
            "type": "DATASET",
        }
        fn = registered_tools["rucio_get_did"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "rucio_list_dataset_replicas" in result
        assert "rucio_get_metadata" not in result

    async def test_invalid_did(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_get_did"]
        result = await fn("a:b:c", ctx=mock_ctx)
        assert "Cannot extract scope" in result


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

    async def test_does_not_materialize_full_iterator(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        """Regression: the tool must pass the client iterator straight to
        paginate_iter instead of list()-ing it first, otherwise a huge
        container is fully consumed to serve a small page."""
        consumed = 0

        def _huge_content() -> Iterator[dict[str, str]]:
            nonlocal consumed
            for i in range(100_000):
                consumed += 1
                yield {"scope": "mc16_13TeV", "name": f"item{i}", "type": "DATASET"}

        mock_rucio_client.list_content.return_value = _huge_content()
        fn = registered_tools["rucio_list_content"]
        await fn("mc16_13TeV:container1", limit=2, ctx=mock_ctx)
        assert consumed <= 3  # offset(0) + limit(2) + 1


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

    async def test_includes_hints(
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
        assert "rucio_list_replicas" in result

    async def test_does_not_materialize_full_iterator(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        """Regression: a 500k-file dataset must not be fully downloaded to
        serve a small page — the client iterator is fed to paginate_iter
        directly instead of being list()-ed first."""
        consumed = 0

        def _huge_files() -> Iterator[dict[str, str]]:
            nonlocal consumed
            for i in range(100_000):
                consumed += 1
                yield {"scope": "mc16_13TeV", "name": f"file{i}.pool.root"}

        mock_rucio_client.list_files.return_value = _huge_files()
        fn = registered_tools["rucio_list_files"]
        await fn("mc16_13TeV:dataset1", limit=2, ctx=mock_ctx)
        assert consumed <= 3  # offset(0) + limit(2) + 1


class TestRucioListParentDids:
    async def test_returns_parents(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_parent_dids.return_value = iter(
            [{"scope": "mc16_13TeV", "name": "parent.container", "type": "CONTAINER"}]
        )
        fn = registered_tools["rucio_list_parent_dids"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "parent.container" in result

    async def test_no_parents(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_parent_dids.return_value = iter([])
        fn = registered_tools["rucio_list_parent_dids"]
        result = await fn("mc16_13TeV:orphan", ctx=mock_ctx)
        assert "No parent DIDs" in result

    async def test_invalid_did(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_list_parent_dids"]
        result = await fn("a:b:c", ctx=mock_ctx)
        assert "Cannot extract scope" in result

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_parent_dids.side_effect = RuntimeError("server error")
        fn = registered_tools["rucio_list_parent_dids"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "Error" in result

    async def test_does_not_materialize_full_iterator(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        """Regression: pass the client iterator straight to paginate_iter."""
        consumed = 0

        def _huge_parents() -> Iterator[dict[str, str]]:
            nonlocal consumed
            for i in range(100_000):
                consumed += 1
                yield {"scope": "mc16_13TeV", "name": f"parent{i}"}

        mock_rucio_client.list_parent_dids.return_value = _huge_parents()
        fn = registered_tools["rucio_list_parent_dids"]
        await fn("mc16_13TeV:some.dataset", limit=2, ctx=mock_ctx)
        assert consumed <= 3  # offset(0) + limit(2) + 1


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

    async def test_includes_hints(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_metadata.return_value = {"datatype": "DAOD_PHYS"}
        fn = registered_tools["rucio_get_metadata"]
        result = await fn("mc20_13TeV:somename", ctx=mock_ctx)
        assert "rucio_get_did" in result
