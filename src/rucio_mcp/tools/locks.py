"""Tools for querying Rucio dataset locks."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import (
    build_hints,
    classify_error,
    format_list,
    get_rucio_client,
    paginate_iter,
    parse_did,
    run_sync,
)

_LOCK_KEYS = ["scope", "name", "rse", "state", "account", "rule_id"]


def register(mcp: FastMCP) -> None:
    """Register dataset lock tools with the MCP server."""

    @mcp.tool()
    async def rucio_get_dataset_locks(
        did: str,
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> str:
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
            return str(exc)

        client = get_rucio_client(ctx)

        def _fetch() -> tuple[list[Any], str]:
            it = client.get_dataset_locks(scope, name)
            return paginate_iter(it, limit=limit, offset=offset)

        try:
            results, footer = await run_sync(_fetch)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return "No locks found for this dataset."

        hints = build_hints(
            [
                f"Use `rucio_list_did_rules {did}` to see the rules that created these locks",
                f"Use `rucio_list_dataset_replicas {did}` to check replica availability",
            ]
        )
        return format_list(results, include_keys=_LOCK_KEYS) + footer + hints

    @mcp.tool()
    async def rucio_get_dataset_locks_by_rse(
        rse: str,
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List all dataset locks at a specific RSE.

        Returns all datasets currently locked at the given RSE by replication
        rules. Useful for understanding what data is being protected at a site.

        Args:
            rse: The RSE name (e.g. ``CERN-PROD_DATADISK``).
            limit: Maximum number of locks to return (default 100).
            offset: Number of locks to skip for pagination.
        """
        client = get_rucio_client(ctx)

        def _fetch() -> tuple[list[Any], str]:
            it = client.get_dataset_locks_by_rse(rse)
            return paginate_iter(it, limit=limit, offset=offset)

        try:
            results, footer = await run_sync(_fetch)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return f"No locks found at {rse}."

        hints = build_hints(
            [f"Use `rucio_get_rse_usage {rse}` to check storage capacity at this RSE"]
        )
        return format_list(results, include_keys=_LOCK_KEYS) + footer + hints
