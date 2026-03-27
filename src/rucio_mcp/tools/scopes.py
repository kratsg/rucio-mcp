"""Tools for listing Rucio scopes."""

from __future__ import annotations

import fnmatch
from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import build_hints, classify_error, paginate_iter


def register(mcp: FastMCP) -> None:
    """Register scope tools with the MCP server."""

    @mcp.tool()
    async def rucio_list_scopes(
        pattern: str = "",
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List all available scopes in the Rucio catalog.

        Scopes categorize datasets by campaign. Common ATLAS scopes include
        MC campaign scopes (``mc16_13TeV``, ``mc20_13TeV``, ``mc21_13p6TeV``),
        data-taking scopes (``data15_13TeV`` through ``data24_13p6TeV``),
        and user/group scopes (``user.<username>``, ``group.<groupname>``).

        Args:
            pattern: Optional wildcard pattern to filter scopes (e.g. ``mc*``,
                ``data2?_13TeV``, ``user.*``). Uses Unix shell-style matching.
                If empty, all scopes are returned.
            limit: Maximum number of scopes to return (default 100).
            offset: Number of scopes to skip for pagination.
        """
        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            scopes = client.list_scopes()
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if pattern:
            scopes = [s for s in scopes if fnmatch.fnmatch(s, pattern)]

        if not scopes:
            return "No scopes found matching the pattern."

        sorted_scopes = sorted(scopes)
        page, footer = paginate_iter(iter(sorted_scopes), limit=limit, offset=offset)
        hints = build_hints(
            ["Use `rucio_list_dids <scope>:*` to search for DIDs within a scope"]
        )
        return "\n".join(f"- {s}" for s in page) + footer + hints
