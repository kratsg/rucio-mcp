"""Tests for scope listing tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.tools.scopes import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = FastMCP("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestRucioListScopes:
    async def test_returns_scopes(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_scopes.return_value = ["mc20_13TeV", "data18_13TeV"]
        fn = registered_tools["rucio_list_scopes"]
        result = await fn(ctx=mock_ctx)
        assert "mc20_13TeV" in result
        assert "data18_13TeV" in result

    async def test_returns_markdown_bullet_list(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_scopes.return_value = ["mc20_13TeV", "data18_13TeV"]
        fn = registered_tools["rucio_list_scopes"]
        result = await fn(ctx=mock_ctx)
        assert "- mc20_13TeV" in result
        assert "- data18_13TeV" in result

    async def test_returns_sorted(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_scopes.return_value = ["zzz_scope", "aaa_scope"]
        fn = registered_tools["rucio_list_scopes"]
        result = await fn(ctx=mock_ctx)
        assert result.index("aaa_scope") < result.index("zzz_scope")

    async def test_pattern_filters_scopes(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_scopes.return_value = [
            "mc20_13TeV",
            "mc16_13TeV",
            "data18_13TeV",
        ]
        fn = registered_tools["rucio_list_scopes"]
        result = await fn(pattern="mc*", ctx=mock_ctx)
        assert "mc20_13TeV" in result
        assert "mc16_13TeV" in result
        assert "data18_13TeV" not in result

    async def test_empty_pattern_returns_all(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_scopes.return_value = ["mc20_13TeV", "data18_13TeV"]
        fn = registered_tools["rucio_list_scopes"]
        result = await fn(ctx=mock_ctx)
        assert "mc20_13TeV" in result
        assert "data18_13TeV" in result

    async def test_pattern_no_match_returns_empty_message(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_scopes.return_value = ["mc20_13TeV", "data18_13TeV"]
        fn = registered_tools["rucio_list_scopes"]
        result = await fn(pattern="user.*", ctx=mock_ctx)
        assert "No scopes" in result

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_scopes.side_effect = RuntimeError("auth failed")
        fn = registered_tools["rucio_list_scopes"]
        result = await fn(ctx=mock_ctx)
        assert result.startswith("Error:")


class TestRucioListScopesForAccount:
    async def test_returns_scopes(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.list_scopes_for_account.return_value = [
            "user.gstark",
            "user.gstark.test",
        ]
        fn = registered_tools["rucio_list_scopes_for_account"]
        result = await fn(ctx=mock_ctx)
        assert "user.gstark" in result

    async def test_uses_client_account_when_empty(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.list_scopes_for_account.return_value = []
        fn = registered_tools["rucio_list_scopes_for_account"]
        await fn(ctx=mock_ctx)
        mock_rucio_client.list_scopes_for_account.assert_called_once_with("gstark")

    async def test_uses_provided_account(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_scopes_for_account.return_value = ["user.otheruser"]
        fn = registered_tools["rucio_list_scopes_for_account"]
        await fn(account="otheruser", ctx=mock_ctx)
        mock_rucio_client.list_scopes_for_account.assert_called_once_with("otheruser")

    async def test_pattern_filters_scopes(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.list_scopes_for_account.return_value = [
            "user.gstark",
            "user.gstark.test",
        ]
        fn = registered_tools["rucio_list_scopes_for_account"]
        result = await fn(pattern="*.test", ctx=mock_ctx)
        assert "user.gstark.test" in result
        assert "- user.gstark\n" not in result

    async def test_no_scopes(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.list_scopes_for_account.return_value = []
        fn = registered_tools["rucio_list_scopes_for_account"]
        result = await fn(ctx=mock_ctx)
        assert "No scopes" in result

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.list_scopes_for_account.side_effect = RuntimeError("denied")
        fn = registered_tools["rucio_list_scopes_for_account"]
        result = await fn(ctx=mock_ctx)
        assert result.startswith("Error:")
