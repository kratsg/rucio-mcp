"""Tools for querying Rucio replication rules."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import format_dict, format_list, parse_did


def register(mcp: FastMCP) -> None:
    """Register replication rule tools with the MCP server."""

    @mcp.tool()
    async def rucio_list_rules(
        did: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List all replication rules for a DID.

        Shows each rule's ID, state, RSE expression, account, copies requested,
        and expiry. Use this to understand where data is being replicated and
        whether rules are OK, REPLICATING, STUCK, or SUSPENDED.

        Args:
            did: The data identifier in ``scope:name`` format.
        """
        try:
            scope, name = parse_did(did)
        except ValueError as exc:
            return str(exc)

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            results = list(client.list_did_rules(scope, name))
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"

        if not results:
            return "No replication rules found."
        return format_list(results)

    @mcp.tool()
    async def rucio_rule_info(
        rule_id: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Show detailed information about a specific replication rule.

        Returns the full rule record including state, RSE expression, account,
        locks OK/REPLICATING/STUCK counts, error message (if any), and dates.

        Args:
            rule_id: The replication rule UUID
                (e.g. ``a1b2c3d4-e5f6-...``).
        """
        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            result = client.get_replication_rule(rule_id)
            return format_dict(result)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"
