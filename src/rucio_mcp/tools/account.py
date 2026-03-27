"""Tools for querying Rucio account usage and limits."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import (
    build_hints,
    classify_error,
    format_dict,
    format_list,
    human_bytes,
    paginate_iter,
)

_USAGE_KEYS = ["rse", "bytes", "bytes_limit", "bytes_remaining", "files"]
_USAGE_BYTE_KEYS = frozenset({"bytes", "bytes_limit", "bytes_remaining"})


def register(mcp: FastMCP) -> None:
    """Register account tools with the MCP server."""

    @mcp.tool()
    async def rucio_list_account_usage(
        account: str = "",
        rse: str = "",
        hide_zero: bool = True,
        limit: int = 50,
        offset: int = 0,
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
            hide_zero: If True (default), hide RSEs with zero bytes and zero
                files — most accounts have limits set at many RSEs but only
                use a few.
            limit: Maximum number of RSEs to return (default 50).
            offset: Number of RSEs to skip for pagination.
        """
        client = ctx.request_context.lifespan_context["rucio_client"]
        effective_account = account or client.account
        try:
            rse_filter = rse or None
            results = list(
                client.get_local_account_usage(effective_account, rse=rse_filter)
            )
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if hide_zero:
            results = [
                r
                for r in results
                if (r.get("bytes") or 0) != 0 or (r.get("files") or 0) != 0
            ]

        if not results:
            return "No account usage found."

        page, footer = paginate_iter(iter(results), limit=limit, offset=offset)
        hints = build_hints(
            ["Use `rucio_list_account_limits` to see your full quota allocations"]
        )
        return (
            format_list(page, include_keys=_USAGE_KEYS, byte_keys=_USAGE_BYTE_KEYS)
            + footer
            + hints
        )

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
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        # Humanize byte values; render None as "none"
        rendered = {}
        for k, v in result.items():
            if v is None:
                rendered[k] = "none"
            elif isinstance(v, (int, float)):
                rendered[k] = human_bytes(v)
            else:
                rendered[k] = v

        hints = build_hints(
            ["Use `rucio_list_account_usage` to see actual storage consumption"]
        )
        return format_dict(rendered, byte_keys=frozenset()) + hints
