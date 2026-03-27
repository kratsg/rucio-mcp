"""Tools for server connectivity and account identity."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import build_hints, classify_error, format_dict


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
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        body = format_dict(result) if isinstance(result, dict) else str(result)
        hints = build_hints(["Use `rucio_whoami` to check your authenticated account"])
        return body + hints

    @mcp.tool()
    async def rucio_whoami(*, ctx: Context[Any, Any]) -> str:
        """Return information about the currently authenticated Rucio account.

        Shows account name, type, email, status, and creation date.
        Use this to confirm that authentication is working correctly.
        """
        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            result = client.whoami()
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [
                "Use `rucio_list_account_usage` to check your storage consumption",
                "Use `rucio_list_account_limits` to see your storage quotas",
            ]
        )
        return format_dict(result) + hints
