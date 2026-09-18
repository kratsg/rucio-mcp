"""Tools for listing Rucio scopes."""

from __future__ import annotations

import fnmatch
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer  # noqa: TC002
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel

from rucio_mcp.tools._helpers import (
    build_hints,
    classify_error,
    get_rucio_client,
    paginate_iter,
)


class RucioListScopesResult(BaseModel):
    """Structured result of ``rucio_list_scopes``."""

    pattern: str
    scopes: list[str]
    offset: int
    limit: int
    truncated: bool


class RucioListScopesForAccountResult(BaseModel):
    """Structured result of ``rucio_list_scopes_for_account``."""

    account: str
    pattern: str
    scopes: list[str]
    offset: int
    limit: int
    truncated: bool


def register(mcp: MCPServer) -> None:
    """Register scope tools with the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List scopes", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_list_scopes(
        pattern: str = "",
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioListScopesResult]:
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
        client = get_rucio_client(ctx)
        try:
            scopes = client.list_scopes()
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if pattern:
            scopes = [s for s in scopes if fnmatch.fnmatch(s, pattern)]

        if not scopes:
            return CallToolResult(
                content=[
                    TextContent(type="text", text="No scopes found matching the pattern.")
                ],
                structured_content=RucioListScopesResult(
                    pattern=pattern, scopes=[], offset=offset, limit=limit, truncated=False
                ).model_dump(mode="json"),
            )

        sorted_scopes = sorted(scopes)
        page, footer = paginate_iter(iter(sorted_scopes), limit=limit, offset=offset)
        hints = build_hints(
            ["Use `rucio_list_dids <scope>:*` to search for DIDs within a scope"]
        )
        text = "\n".join(f"- {s}" for s in page) + footer + hints
        payload = RucioListScopesResult(
            pattern=pattern, scopes=page, offset=offset, limit=limit, truncated=bool(footer)
        )
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List scopes for an account", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_list_scopes_for_account(
        account: str = "",
        pattern: str = "",
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioListScopesForAccountResult]:
        """List all scopes owned by a Rucio account.

        Returns the scopes that the given account is allowed to write DIDs into.
        Defaults to the authenticated account if none is specified.

        Args:
            account: Rucio account name. Defaults to the authenticated account.
            pattern: Optional wildcard pattern to filter scopes (e.g.
                ``user.*``, ``group.phys*``). Uses Unix shell-style matching.
            limit: Maximum number of scopes to return (default 100).
            offset: Number of scopes to skip for pagination.
        """
        client = get_rucio_client(ctx)
        effective_account = account or client.account
        try:
            scopes = client.list_scopes_for_account(effective_account)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if pattern:
            scopes = [s for s in scopes if fnmatch.fnmatch(s, pattern)]

        if not scopes:
            return CallToolResult(
                content=[TextContent(type="text", text="No scopes found.")],
                structured_content=RucioListScopesForAccountResult(
                    account=effective_account,
                    pattern=pattern,
                    scopes=[],
                    offset=offset,
                    limit=limit,
                    truncated=False,
                ).model_dump(mode="json"),
            )

        sorted_scopes = sorted(scopes)
        page, footer = paginate_iter(iter(sorted_scopes), limit=limit, offset=offset)
        hints = build_hints(
            ["Use `rucio_list_dids <scope>:*` to search for DIDs within a scope"]
        )
        text = "\n".join(f"- {s}" for s in page) + footer + hints
        payload = RucioListScopesForAccountResult(
            account=effective_account,
            pattern=pattern,
            scopes=page,
            offset=offset,
            limit=limit,
            truncated=bool(footer),
        )
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )
