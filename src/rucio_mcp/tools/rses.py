"""Tools for querying Rucio Storage Elements (RSEs)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import (
    build_hints,
    classify_error,
    format_dict,
    format_list,
    get_rucio_client,
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
        client = get_rucio_client(ctx)
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
                "Use `rucio_get_rse_usage <rse>` to check storage capacity",
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
        client = get_rucio_client(ctx)
        try:
            result = client.list_rse_attributes(rse)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [f"Use `rucio_get_rse_usage {rse}` to check storage capacity"]
        )
        return format_dict(result) + hints

    @mcp.tool()
    async def rucio_get_rse_usage(
        rse: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Show total, used, and free storage space for an RSE.

        Args:
            rse: The exact RSE name (e.g. ``CERN-PROD_DATADISK``).
        """
        client = get_rucio_client(ctx)
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

    @mcp.tool()
    async def rucio_get_rse(
        rse: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Show detailed information about a specific RSE.

        Returns RSE type, deterministic flag, volatile flag, and other
        configuration details for the named storage element.

        Args:
            rse: The exact RSE name (e.g. ``CERN-PROD_DATADISK``).
        """
        client = get_rucio_client(ctx)
        try:
            result = client.get_rse(rse)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [
                f"Use `rucio_list_rse_attributes {rse}` to see RSE properties (type, tier, country)",
                f"Use `rucio_get_rse_usage {rse}` to check storage capacity",
            ]
        )
        return format_dict(result) + hints

    @mcp.tool()
    async def rucio_get_rse_limits(
        rse: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Show the configured space limits for an RSE.

        Returns limit entries such as ``MaxBeingDeletedFiles`` and
        ``MinFreeSpace`` set by the site administrators.

        Args:
            rse: The exact RSE name (e.g. ``CERN-PROD_DATADISK``).
        """
        client = get_rucio_client(ctx)
        try:
            results = list(client.get_rse_limits(rse))
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return "No limits configured for this RSE."

        hints = build_hints(
            [f"Use `rucio_get_rse_usage {rse}` to check current space consumption"]
        )
        return format_list(results) + hints

    @mcp.tool()
    async def rucio_get_rse_protocols(
        rse: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List the transfer protocols supported by an RSE.

        Returns protocol details including scheme (root, https, srm), hostname,
        port, and prefix for each supported protocol.

        Args:
            rse: The exact RSE name (e.g. ``CERN-PROD_DATADISK``).
        """
        client = get_rucio_client(ctx)
        try:
            result = client.get_protocols(rse)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [f"Use `rucio_list_rse_attributes {rse}` to see RSE properties"]
        )
        if isinstance(result, dict):
            return format_dict(result) + hints
        return str(result) + hints

    @mcp.tool()
    async def rucio_get_distance(
        source: str,
        destination: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Show the network distance (ranking) between two RSEs.

        The distance ranking is used by Rucio's transfer scheduler to prefer
        closer RSEs when choosing a data source. Lower ranking = closer.

        Args:
            source: The source RSE name (e.g. ``CERN-PROD_DATADISK``).
            destination: The destination RSE name.
        """
        client = get_rucio_client(ctx)
        try:
            results = client.get_distance(source, destination)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return f"No distance information found between {source} and {destination}."

        hints = build_hints(["Use `rucio_list_rses` to find valid RSE names"])
        return format_list(results) + hints

    @mcp.tool()
    async def rucio_list_transfer_limits(
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List global transfer limit policies.

        Returns the transfer limit entries that constrain concurrent transfers
        by activity and RSE.

        Args:
            limit: Maximum number of entries to return (default 100).
            offset: Number of entries to skip for pagination.
        """
        client = get_rucio_client(ctx)
        try:
            it = client.list_transfer_limits()
            results, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return "No transfer limits configured."

        hints = build_hints(["Use `rucio_list_rses` to look up RSE details"])
        return format_list(results) + footer + hints
