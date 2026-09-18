"""Tools for querying Rucio account usage and limits."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer  # noqa: TC002
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel

from rucio_mcp.tools._helpers import (
    build_hints,
    classify_error,
    format_dict,
    format_list,
    get_rucio_client,
    human_bytes,
    paginate_iter,
)

_USAGE_KEYS = ["rse", "bytes", "bytes_limit", "bytes_remaining", "files"]
_USAGE_BYTE_KEYS = frozenset({"bytes", "bytes_limit", "bytes_remaining"})


class RucioGetLocalAccountUsageResult(BaseModel):
    """Structured result of ``rucio_get_local_account_usage``."""

    account: str
    rse: str
    hide_zero: bool
    usage: list[dict[str, Any]]
    offset: int
    limit: int
    truncated: bool


class RucioGetLocalAccountLimitsResult(BaseModel):
    """Structured result of ``rucio_get_local_account_limits``."""

    account: str
    rse_expression: str
    limits: dict[str, Any]


class RucioListAccountsResult(BaseModel):
    """Structured result of ``rucio_list_accounts``."""

    account_type: str
    identity: str
    accounts: list[dict[str, Any]]
    offset: int
    limit: int
    truncated: bool


class RucioGetAccountResult(BaseModel):
    """Structured result of ``rucio_get_account``."""

    account: str | None = None
    type: str | None = None
    status: str | None = None
    email: str | None = None
    created_at: str | None = None


class RucioListAccountRulesResult(BaseModel):
    """Structured result of ``rucio_list_account_rules``."""

    account: str
    rules: list[dict[str, Any]]
    offset: int
    limit: int
    truncated: bool


def register(mcp: MCPServer) -> None:
    """Register account tools with the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Show account storage usage",
            read_only_hint=True,
            open_world_hint=True,
        )
    )
    async def rucio_get_local_account_usage(
        account: str = "",
        rse: str = "",
        hide_zero: bool = True,
        limit: int = 50,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioGetLocalAccountUsageResult]:
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
        client = get_rucio_client(ctx)
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
            return CallToolResult(
                content=[TextContent(type="text", text="No account usage found.")],
                structured_content=RucioGetLocalAccountUsageResult(
                    account=effective_account,
                    rse=rse,
                    hide_zero=hide_zero,
                    usage=[],
                    offset=offset,
                    limit=limit,
                    truncated=False,
                ).model_dump(mode="json"),
            )

        page, footer = paginate_iter(iter(results), limit=limit, offset=offset)
        hints = build_hints(
            ["Use `rucio_get_local_account_limits` to see your full quota allocations"]
        )
        text = (
            format_list(page, include_keys=_USAGE_KEYS, byte_keys=_USAGE_BYTE_KEYS)
            + footer
            + hints
        )
        payload = RucioGetLocalAccountUsageResult(
            account=effective_account,
            rse=rse,
            hide_zero=hide_zero,
            usage=page,
            offset=offset,
            limit=limit,
            truncated=bool(footer),
        )
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Show account quota limits", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_get_local_account_limits(
        account: str = "",
        rse_expression: str = "",
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioGetLocalAccountLimitsResult]:
        """Show the storage quota limits for an account.

        Returns the byte limit set for the account at each RSE or group of RSEs
        matching the expression.

        Args:
            account: Rucio account name. Defaults to the authenticated account.
            rse_expression: RSE expression to filter limits. If empty, all
                limits are returned.
        """
        client = get_rucio_client(ctx)
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
            ["Use `rucio_get_local_account_usage` to see actual storage consumption"]
        )
        text = format_dict(rendered, byte_keys=frozenset()) + hints
        payload = RucioGetLocalAccountLimitsResult(
            account=effective_account, rse_expression=rse_expression, limits=result
        )
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List accounts", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_list_accounts(
        account_type: str = "",
        identity: str = "",
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioListAccountsResult]:
        """List Rucio accounts, optionally filtered by type or identity.

        Args:
            account_type: Filter by account type: ``USER``, ``GROUP``, or
                ``SERVICE``. If empty, all types are returned.
            identity: Filter by identity string (e.g. a DN or email).
            limit: Maximum number of accounts to return (default 100).
            offset: Number of accounts to skip for pagination.
        """
        client = get_rucio_client(ctx)
        try:
            it = client.list_accounts(
                account_type=account_type or None,
                identity=identity or None,
            )
            results, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return CallToolResult(
                content=[TextContent(type="text", text="No accounts found.")],
                structured_content=RucioListAccountsResult(
                    account_type=account_type,
                    identity=identity,
                    accounts=[],
                    offset=offset,
                    limit=limit,
                    truncated=False,
                ).model_dump(mode="json"),
            )

        hints = build_hints(
            ["Use `rucio_get_account <account>` to see details for a specific account"]
        )
        text = format_list(results) + footer + hints
        payload = RucioListAccountsResult(
            account_type=account_type,
            identity=identity,
            accounts=results,
            offset=offset,
            limit=limit,
            truncated=bool(footer),
        )
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Show account details", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_get_account(
        account: str = "",
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioGetAccountResult]:
        """Show detailed information about a Rucio account.

        Returns account type, status, email, and creation date.

        Args:
            account: Rucio account name. Defaults to the authenticated account.
        """
        client = get_rucio_client(ctx)
        effective_account = account or client.account
        try:
            result = client.get_account(effective_account)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [
                f"Use `rucio_get_local_account_usage {effective_account}` to see storage consumption",
                f"Use `rucio_list_account_rules {effective_account}` to see replication rules",
            ]
        )
        payload = RucioGetAccountResult(
            account=result.get("account"),
            type=result.get("type"),
            status=result.get("status"),
            email=result.get("email"),
            created_at=result.get("created_at"),
        )
        return CallToolResult(
            content=[TextContent(type="text", text=format_dict(result) + hints)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List account replication rules",
            read_only_hint=True,
            open_world_hint=True,
        )
    )
    async def rucio_list_account_rules(
        account: str = "",
        limit: int = 50,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioListAccountRulesResult]:
        """List all replication rules owned by an account.

        Returns rules across all DIDs for the given account. Defaults to the
        authenticated account if none is specified.

        Args:
            account: Rucio account name. Defaults to the authenticated account.
            limit: Maximum number of rules to return (default 50).
            offset: Number of rules to skip for pagination.
        """
        client = get_rucio_client(ctx)
        effective_account = account or client.account
        try:
            it = client.list_replication_rules(filters={"account": effective_account})
            results, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return CallToolResult(
                content=[TextContent(type="text", text="No replication rules found.")],
                structured_content=RucioListAccountRulesResult(
                    account=effective_account,
                    rules=[],
                    offset=offset,
                    limit=limit,
                    truncated=False,
                ).model_dump(mode="json"),
            )

        hints = build_hints(
            [
                "Use `rucio_get_replication_rule <rule_id>` to see full details of a specific rule"
            ]
        )
        text = format_list(results) + footer + hints
        payload = RucioListAccountRulesResult(
            account=effective_account,
            rules=results,
            offset=offset,
            limit=limit,
            truncated=bool(footer),
        )
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )
