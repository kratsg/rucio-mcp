"""Tools for querying Rucio Storage Elements (RSEs)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import format_dict, format_list


def register(mcp: FastMCP) -> None:
    """Register RSE tools with the MCP server."""

    @mcp.tool()
    async def rucio_list_rses(
        rse_expression: str = "",
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List Rucio Storage Elements (RSEs) matching an expression.

        RSEs are the storage sites where data physically resides. Without a
        filter, all registered RSEs are returned. Use an RSE expression to
        narrow results by site, country, or type.

        Args:
            rse_expression: Boolean RSE expression for filtering.
                Examples:
                  ``CERN-PROD_DATADISK`` — a specific RSE by name
                  ``country=US&type=DISK`` — US disk sites
                  ``tier=1`` — Tier-1 sites only
        """
        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            rse_filter = rse_expression or None
            results = list(client.list_rses(rse_expression=rse_filter))
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"

        if not results:
            return "No RSEs found."
        return "\n".join(r["rse"] for r in results if isinstance(r, dict))

    @mcp.tool()
    async def rucio_list_rse_attributes(
        rse: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List the attributes (key-value pairs) of a specific RSE.

        RSE attributes describe properties like type (DISK/TAPE), tier,
        country, and site-specific configuration used in RSE expressions.

        Args:
            rse: The exact RSE name (e.g. ``CERN-PROD_DATADISK``).
        """
        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            result = client.list_rse_attributes(rse)
            return format_dict(result)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"

    @mcp.tool()
    async def rucio_list_rse_usage(
        rse: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Show total, used, and free storage space for an RSE.

        Args:
            rse: The exact RSE name (e.g. ``CERN-PROD_DATADISK``).
        """
        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            results = list(client.get_rse_usage(rse))
            return format_list(results)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"
