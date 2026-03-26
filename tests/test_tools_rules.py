"""Tests for replication rule tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.tools.rules import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = FastMCP("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestRucioListRules:
    async def test_returns_rules(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
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
        fn = registered_tools["rucio_list_rules"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "abc123" in result
        assert "CERN-PROD_DATADISK" in result

    async def test_passes_scope_and_name(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_did_rules.return_value = iter([])
        fn = registered_tools["rucio_list_rules"]
        await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        mock_rucio_client.list_did_rules.assert_called_once_with(
            "mc16_13TeV", "some.dataset"
        )

    async def test_no_rules(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_did_rules.return_value = iter([])
        fn = registered_tools["rucio_list_rules"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "No replication rules" in result

    async def test_invalid_did(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_list_rules"]
        result = await fn("nodidformat", ctx=mock_ctx)
        assert "scope:name" in result

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_did_rules.side_effect = RuntimeError("server error")
        fn = registered_tools["rucio_list_rules"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "Error" in result


class TestRucioRuleInfo:
    async def test_returns_rule_info(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_replication_rule.return_value = {
            "id": "abc123",
            "state": "REPLICATING",
            "rse_expression": "BNL-OSG2_DATADISK",
            "locks_ok_cnt": 0,
            "locks_replicating_cnt": 5,
        }
        fn = registered_tools["rucio_rule_info"]
        result = await fn("abc123", ctx=mock_ctx)
        assert "REPLICATING" in result
        assert "BNL-OSG2_DATADISK" in result

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.get_replication_rule.side_effect = RuntimeError("not found")
        fn = registered_tools["rucio_rule_info"]
        result = await fn("bad-uuid", ctx=mock_ctx)
        assert "Error" in result


class TestRucioListRuleHistory:
    async def test_returns_history(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
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
        assert "REPLICATING" in result

    async def test_invalid_did(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_list_rule_history"]
        result = await fn("nodidformat", ctx=mock_ctx)
        assert "scope:name" in result

    async def test_no_history(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.list_replication_rule_full_history.return_value = iter([])
        fn = registered_tools["rucio_list_rule_history"]
        result = await fn("mc16_13TeV:some.dataset", ctx=mock_ctx)
        assert "No rule history" in result


class TestRucioAddRule:
    async def test_creates_rule(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.add_replication_rule.return_value = ["rule-id-xyz"]
        fn = registered_tools["rucio_add_rule"]
        result = await fn(
            "mc16_13TeV:some.dataset",
            copies=1,
            rse_expression="CERN-PROD_DATADISK",
            ctx=mock_ctx,
        )
        assert "rule-id-xyz" in result

    async def test_passes_correct_args(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
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
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx_readonly: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_add_rule"]
        result = await fn(
            "mc16_13TeV:some.dataset",
            copies=1,
            rse_expression="CERN-PROD_DATADISK",
            ctx=mock_ctx_readonly,
        )
        assert "read-only" in result.lower()

    async def test_invalid_did(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_add_rule"]
        result = await fn("nodidformat", copies=1, rse_expression="X", ctx=mock_ctx)
        assert "scope:name" in result

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.add_replication_rule.side_effect = RuntimeError(
            "quota exceeded"
        )
        fn = registered_tools["rucio_add_rule"]
        result = await fn(
            "mc16_13TeV:some.dataset", copies=1, rse_expression="X", ctx=mock_ctx
        )
        assert "Error" in result


class TestRucioDeleteRule:
    async def test_deletes_rule(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_delete_rule"]
        result = await fn("abc123", ctx=mock_ctx)
        mock_rucio_client.delete_replication_rule.assert_called_once_with(
            "abc123", purge_replicas=False
        )
        assert "deleted" in result.lower()

    async def test_purge_replicas(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
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
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx_readonly: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_delete_rule"]
        result = await fn("abc123", ctx=mock_ctx_readonly)
        assert "read-only" in result.lower()

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.delete_replication_rule.side_effect = RuntimeError(
            "not found"
        )
        fn = registered_tools["rucio_delete_rule"]
        result = await fn("bad-uuid", ctx=mock_ctx)
        assert "Error" in result


class TestRucioUpdateRule:
    async def test_updates_lifetime(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_update_rule"]
        result = await fn("abc123", lifetime=3600, ctx=mock_ctx)
        mock_rucio_client.update_replication_rule.assert_called_once_with(
            "abc123", {"lifetime": 3600}
        )
        assert "updated" in result.lower()

    async def test_updates_multiple_fields(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_update_rule"]
        await fn("abc123", lifetime=3600, comment="test", locked=True, ctx=mock_ctx)
        call_options = mock_rucio_client.update_replication_rule.call_args[0][1]
        assert call_options["lifetime"] == 3600
        assert call_options["comment"] == "test"
        assert call_options["locked"] is True

    async def test_blocked_in_read_only_mode(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx_readonly: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_update_rule"]
        result = await fn("abc123", lifetime=3600, ctx=mock_ctx_readonly)
        assert "read-only" in result.lower()

    async def test_client_error(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.update_replication_rule.side_effect = RuntimeError(
            "not found"
        )
        fn = registered_tools["rucio_update_rule"]
        result = await fn("bad-uuid", lifetime=3600, ctx=mock_ctx)
        assert "Error" in result


class TestRucioReduceRule:
    async def test_reduces_copies(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.reduce_replication_rule.return_value = "new-rule-id"
        fn = registered_tools["rucio_reduce_rule"]
        result = await fn("abc123", copies=1, ctx=mock_ctx)
        mock_rucio_client.reduce_replication_rule.assert_called_once_with(
            "abc123", 1, exclude_expression=None
        )
        assert "new-rule-id" in result

    async def test_blocked_in_read_only_mode(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx_readonly: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_reduce_rule"]
        result = await fn("abc123", copies=1, ctx=mock_ctx_readonly)
        assert "read-only" in result.lower()


class TestRucioMoveRule:
    async def test_moves_rule(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        mock_rucio_client.move_replication_rule.return_value = "new-rule-id"
        fn = registered_tools["rucio_move_rule"]
        result = await fn("abc123", rse_expression="BNL-OSG2_DATADISK", ctx=mock_ctx)
        mock_rucio_client.move_replication_rule.assert_called_once_with(
            "abc123", "BNL-OSG2_DATADISK", override={}
        )
        assert "new-rule-id" in result

    async def test_blocked_in_read_only_mode(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx_readonly: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_move_rule"]
        result = await fn(
            "abc123", rse_expression="BNL-OSG2_DATADISK", ctx=mock_ctx_readonly
        )
        assert "read-only" in result.lower()


class TestRucioApproveRule:
    async def test_approves_rule(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_approve_rule"]
        result = await fn("abc123", ctx=mock_ctx)
        mock_rucio_client.approve_replication_rule.assert_called_once_with("abc123")
        assert "approved" in result.lower()

    async def test_blocked_in_read_only_mode(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx_readonly: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_approve_rule"]
        result = await fn("abc123", ctx=mock_ctx_readonly)
        assert "read-only" in result.lower()


class TestRucioDenyRule:
    async def test_denies_rule(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx: MagicMock,
        mock_rucio_client: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_deny_rule"]
        result = await fn("abc123", ctx=mock_ctx)
        mock_rucio_client.deny_replication_rule.assert_called_once_with(
            "abc123", reason=None
        )
        assert "denied" in result.lower()

    async def test_deny_with_reason(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
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
        registered_tools: dict[str, Callable[..., Awaitable[str]]],
        mock_ctx_readonly: MagicMock,
    ) -> None:
        fn = registered_tools["rucio_deny_rule"]
        result = await fn("abc123", ctx=mock_ctx_readonly)
        assert "read-only" in result.lower()
