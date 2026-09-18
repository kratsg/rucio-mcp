"""Tests for replication rule tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from mcp.server.mcpserver import MCPServer

from rucio_mcp.tools.rules import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator
    from unittest.mock import MagicMock

    from mcp.types import CallToolResult


@pytest.fixture
def rule_tools() -> dict[str, Any]:
    mcp = MCPServer("test")
    register(mcp)
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


@pytest.fixture
def registered_tools(
    rule_tools: dict[str, Any],
) -> dict[str, Callable[..., Awaitable[CallToolResult]]]:
    return {name: tool.fn for name, tool in rule_tools.items()}


class TestRuleToolsRegistration:
    def test_read_only_tools_declare_read_only_annotations(
        self, rule_tools: dict[str, Any]
    ) -> None:
        read_only = {
            "rucio_list_did_rules",
            "rucio_get_replication_rule",
            "rucio_list_rule_history",
            "rucio_list_replication_rules",
        }
        for name in read_only:
            tool = rule_tools[name]
            assert tool.annotations is not None, name
            assert tool.annotations.read_only_hint is True, name
            assert tool.annotations.open_world_hint is True, name

    def test_mutating_tools_declare_non_destructive_annotations(
        self, rule_tools: dict[str, Any]
    ) -> None:
        mutating = {
            "rucio_add_rule",
            "rucio_update_rule",
            "rucio_reduce_rule",
            "rucio_move_rule",
            "rucio_approve_rule",
            "rucio_deny_rule",
        }
        for name in mutating:
            tool = rule_tools[name]
            assert tool.annotations is not None, name
            assert tool.annotations.read_only_hint is False, name
            assert tool.annotations.destructive_hint is not True, name

    def test_delete_rule_declares_destructive_annotation(
        self, rule_tools: dict[str, Any]
    ) -> None:
        tool = rule_tools["rucio_delete_rule"]
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is True

    def test_every_tool_publishes_an_output_schema(
        self, rule_tools: dict[str, Any]
    ) -> None:
        for name, tool in rule_tools.items():
            assert tool.output_schema is not None, name


class TestRucioListDidRules:
    async def test_returns_rules(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_did_rules.return_value = iter(
            [
                {
                    "id": "abc123",
                    "state": "OK",
                    "rse_expression": "CERN-PROD_DATADISK",
                    "account": "gstark",
                    "copies": 1,
                }
            ]
        )
        fn = registered_tools["rucio_list_did_rules"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "abc123" in tool_text(result)
        assert "CERN-PROD_DATADISK" in tool_text(result)

    async def test_passes_scope_and_name(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_did_rules.return_value = iter([])
        fn = registered_tools["rucio_list_did_rules"]
        await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        mock_rucio_client.list_did_rules.assert_called_once_with(
            "mc16_13TeV", "some.dataset"
        )

    async def test_no_rules(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_did_rules.return_value = iter([])
        fn = registered_tools["rucio_list_did_rules"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "No replication rules" in tool_text(result)

    async def test_invalid_did(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_list_did_rules"]
        result = await fn("a:b:c", ctx=mock_ctx)
        assert "Cannot extract scope" in tool_text(result)

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_did_rules.side_effect = RuntimeError("server error")
        fn = registered_tools["rucio_list_did_rules"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "Error" in tool_text(result)
        assert result.is_error is True

    async def test_pagination_footer_on_overflow(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_did_rules.return_value = iter(
            [{"id": f"rule{i}", "state": "OK"} for i in range(3)]
        )
        fn = registered_tools["rucio_list_did_rules"]
        result = await fn("mc16_13TeV:some.dataset", limit=2, ctx=mock_ctx)
        assert "rule0" in tool_text(result)
        assert "rule1" in tool_text(result)
        assert "rule2" not in tool_text(result)
        assert "offset=2" in tool_text(result)

    async def test_does_not_materialize_full_iterator(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        """Regression: pass the client iterator straight to paginate_iter
        instead of list()-ing all rules for the DID up front."""
        consumed = 0

        def _huge_rules() -> Iterator[dict[str, str]]:
            nonlocal consumed
            for i in range(100_000):
                consumed += 1
                yield {"id": f"rule{i}", "state": "OK"}

        mock_rucio_client.list_did_rules.return_value = _huge_rules()
        fn = registered_tools["rucio_list_did_rules"]
        await fn("mc16_13TeV:some.dataset", limit=2, ctx=mock_ctx)
        assert consumed <= 3  # offset(0) + limit(2) + 1


class TestRucioGetReplicationRule:
    async def test_returns_rule_info(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_replication_rule.return_value = {
            "id": "abc123",
            "state": "REPLICATING",
            "rse_expression": "BNL-OSG2_DATADISK",
            "locks_ok_cnt": 0,
            "locks_replicating_cnt": 5,
        }
        fn = registered_tools["rucio_get_replication_rule"]
        result = await fn("abc123", ctx=mock_ctx)
        assert "REPLICATING" in tool_text(result)
        assert "BNL-OSG2_DATADISK" in tool_text(result)

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.get_replication_rule.side_effect = RuntimeError("not found")
        fn = registered_tools["rucio_get_replication_rule"]
        result = await fn("bad-uuid", ctx=mock_ctx)
        assert "Error" in tool_text(result)
        assert result.is_error is True


class TestRucioListRuleHistory:
    async def test_returns_history(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_replication_rule_full_history.return_value = iter(
            [
                {"id": "abc123", "state": "OK", "rse_expression": "CERN-PROD_DATADISK"},
                {
                    "id": "abc123",
                    "state": "REPLICATING",
                    "rse_expression": "CERN-PROD_DATADISK",
                },
            ]
        )
        fn = registered_tools["rucio_list_rule_history"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "REPLICATING" in tool_text(result)

    async def test_invalid_did(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_list_rule_history"]
        result = await fn("a:b:c", ctx=mock_ctx)
        assert "Cannot extract scope" in tool_text(result)

    async def test_no_history(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_replication_rule_full_history.return_value = iter([])
        fn = registered_tools["rucio_list_rule_history"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "No rule history" in tool_text(result)

    async def test_includes_hints(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_replication_rule_full_history.return_value = iter(
            [{"id": "abc123", "state": "OK", "rse_expression": "CERN-PROD_DATADISK"}]
        )
        fn = registered_tools["rucio_list_rule_history"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "rucio_list_did_rules" in tool_text(result)

    async def test_does_not_materialize_full_iterator(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        """Regression: a long-lived DID's full rule history must not be
        fully downloaded to serve a small page."""
        consumed = 0

        def _huge_history() -> Iterator[dict[str, str]]:
            nonlocal consumed
            for i in range(100_000):
                consumed += 1
                yield {"id": "abc123", "state": "OK", "sequence_number": str(i)}

        mock_rucio_client.list_replication_rule_full_history.return_value = (
            _huge_history()
        )
        fn = registered_tools["rucio_list_rule_history"]
        await fn("mc16_13TeV:some.dataset", limit=2, ctx=mock_ctx)
        assert consumed <= 3  # offset(0) + limit(2) + 1


class TestRucioAddRule:
    async def test_creates_rule(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.add_replication_rule.return_value = ["rule-id-xyz"]
        fn = registered_tools["rucio_add_rule"]
        result = await fn(
            "mc16_13TeV:some.dataset",
            copies=1,
            rse_expression="CERN-PROD_DATADISK",
            ctx=mock_ctx,
        )
        assert "rule-id-xyz" in tool_text(result)

    async def test_returns_markdown_rule_ids(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.add_replication_rule.return_value = ["rule-id-xyz"]
        fn = registered_tools["rucio_add_rule"]
        result = await fn(
            "mc16_13TeV:some.dataset",
            copies=1,
            rse_expression="CERN-PROD_DATADISK",
            ctx=mock_ctx,
        )
        assert "**Created rule(s):**" in tool_text(result)
        assert "- `rule-id-xyz`" in tool_text(result)

    async def test_passes_correct_args(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.add_replication_rule.return_value = ["rule-id-xyz"]
        fn = registered_tools["rucio_add_rule"]
        await fn(
            "mc16_13TeV:dataset1 mc16_13TeV:dataset2",
            copies=2,
            rse_expression="tier=1",
            lifetime=86400,
            ctx=mock_ctx,
        )
        call_args = mock_rucio_client.add_replication_rule.call_args
        dids_arg = call_args[0][0]
        assert len(dids_arg) == 2
        assert dids_arg[0] == {"scope": "mc16_13TeV", "name": "dataset1"}
        assert call_args[0][1] == 2
        assert call_args[0][2] == "tier=1"
        assert call_args[1]["lifetime"] == 86400

    async def test_blocked_in_read_only_mode(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx_readonly: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_add_rule"]
        result = await fn(
            "mc16_13TeV:some.dataset",
            copies=1,
            rse_expression="CERN-PROD_DATADISK",
            ctx=mock_ctx_readonly,
        )
        assert "read-only" in tool_text(result).lower()

    async def test_invalid_did(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_add_rule"]
        result = await fn("a:b:c", copies=1, rse_expression="X", ctx=mock_ctx)
        assert "Cannot extract scope" in tool_text(result)

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.add_replication_rule.side_effect = RuntimeError(
            "quota exceeded"
        )
        fn = registered_tools["rucio_add_rule"]
        result = await fn(
            "mc16_13TeV:some.dataset", copies=1, rse_expression="X", ctx=mock_ctx
        )
        assert "Error" in tool_text(result)
        assert result.is_error is True


class TestRucioDeleteRule:
    async def test_deletes_rule(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_delete_rule"]
        result = await fn("abc123", ctx=mock_ctx)
        mock_rucio_client.delete_replication_rule.assert_called_once_with(
            "abc123", purge_replicas=False
        )
        assert "deleted" in tool_text(result).lower()

    async def test_purge_replicas(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_delete_rule"]
        await fn("abc123", purge_replicas=True, ctx=mock_ctx)
        mock_rucio_client.delete_replication_rule.assert_called_once_with(
            "abc123", purge_replicas=True
        )

    async def test_blocked_in_read_only_mode(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx_readonly: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_delete_rule"]
        result = await fn("abc123", ctx=mock_ctx_readonly)
        assert "read-only" in tool_text(result).lower()
        assert result.is_error is True

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.delete_replication_rule.side_effect = RuntimeError(
            "not found"
        )
        fn = registered_tools["rucio_delete_rule"]
        result = await fn("bad-uuid", ctx=mock_ctx)
        assert "Error" in tool_text(result)
        assert result.is_error is True

    async def test_includes_hints(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_delete_rule"]
        result = await fn("abc123", ctx=mock_ctx)
        assert "rucio_list_did_rules" in tool_text(result)


class TestRucioUpdateRule:
    async def test_updates_lifetime(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_update_rule"]
        result = await fn("abc123", lifetime=3600, ctx=mock_ctx)
        mock_rucio_client.update_replication_rule.assert_called_once_with(
            "abc123", {"lifetime": 3600}
        )
        assert "updated" in tool_text(result).lower()

    async def test_updates_multiple_fields(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_update_rule"]
        await fn("abc123", lifetime=3600, comment="test", locked=True, ctx=mock_ctx)
        call_options = mock_rucio_client.update_replication_rule.call_args[0][1]
        assert call_options["lifetime"] == 3600
        assert call_options["comment"] == "test"
        assert call_options["locked"] is True

    async def test_unlock_sends_false(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_update_rule"]
        await fn("abc123", locked=False, ctx=mock_ctx)
        call_options = mock_rucio_client.update_replication_rule.call_args[0][1]
        # Unlocking must actually be sent, not dropped as a falsy value.
        assert call_options["locked"] is False

    async def test_no_options_returns_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_update_rule"]
        result = await fn("abc123", ctx=mock_ctx)
        assert tool_text(result).startswith("Error:")
        mock_rucio_client.update_replication_rule.assert_not_called()

    async def test_blocked_in_read_only_mode(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx_readonly: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_update_rule"]
        result = await fn("abc123", lifetime=3600, ctx=mock_ctx_readonly)
        assert "read-only" in tool_text(result).lower()

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.update_replication_rule.side_effect = RuntimeError(
            "not found"
        )
        fn = registered_tools["rucio_update_rule"]
        result = await fn("bad-uuid", lifetime=3600, ctx=mock_ctx)
        assert "Error" in tool_text(result)
        assert result.is_error is True


class TestRucioReduceRule:
    async def test_reduces_copies(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.reduce_replication_rule.return_value = "new-rule-id"
        fn = registered_tools["rucio_reduce_rule"]
        result = await fn("abc123", copies=1, ctx=mock_ctx)
        mock_rucio_client.reduce_replication_rule.assert_called_once_with(
            "abc123", 1, exclude_expression=None
        )
        assert "new-rule-id" in tool_text(result)

    async def test_blocked_in_read_only_mode(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx_readonly: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_reduce_rule"]
        result = await fn("abc123", copies=1, ctx=mock_ctx_readonly)
        assert "read-only" in tool_text(result).lower()
        assert result.is_error is True


class TestRucioMoveRule:
    async def test_moves_rule(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.move_replication_rule.return_value = "new-rule-id"
        fn = registered_tools["rucio_move_rule"]
        result = await fn("abc123", rse_expression="BNL-OSG2_DATADISK", ctx=mock_ctx)
        mock_rucio_client.move_replication_rule.assert_called_once_with(
            "abc123", "BNL-OSG2_DATADISK", override={}
        )
        assert "new-rule-id" in tool_text(result)

    async def test_blocked_in_read_only_mode(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx_readonly: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_move_rule"]
        result = await fn(
            "abc123", rse_expression="BNL-OSG2_DATADISK", ctx=mock_ctx_readonly
        )
        assert "read-only" in tool_text(result).lower()
        assert result.is_error is True


class TestRucioApproveRule:
    async def test_approves_rule(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_approve_rule"]
        result = await fn("abc123", ctx=mock_ctx)
        mock_rucio_client.approve_replication_rule.assert_called_once_with("abc123")
        assert "approved" in tool_text(result).lower()

    async def test_blocked_in_read_only_mode(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx_readonly: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_approve_rule"]
        result = await fn("abc123", ctx=mock_ctx_readonly)
        assert "read-only" in tool_text(result).lower()
        assert result.is_error is True


class TestRucioListReplicationRules:
    async def test_returns_rules(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_replication_rules.return_value = iter(
            [
                {
                    "id": "abc123",
                    "state": "OK",
                    "rse_expression": "CERN-PROD_DATADISK",
                    "account": "gstark",
                    "scope": "mc20_13TeV",
                    "name": "some.dataset",
                }
            ]
        )
        fn = registered_tools["rucio_list_replication_rules"]
        result = await fn(ctx=mock_ctx)
        assert "abc123" in tool_text(result)
        assert "CERN-PROD_DATADISK" in tool_text(result)

    async def test_passes_scope_filter(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_replication_rules.return_value = iter([])
        fn = registered_tools["rucio_list_replication_rules"]
        await fn(scope="mc20_13TeV", ctx=mock_ctx)
        call_kwargs = mock_rucio_client.list_replication_rules.call_args[1]
        assert call_kwargs["filters"]["scope"] == "mc20_13TeV"

    async def test_passes_account_filter(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_replication_rules.return_value = iter([])
        fn = registered_tools["rucio_list_replication_rules"]
        await fn(account="gstark", ctx=mock_ctx)
        call_kwargs = mock_rucio_client.list_replication_rules.call_args[1]
        assert call_kwargs["filters"]["account"] == "gstark"

    async def test_empty_filters_when_no_params(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_replication_rules.return_value = iter([])
        fn = registered_tools["rucio_list_replication_rules"]
        await fn(ctx=mock_ctx)
        mock_rucio_client.list_replication_rules.assert_called_once_with(filters={})

    async def test_no_rules(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_replication_rules.return_value = iter([])
        fn = registered_tools["rucio_list_replication_rules"]
        result = await fn(ctx=mock_ctx)
        assert "No replication rules" in tool_text(result)

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        mock_rucio_client.list_replication_rules.side_effect = RuntimeError(
            "server error"
        )
        fn = registered_tools["rucio_list_replication_rules"]
        result = await fn(ctx=mock_ctx)
        assert "Error" in tool_text(result)
        assert result.is_error is True


class TestRucioDenyRule:
    async def test_denies_rule(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_deny_rule"]
        result = await fn("abc123", ctx=mock_ctx)
        mock_rucio_client.deny_replication_rule.assert_called_once_with(
            "abc123", reason=None
        )
        assert "denied" in tool_text(result).lower()

    async def test_deny_with_reason(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_deny_rule"]
        await fn("abc123", reason="quota exceeded", ctx=mock_ctx)
        mock_rucio_client.deny_replication_rule.assert_called_once_with(
            "abc123", reason="quota exceeded"
        )

    async def test_blocked_in_read_only_mode(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        mock_ctx_readonly: MagicMock,
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_deny_rule"]
        result = await fn("abc123", ctx=mock_ctx_readonly)
        assert "read-only" in tool_text(result).lower()
