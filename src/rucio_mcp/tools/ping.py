"""Tools for server connectivity and account identity."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import format_dict


def register(mcp: FastMCP) -> None:
    """Register ping and whoami tools with the MCP server."""

    @mcp.tool()
    async def rucio_ping(*, ctx: Context[Any, Any]) -> str:
        """Ping the Rucio server and return its version.

        Use this tool to verify that the Rucio server is reachable and to
        check which server version is running.
        """
        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            result = client.ping()
            return format_dict(result) if isinstance(result, dict) else str(result)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"

    @mcp.tool()
    async def rucio_whoami(*, ctx: Context[Any, Any]) -> str:
        """Return information about the currently authenticated Rucio account.

        Shows account name, type, email, status, and creation date.
        Use this to confirm that authentication is working correctly.
        """
        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            result = client.whoami()
            return format_dict(result)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"
