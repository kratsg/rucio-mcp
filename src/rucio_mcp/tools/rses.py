"""Tools for querying Rucio Storage Elements (RSEs)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import (
    build_hints,
    classify_error,
    format_dict,
    format_list,
    paginate_iter,
)

_RSE_USAGE_KEYS = ["source", "used", "free", "total", "files"]
_RSE_USAGE_BYTE_KEYS = frozenset({"used", "free", "total"})


def register(mcp: FastMCP) -> None:
    """Register RSE tools with the MCP server."""

    @mcp.tool()
    async def rucio_list_rses(
        rse_expression: str = "",
        limit: int = 100,
        offset: int = 0,
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
            limit: Maximum number of RSEs to return (default 100).
            offset: Number of RSEs to skip for pagination.
        """
        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            rse_filter = rse_expression or None
            it = iter(client.list_rses(rse_expression=rse_filter))
            results, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return "No RSEs found."

        lines = "\n".join(f"- `{r['rse']}`" for r in results if isinstance(r, dict))
        hints = build_hints(
            [
                "Use `rucio_list_rse_attributes <rse>` to see RSE properties (type, tier, country)",
                "Use `rucio_list_rse_usage <rse>` to check storage capacity",
            ]
        )
        return lines + footer + hints

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
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [f"Use `rucio_list_rse_usage {rse}` to check storage capacity"]
        )
        return format_dict(result) + hints

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
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [
                f"Use `rucio_list_rse_attributes {rse}` to see RSE properties (type, tier, country)"
            ]
        )
        return (
            format_list(
                results, include_keys=_RSE_USAGE_KEYS, byte_keys=_RSE_USAGE_BYTE_KEYS
            )
            + hints
        )
