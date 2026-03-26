"""Tools for listing Rucio scopes."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002


def register(mcp: FastMCP) -> None:
    """Register scope tools with the MCP server."""

    @mcp.tool()
    async def rucio_list_scopes(*, ctx: Context[Any, Any]) -> str:
        """List all available scopes in the Rucio catalog.

        Scopes categorize datasets by campaign. Common ATLAS scopes include
        MC campaign scopes (``mc16_13TeV``, ``mc20_13TeV``, ``mc21_13p6TeV``),
        data-taking scopes (``data15_13TeV`` through ``data24_13p6TeV``),
        and user/group scopes (``user.<username>``, ``group.<groupname>``).
        """
        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            scopes = client.list_scopes()
            return "\n".join(sorted(scopes))
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"
