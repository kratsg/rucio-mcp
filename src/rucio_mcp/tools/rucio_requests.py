"""Tools for querying Rucio transfer requests."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import (
    build_hints,
    classify_error,
    format_list,
    get_rucio_client,
    paginate_iter,
)


def _parse_states(request_states: str) -> list[str]:
    """Split a comma- or space-separated states string into a list."""
    # Normalise: replace commas with spaces then split
    return request_states.replace(",", " ").split()


def register(mcp: FastMCP) -> None:
    """Register transfer request tools with the MCP server."""

    @mcp.tool()
    async def rucio_list_requests(
        src_rse: str,
        dst_rse: str,
        request_states: str,
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List current transfer requests between two RSEs.

        Returns in-flight transfer requests filtered by source RSE, destination
        RSE, and one or more states. Useful for monitoring active transfers.

        Args:
            src_rse: Source RSE name (e.g. ``CERN-PROD_DATADISK``).
            dst_rse: Destination RSE name (e.g. ``BNL-OSG2_DATADISK``).
            request_states: Comma- or space-separated list of states to include.
                Common values: ``SUBMITTED``, ``WAITING``, ``FAILED``, ``DONE``.
            limit: Maximum number of requests to return (default 100).
            offset: Number of requests to skip for pagination.
        """
        client = get_rucio_client(ctx)
        states = _parse_states(request_states)
        try:
            it = client.list_requests(src_rse, dst_rse, states)
            results, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return "No requests found."

        hints = build_hints(
            [
                f"Use `rucio_list_requests_history {src_rse} {dst_rse} DONE` to see completed transfers"
            ]
        )
        return format_list(results) + footer + hints

    @mcp.tool()
    async def rucio_list_requests_history(
        src_rse: str,
        dst_rse: str,
        request_states: str,
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List historical transfer requests between two RSEs.

        Returns past transfer requests. The rucio server handles offset/limit
        pagination natively for this endpoint.

        Args:
            src_rse: Source RSE name (e.g. ``CERN-PROD_DATADISK``).
            dst_rse: Destination RSE name (e.g. ``BNL-OSG2_DATADISK``).
            request_states: Comma- or space-separated list of states to include.
                Common values: ``DONE``, ``FAILED``, ``LOST``.
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip for pagination.
        """
        client = get_rucio_client(ctx)
        states = _parse_states(request_states)
        try:
            it = client.list_requests_history(
                src_rse, dst_rse, states, offset=offset, limit=limit
            )
            results = list(it)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return "No request history found."

        # Build a pagination footer if we received a full page (may be more)
        footer = ""
        if len(results) == limit:
            footer = (
                f"\n\n---\nShowing {limit} results (offset={offset}). "
                f"Pass offset={offset + limit} to see more."
            )

        hints = build_hints(
            [
                f"Use `rucio_list_requests {src_rse} {dst_rse} SUBMITTED` to see current transfers"
            ]
        )
        return format_list(results) + footer + hints
