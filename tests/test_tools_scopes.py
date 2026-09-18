"""Tests for scope listing tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from mcp.server.mcpserver import MCPServer

from rucio_mcp.tools.scopes import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock

    from mcp.types import CallToolResult


@pytest.fixture
def scope_tools() -> dict[str, Any]:
    mcp = MCPServer("test")
    register(mcp)
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


@pytest.fixture
def registered_tools(
    scope_tools: dict[str, Any],
) -> dict[str, Callable[..., Awaitable[CallToolResult]]]:
    return {name: tool.fn for name, tool in scope_tools.items()}


class TestScopeToolsRegistration:
    def test_declares_read_only_annotations(self, scope_tools: dict[str, Any]) -> None:
        for tool in scope_tools.values():
            assert tool.annotations is not None, tool.name
            assert tool.annotations.read_only_hint is True, tool.name
            assert tool.annotations.open_world_hint is True, tool.name

    def test_publishes_output_schemas(self, scope_tools: dict[str, Any]) -> None:
        assert "scopes" in scope_tools["rucio_list_scopes"].output_schema["properties"]
        assert (
            "scopes" in scope_tools["rucio_list_scopes_for_account"].output_schema["properties"]
        )


class TestRucioListScopes:
    async def test_returns_scopes(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_scopes.return_value = ["mc20_13TeV", "data18_13TeV"]
        fn = registered_tools["rucio_list_scopes"]
        result = await fn(ctx=mock_ctx)
        output = tool_text(result)
        assert "mc20_13TeV" in output
        assert "data18_13TeV" in output
        assert result.structured_content is not None
        assert set(result.structured_content["scopes"]) == {"mc20_13TeV", "data18_13TeV"}

    async def test_returns_markdown_bullet_list(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_scopes.return_value = ["mc20_13TeV", "data18_13TeV"]
        fn = registered_tools["rucio_list_scopes"]
        result = await fn(ctx=mock_ctx)
        output = tool_text(result)
        assert "- mc20_13TeV" in output
        assert "- data18_13TeV" in output

    async def test_returns_sorted(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_scopes.return_value = ["zzz_scope", "aaa_scope"]
        fn = registered_tools["rucio_list_scopes"]
        result = await fn(ctx=mock_ctx)
        output = tool_text(result)
        assert output.index("aaa_scope") < output.index("zzz_scope")

    async def test_pattern_filters_scopes(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_scopes.return_value = [
            "mc20_13TeV",
            "mc16_13TeV",
            "data18_13TeV",
        ]
        fn = registered_tools["rucio_list_scopes"]
        result = await fn(pattern="mc*", ctx=mock_ctx)
        output = tool_text(result)
        assert "mc20_13TeV" in output
        assert "mc16_13TeV" in output
        assert "data18_13TeV" not in output

    async def test_empty_pattern_returns_all(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_scopes.return_value = ["mc20_13TeV", "data18_13TeV"]
        fn = registered_tools["rucio_list_scopes"]
        result = await fn(ctx=mock_ctx)
        output = tool_text(result)
        assert "mc20_13TeV" in output
        assert "data18_13TeV" in output

    async def test_pattern_no_match_returns_empty_message(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_scopes.return_value = ["mc20_13TeV", "data18_13TeV"]
        fn = registered_tools["rucio_list_scopes"]
        result = await fn(pattern="user.*", ctx=mock_ctx)
        assert "No scopes" in tool_text(result)
        assert result.structured_content == {
            "pattern": "user.*",
            "scopes": [],
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
        mock_rucio_client.list_scopes.side_effect = RuntimeError("auth failed")
        fn = registered_tools["rucio_list_scopes"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True


class TestRucioListScopesForAccount:
    async def test_returns_scopes(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.list_scopes_for_account.return_value = [
            "user.gstark",
            "user.gstark.test",
        ]
        fn = registered_tools["rucio_list_scopes_for_account"]
        result = await fn(ctx=mock_ctx)
        assert "user.gstark" in tool_text(result)

    async def test_uses_client_account_when_empty(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
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
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_scopes_for_account.return_value = ["user.otheruser"]
        fn = registered_tools["rucio_list_scopes_for_account"]
        await fn(account="otheruser", ctx=mock_ctx)
        mock_rucio_client.list_scopes_for_account.assert_called_once_with("otheruser")

    async def test_pattern_filters_scopes(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.list_scopes_for_account.return_value = [
            "user.gstark",
            "user.gstark.test",
        ]
        fn = registered_tools["rucio_list_scopes_for_account"]
        result = await fn(pattern="*.test", ctx=mock_ctx)
        output = tool_text(result)
        assert "user.gstark.test" in output
        assert "- user.gstark\n" not in output

    async def test_no_scopes(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.list_scopes_for_account.return_value = []
        fn = registered_tools["rucio_list_scopes_for_account"]
        result = await fn(ctx=mock_ctx)
        assert "No scopes" in tool_text(result)

    async def test_error_on_exception(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.account = "gstark"
        mock_rucio_client.list_scopes_for_account.side_effect = RuntimeError("denied")
        fn = registered_tools["rucio_list_scopes_for_account"]
        result = await fn(ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        assert result.is_error is True
