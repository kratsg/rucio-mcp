"""Tools for Data IDentifier (DID) discovery and inspection."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import (
    build_hints,
    classify_error,
    format_dict,
    format_list,
    paginate_iter,
    parse_did,
)

_STAT_KEYS = [
    "scope",
    "name",
    "type",
    "bytes",
    "length",
    "account",
    "open",
    "monotonic",
    "created_at",
    "updated_at",
]

_CONTENT_KEYS = ["scope", "name", "type", "bytes", "length"]


def register(mcp: FastMCP) -> None:
    """Register DID tools with the MCP server."""

    @mcp.tool()
    async def rucio_list_dids(
        did_pattern: str,
        did_type: str = "collection",
        recursive: bool = False,
        limit: int = 50,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Search for ATLAS datasets and containers matching a wildcard pattern.

        Returns a list of matching DIDs in ``scope:name`` format. For physics
        analysis, containers (dataset containers) are the typical target —
        they group all datasets from a single production campaign.

        Args:
            did_pattern: Pattern in ``scope:name_pattern`` format. Wildcards
                (``*``) are supported in the name portion.
                Examples:
                  ``mc20_13TeV:mc20_13TeV.700320.*DAOD_PHYS*``
                  ``data15_13TeV:data15_13TeV.*periodAllYear*DAOD_PHYSLITE*``
            did_type: Type filter. One of: ``all``, ``collection``,
                ``dataset``, ``container``, ``file``. Default: ``collection``.
            recursive: Whether to list DIDs recursively into containers.
            limit: Maximum number of results to return (default 50).
            offset: Number of results to skip for pagination.

        """
        try:
            scope, name = parse_did(did_pattern)
        except ValueError as exc:
            return str(exc)

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            it = client.list_dids(
                scope,
                {"name": name},
                did_type=did_type,
                recursive=recursive,
            )
            results, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return "No DIDs found matching the pattern."

        lines = "\n".join(
            f"- `{scope}:{r['name']}`" if isinstance(r, dict) else f"- `{scope}:{r}`"
            for r in results
        )
        hints = build_hints(
            [
                "Use `rucio_stat <scope:name>` to inspect a specific DID",
                "Use `rucio_list_dataset_replicas <scope:name>` to find where it is stored",
                "Use `rucio_list_rules <scope:name>` to see replication rules",
            ]
        )
        return lines + footer + hints

    @mcp.tool()
    async def rucio_stat(
        did: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Return attributes and status for a DID.

        Shows type, bytes, length (number of files), account, open/closed
        status, and timestamps.

        Args:
            did: The data identifier in ``scope:name`` format.
        """
        try:
            scope, name = parse_did(did)
        except ValueError as exc:
            return str(exc)

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            result = client.get_did(scope, name, dynamic=True)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        did_type = result.get("type", "")
        if did_type == "CONTAINER":
            hints = build_hints(
                [
                    f"Use `rucio_list_container_replicas {did}` to find where it is stored",
                    f"Use `rucio_list_rules {did}` to see replication rules",
                ]
            )
        elif did_type == "DATASET":
            hints = build_hints(
                [
                    f"Use `rucio_list_dataset_replicas {did}` for a summary view per RSE",
                    f"Use `rucio_list_file_replicas {did}` for per-file PFN details",
                    f"Use `rucio_list_rules {did}` to see replication rules",
                ]
            )
        else:
            hints = build_hints(
                [
                    f"Use `rucio_list_parent_dids {did}` to find parent datasets",
                    f"Use `rucio_list_file_replicas {did}` to find replica locations",
                ]
            )

        return format_dict(result, include_keys=_STAT_KEYS) + hints

    @mcp.tool()
    async def rucio_list_content(
        did: str,
        limit: int = 50,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List the immediate contents of a container or dataset.

        For a container, returns its child datasets. For a dataset, returns
        its constituent files.

        Args:
            did: The container or dataset in ``scope:name`` format.
            limit: Maximum number of results to return (default 50).
            offset: Number of results to skip for pagination.
        """
        try:
            scope, name = parse_did(did)
        except ValueError as exc:
            return str(exc)

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            results = list(client.list_content(scope, name))
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return "No contents found."

        page, footer = paginate_iter(iter(results), limit=limit, offset=offset)
        hints = build_hints(["Use `rucio_stat <scope:name>` to inspect any child DID"])
        return format_list(page, include_keys=_CONTENT_KEYS) + footer + hints

    @mcp.tool()
    async def rucio_list_files(
        did: str,
        long: bool = False,
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List all files contained within a DID.

        Args:
            did: The dataset or container in ``scope:name`` format.
            long: If True, include GUID, adler32 checksum, and file size.
            limit: Maximum number of files to return (default 100).
            offset: Number of files to skip for pagination.
        """
        try:
            scope, name = parse_did(did)
        except ValueError as exc:
            return str(exc)

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            results = list(client.list_files(scope, name, long=long))
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return "No files found."

        page, footer = paginate_iter(iter(results), limit=limit, offset=offset)
        hints = build_hints(
            [f"Use `rucio_list_file_replicas {did}` to find where files are stored"]
        )
        if long:
            return format_list(page) + footer + hints
        return (
            "\n".join(
                f"- `{r['scope']}:{r['name']}`" for r in page if isinstance(r, dict)
            )
            + footer
            + hints
        )

    @mcp.tool()
    async def rucio_get_metadata(
        did: str,
        plugin: str = "DID_COLUMN",
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Retrieve metadata key-value pairs for a DID.

        Args:
            did: The data identifier in ``scope:name`` format.
            plugin: Metadata plugin. ``DID_COLUMN`` (default) returns standard
                Rucio metadata. ``JSON`` returns user-defined metadata.
        """
        try:
            scope, name = parse_did(did)
        except ValueError as exc:
            return str(exc)

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            result = client.get_metadata(scope, name, plugin=plugin)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [f"Use `rucio_stat {did}` for structure and size information"]
        )
        return format_dict(result) + hints

    @mcp.tool()
    async def rucio_list_parent_dids(
        did: str,
        limit: int = 50,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List all parent DIDs (containers) that contain the given DID.

        Useful for navigating the DID hierarchy upward from a file or dataset.

        Args:
            did: The data identifier in ``scope:name`` format.
            limit: Maximum number of results to return (default 50).
            offset: Number of results to skip for pagination.
        """
        try:
            scope, name = parse_did(did)
        except ValueError as exc:
            return str(exc)

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            results = list(client.list_parent_dids(scope, name))
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return "No parent DIDs found."

        page, footer = paginate_iter(iter(results), limit=limit, offset=offset)
        hints = build_hints(["Use `rucio_stat <scope:name>` to inspect any parent DID"])
        return format_list(page) + footer + hints
