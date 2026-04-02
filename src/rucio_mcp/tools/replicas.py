"""Tools for querying file and dataset replica locations."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import (
    build_hints,
    classify_error,
    format_list,
    paginate_iter,
    parse_did,
)

_DATASET_REPLICA_KEYS = ["rse", "available_bytes", "available_length", "state"]
_DATASET_REPLICA_BYTE_KEYS = frozenset({"available_bytes"})


def _format_file_replicas(replicas: list[dict[str, Any]]) -> str:
    """Format list_replicas output as markdown.

    Each replica entry includes the file DID as a heading and its physical
    locations (PFNs) as a bulleted list grouped by RSE.
    """
    lines = []
    for replica in replicas:
        scope = replica.get("scope", "")
        name = replica.get("name", "")
        lines.append(f"### `{scope}:{name}`")
        pfns: dict[str, Any] = replica.get("pfns", {})
        if pfns:
            for pfn, info in pfns.items():
                rse = (
                    info.get("rse", "unknown") if isinstance(info, dict) else "unknown"
                )
                lines.append(f"- **{rse}:** `{pfn}`")
        else:
            lines.append("- *(no replicas available)*")
        lines.append("")
    return "\n".join(lines).rstrip()


def register(mcp: FastMCP) -> None:
    """Register replica tools with the MCP server."""

    @mcp.tool()
    async def rucio_list_file_replicas(
        dids: str,
        protocols: str = "",
        rse_expression: str = "",
        sort: str = "",
        all_states: bool = False,
        limit: int = 20,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List physical replica locations (PFNs) for files in a DID.

        Returns the physical file names (PFNs) for each file, grouped by RSE.
        This is the primary tool for finding where data is physically stored
        and generating access URLs for grid jobs or local downloads.

        Args:
            dids: One or more space-separated DIDs in ``scope:name`` format.
                Each DID can be a file, dataset, or container.
            protocols: Comma-separated list of protocols to return PFNs for.
                Examples: ``root``, ``https``, ``srm``, ``davs``.
                If empty, all available protocols are returned.
            rse_expression: RSE expression to filter replicas by storage site.
                Examples: ``CERN-PROD_DATADISK``,
                ``type=DISK&tier=1&country=US``.
            sort: Replica sorting strategy. One of: ``geoip``, ``random``,
                or empty string (no sorting).
            all_states: If True, include unavailable replicas as well.
            limit: Maximum number of files to return PFNs for (default 20).
            offset: Number of files to skip for pagination.
        """
        did_list = dids.split()
        parsed = []
        for did in did_list:
            try:
                scope, name = parse_did(did)
            except ValueError as exc:
                return str(exc)
            parsed.append({"scope": scope, "name": name})

        kwargs: dict[str, Any] = {"ignore_availability": not all_states}
        if protocols:
            kwargs["schemes"] = [p.strip() for p in protocols.split(",")]
        if rse_expression:
            kwargs["rse_expression"] = rse_expression
        if sort:
            kwargs["sort"] = sort

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            it = client.list_replicas(parsed, **kwargs)
            results, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return "No replicas found."

        hints = build_hints(
            ["Use `rucio_list_dataset_replicas <did>` for a summary view per RSE"]
        )
        return _format_file_replicas(results) + footer + hints

    @mcp.tool()
    async def rucio_list_dataset_replicas(
        did: str,
        deep: bool = False,
        limit: int = 50,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Show dataset-level replica availability across RSEs.

        Returns a summary of how much of the dataset is available at each
        Rucio Storage Element (RSE), including available bytes and file count.
        Use this to find which sites have the dataset before submitting jobs.

        Args:
            did: The dataset or container in ``scope:name`` format.
            deep: If True, check individual file availability rather than
                relying on the dataset-level counters (slower but accurate).
            limit: Maximum number of RSEs to return (default 50).
            offset: Number of RSEs to skip for pagination.
        """
        try:
            scope, name = parse_did(did)
        except ValueError as exc:
            return str(exc)

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            results = list(client.list_dataset_replicas(scope, name, deep=deep))
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            hints = build_hints(
                [
                    f"If {did} is a container, it may have no replicas at the container level. "
                    f"Use `rucio_list_content {did}` to find child datasets, then call "
                    f"`rucio_list_dataset_replicas <child_did>` on each one.",
                ]
            )
            return "No dataset replicas found." + hints

        page, footer = paginate_iter(iter(results), limit=limit, offset=offset)
        hints = build_hints(
            [
                f"Use `rucio_list_file_replicas {did}` for per-file PFN details",
                f"Use `rucio_list_rules {did}` to see replication rules",
                f"If results look incomplete and {did} is a container, use "
                f"`rucio_list_content {did}` to find child datasets and check their replicas individually.",
            ]
        )
        return (
            format_list(
                page,
                include_keys=_DATASET_REPLICA_KEYS,
                byte_keys=_DATASET_REPLICA_BYTE_KEYS,
            )
            + footer
            + hints
        )
