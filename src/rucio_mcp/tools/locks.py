"""Tools for querying Rucio dataset locks."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer  # noqa: TC002
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel

from rucio_mcp.tools._helpers import (
    build_hints,
    classify_error,
    error_result,
    format_list,
    get_rucio_client,
    paginate_iter,
    parse_did,
)

_LOCK_KEYS = ["scope", "name", "rse", "state", "account", "rule_id"]


class RucioLock(BaseModel):
    """One dataset lock, as reported by the ``rucio_get_dataset_locks*`` tools."""

    scope: str | None = None
    name: str | None = None
    rse: str | None = None
    state: str | None = None
    account: str | None = None
    rule_id: str | None = None


class RucioGetDatasetLocksResult(BaseModel):
    """Structured result of ``rucio_get_dataset_locks``."""

    did: str
    locks: list[RucioLock]
    offset: int
    limit: int
    truncated: bool


class RucioGetDatasetLocksByRseResult(BaseModel):
    """Structured result of ``rucio_get_dataset_locks_by_rse``."""

    rse: str
    locks: list[RucioLock]
    offset: int
    limit: int
    truncated: bool


def register(mcp: MCPServer) -> None:
    """Register dataset lock tools with the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List dataset locks", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_get_dataset_locks(
        did: str,
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioGetDatasetLocksResult]:
        """List all locks on a specific dataset DID.

        Locks are created by replication rules. Each lock corresponds to one
        rule protecting a copy of the dataset at a specific RSE.

        Args:
            did: The dataset in ``scope:name`` format.
            limit: Maximum number of locks to return (default 100).
            offset: Number of locks to skip for pagination.
        """
        try:
            scope, name = parse_did(did)
        except ValueError as exc:
            return error_result(str(exc))

        client = get_rucio_client(ctx)
        try:
            it = client.get_dataset_locks(scope, name)
            results, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return CallToolResult(
                content=[
                    TextContent(type="text", text="No locks found for this dataset.")
                ],
                structured_content=RucioGetDatasetLocksResult(
                    did=did, locks=[], offset=offset, limit=limit, truncated=False
                ).model_dump(mode="json"),
            )

        hints = build_hints(
            [
                f"Use `rucio_list_did_rules {did}` to see the rules that created these locks",
                f"Use `rucio_list_dataset_replicas {did}` to check replica availability",
            ]
        )
        text = format_list(results, include_keys=_LOCK_KEYS) + footer + hints
        payload = RucioGetDatasetLocksResult(
            did=did,
            locks=[RucioLock(**r) for r in results],
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
            title="List dataset locks at an RSE",
            read_only_hint=True,
            open_world_hint=True,
        )
    )
    async def rucio_get_dataset_locks_by_rse(
        rse: str,
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioGetDatasetLocksByRseResult]:
        """List all dataset locks at a specific RSE.

        Returns all datasets currently locked at the given RSE by replication
        rules. Useful for understanding what data is being protected at a site.

        Args:
            rse: The RSE name (e.g. ``CERN-PROD_DATADISK``).
            limit: Maximum number of locks to return (default 100).
            offset: Number of locks to skip for pagination.
        """
        client = get_rucio_client(ctx)
        try:
            it = client.get_dataset_locks_by_rse(rse)
            results, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return CallToolResult(
                content=[TextContent(type="text", text=f"No locks found at {rse}.")],
                structured_content=RucioGetDatasetLocksByRseResult(
                    rse=rse, locks=[], offset=offset, limit=limit, truncated=False
                ).model_dump(mode="json"),
            )

        hints = build_hints(
            [f"Use `rucio_get_rse_usage {rse}` to check storage capacity at this RSE"]
        )
        text = format_list(results, include_keys=_LOCK_KEYS) + footer + hints
        payload = RucioGetDatasetLocksByRseResult(
            rse=rse,
            locks=[RucioLock(**r) for r in results],
            offset=offset,
            limit=limit,
            truncated=bool(footer),
        )
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )
