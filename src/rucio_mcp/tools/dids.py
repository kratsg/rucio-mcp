"""Tools for Data IDentifier (DID) discovery and inspection."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.nomenclature import ATLAS_NOMENCLATURE
from rucio_mcp.tools._helpers import format_dict, format_list, parse_did


def register(mcp: FastMCP) -> None:
    """Register DID tools with the MCP server."""

    @mcp.tool()
    async def rucio_list_dids(
        did_pattern: str,
        did_type: str = "collection",
        recursive: bool = False,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        (
            """Search for ATLAS datasets and containers matching a wildcard pattern.

        Returns a newline-separated list of matching DIDs in ``scope:name``
        format. For physics analysis, containers (dataset containers) are the
        typical target — they group all datasets from a single production
        campaign.

        Args:
            did_pattern: Pattern in ``scope:name_pattern`` format. Wildcards
                (``*``) are supported in the name portion.
                Examples:
                  ``mc20_13TeV:mc20_13TeV.700320.*DAOD_PHYS*``
                  ``data15_13TeV:data15_13TeV.*periodAllYear*DAOD_PHYSLITE*``
            did_type: Type filter. One of: ``all``, ``collection``,
                ``dataset``, ``container``, ``file``. Default: ``collection``.
            recursive: Whether to list DIDs recursively into containers.

        """
            + ATLAS_NOMENCLATURE
        )
        try:
            scope, name = parse_did(did_pattern)
        except ValueError as exc:
            return str(exc)

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            results = list(
                client.list_dids(
                    scope,
                    {"name": name},
                    did_type=did_type,
                    recursive=recursive,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return f"Error listing DIDs: {exc}"

        if not results:
            return "No DIDs found matching the pattern."
        return "\n".join(
            f"{scope}:{r['name']}" if isinstance(r, dict) else f"{scope}:{r}"
            for r in results
        )

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
            return format_dict(result)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"

    @mcp.tool()
    async def rucio_list_content(
        did: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List the immediate contents of a container or dataset.

        For a container, returns its child datasets. For a dataset, returns
        its constituent files.

        Args:
            did: The container or dataset in ``scope:name`` format.
        """
        try:
            scope, name = parse_did(did)
        except ValueError as exc:
            return str(exc)

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            results = list(client.list_content(scope, name))
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"

        if not results:
            return "No contents found."
        return format_list(results)

    @mcp.tool()
    async def rucio_list_files(
        did: str,
        long: bool = False,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List all files contained within a DID.

        Args:
            did: The dataset or container in ``scope:name`` format.
            long: If True, include GUID, adler32 checksum, and file size.
        """
        try:
            scope, name = parse_did(did)
        except ValueError as exc:
            return str(exc)

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            results = list(client.list_files(scope, name, long=long))
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"

        if not results:
            return "No files found."
        if long:
            return format_list(results)
        return "\n".join(
            f"{r['scope']}:{r['name']}" for r in results if isinstance(r, dict)
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
            return format_dict(result)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"

    @mcp.tool()
    async def rucio_list_parent_dids(
        did: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List all parent DIDs (containers) that contain the given DID.

        Useful for navigating the DID hierarchy upward from a file or dataset.

        Args:
            did: The data identifier in ``scope:name`` format.
        """
        try:
            scope, name = parse_did(did)
        except ValueError as exc:
            return str(exc)

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            results = list(client.list_parent_dids(scope, name))
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"

        if not results:
            return "No parent DIDs found."
        return format_list(results)
