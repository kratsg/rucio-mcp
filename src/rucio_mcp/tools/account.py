"""Tools for querying Rucio account usage and limits."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import format_dict, format_list


def register(mcp: FastMCP) -> None:
    """Register account tools with the MCP server."""

    @mcp.tool()
    async def rucio_list_account_usage(
        account: str = "",
        rse: str = "",
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Show how much storage an account is using at each RSE.

        Returns bytes used, bytes limit, and number of files per RSE.
        Useful for understanding your quota consumption across sites.

        Args:
            account: Rucio account name. Defaults to the authenticated account
                (from ``RUCIO_ACCOUNT`` env var or rucio.cfg).
            rse: Limit results to a specific RSE name. If empty, all RSEs
                with usage are returned.
        """
        client = ctx.request_context.lifespan_context["rucio_client"]
        effective_account = account or client.account
        try:
            rse_filter = rse or None
            results = list(
                client.get_local_account_usage(effective_account, rse=rse_filter)
            )
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"

        if not results:
            return "No account usage found."
        return format_list(results)

    @mcp.tool()
    async def rucio_list_account_limits(
        account: str = "",
        rse_expression: str = "",
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Show the storage quota limits for an account.

        Returns the byte limit set for the account at each RSE or group of RSEs
        matching the expression.

        Args:
            account: Rucio account name. Defaults to the authenticated account.
            rse_expression: RSE expression to filter limits. If empty, all
                limits are returned.
        """
        client = ctx.request_context.lifespan_context["rucio_client"]
        effective_account = account or client.account
        try:
            if rse_expression:
                result = client.get_account_limits(
                    effective_account,
                    rse_expression=rse_expression,
                    locality="local",
                )
            else:
                result = client.get_local_account_limits(effective_account)
            return format_dict(
                {k: v if v is not None else "none" for k, v in result.items()}
            )
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"
