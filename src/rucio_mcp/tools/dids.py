"""Tools for Data IDentifier (DID) discovery and inspection."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer  # noqa: TC002
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel

from rucio_mcp.tools._helpers import (
    build_hints,
    classify_error,
    error_result,
    format_dict,
    format_list,
    get_rucio_client,
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


class RucioListDidsResult(BaseModel):
    """Structured result of ``rucio_list_dids``."""

    did_pattern: str
    did_type: str
    dids: list[str]
    offset: int
    limit: int
    truncated: bool


class RucioGetDidResult(BaseModel):
    """Structured result of ``rucio_get_did``."""

    scope: str | None = None
    name: str | None = None
    type: str | None = None
    bytes: int | None = None
    length: int | None = None
    account: str | None = None
    open: bool | None = None
    monotonic: bool | None = None
    created_at: str | None = None
    updated_at: str | None = None


class RucioListContentResult(BaseModel):
    """Structured result of ``rucio_list_content``."""

    did: str
    content: list[dict[str, Any]]
    offset: int
    limit: int
    truncated: bool


class RucioListFilesResult(BaseModel):
    """Structured result of ``rucio_list_files``."""

    did: str
    long: bool
    files: list[dict[str, Any]]
    offset: int
    limit: int
    truncated: bool


class RucioGetMetadataResult(BaseModel):
    """Structured result of ``rucio_get_metadata``."""

    did: str
    plugin: str
    metadata: dict[str, Any]


class RucioListParentDidsResult(BaseModel):
    """Structured result of ``rucio_list_parent_dids``."""

    did: str
    parents: list[dict[str, Any]]
    offset: int
    limit: int
    truncated: bool


def register(mcp: MCPServer) -> None:
    """Register DID tools with the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Search DIDs", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_list_dids(
        did_pattern: str,
        did_type: str = "collection",
        recursive: bool = False,
        limit: int = 50,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioListDidsResult]:
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
            return error_result(str(exc))

        client = get_rucio_client(ctx)
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
            return CallToolResult(
                content=[
                    TextContent(type="text", text="No DIDs found matching the pattern.")
                ],
                structured_content=RucioListDidsResult(
                    did_pattern=did_pattern,
                    did_type=did_type,
                    dids=[],
                    offset=offset,
                    limit=limit,
                    truncated=False,
                ).model_dump(mode="json"),
            )

        did_names = [
            f"{scope}:{r['name']}" if isinstance(r, dict) else f"{scope}:{r}"
            for r in results
        ]
        lines = "\n".join(f"- `{d}`" for d in did_names)
        hints = build_hints(
            [
                "Use `rucio_get_did <scope:name>` to inspect a specific DID",
                "Use `rucio_list_dataset_replicas <scope:name>` to find where it is stored",
                "Use `rucio_list_did_rules <scope:name>` to see replication rules",
            ]
        )
        payload = RucioListDidsResult(
            did_pattern=did_pattern,
            did_type=did_type,
            dids=did_names,
            offset=offset,
            limit=limit,
            truncated=bool(footer),
        )
        return CallToolResult(
            content=[TextContent(type="text", text=lines + footer + hints)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get DID details", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_get_did(
        did: str,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioGetDidResult]:
        """Return attributes and status for a DID.

        Shows type, bytes, length (number of files), account, open/closed
        status, and timestamps.

        Args:
            did: The data identifier in ``scope:name`` format.
        """
        try:
            scope, name = parse_did(did)
        except ValueError as exc:
            return error_result(str(exc))

        client = get_rucio_client(ctx)
        try:
            result = client.get_did(scope, name, dynamic=True)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        did_type = result.get("type", "")
        if did_type == "CONTAINER":
            hints = build_hints(
                [
                    f"Use `rucio_list_container_replicas {did}` to find where it is stored",
                    f"Use `rucio_list_did_rules {did}` to see replication rules",
                ]
            )
        elif did_type == "DATASET":
            hints = build_hints(
                [
                    f"Use `rucio_list_dataset_replicas {did}` for a summary view per RSE",
                    f"Use `rucio_list_replicas {did}` for per-file PFN details",
                    f"Use `rucio_list_did_rules {did}` to see replication rules",
                ]
            )
        else:
            hints = build_hints(
                [
                    f"Use `rucio_list_parent_dids {did}` to find parent datasets",
                    f"Use `rucio_list_replicas {did}` to find replica locations",
                ]
            )

        payload = RucioGetDidResult(**{k: result.get(k) for k in _STAT_KEYS})
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=format_dict(result, include_keys=_STAT_KEYS) + hints,
                )
            ],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List DID contents", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_list_content(
        did: str,
        limit: int = 50,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioListContentResult]:
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
            return error_result(str(exc))

        client = get_rucio_client(ctx)
        try:
            it = client.list_content(scope, name)
            page, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not page:
            return CallToolResult(
                content=[TextContent(type="text", text="No contents found.")],
                structured_content=RucioListContentResult(
                    did=did, content=[], offset=offset, limit=limit, truncated=False
                ).model_dump(mode="json"),
            )

        hints = build_hints(
            ["Use `rucio_get_did <scope:name>` to inspect any child DID"]
        )
        text = format_list(page, include_keys=_CONTENT_KEYS) + footer + hints
        payload = RucioListContentResult(
            did=did, content=page, offset=offset, limit=limit, truncated=bool(footer)
        )
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List files in a DID", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_list_files(
        did: str,
        long: bool = False,
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioListFilesResult]:
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
            return error_result(str(exc))

        client = get_rucio_client(ctx)
        try:
            it = client.list_files(scope, name, long=long)
            page, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not page:
            return CallToolResult(
                content=[TextContent(type="text", text="No files found.")],
                structured_content=RucioListFilesResult(
                    did=did,
                    long=long,
                    files=[],
                    offset=offset,
                    limit=limit,
                    truncated=False,
                ).model_dump(mode="json"),
            )

        hints = build_hints(
            [f"Use `rucio_list_replicas {did}` to find where files are stored"]
        )
        if long:
            text = format_list(page) + footer + hints
        else:
            text = (
                "\n".join(
                    f"- `{r['scope']}:{r['name']}`" for r in page if isinstance(r, dict)
                )
                + footer
                + hints
            )
        payload = RucioListFilesResult(
            did=did,
            long=long,
            files=page,
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
            title="Get DID metadata", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_get_metadata(
        did: str,
        plugin: str = "DID_COLUMN",
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioGetMetadataResult]:
        """Retrieve metadata key-value pairs for a DID.

        Args:
            did: The data identifier in ``scope:name`` format.
            plugin: Metadata plugin. ``DID_COLUMN`` (default) returns standard
                Rucio metadata. ``JSON`` returns user-defined metadata.
        """
        try:
            scope, name = parse_did(did)
        except ValueError as exc:
            return error_result(str(exc))

        client = get_rucio_client(ctx)
        try:
            result = client.get_metadata(scope, name, plugin=plugin)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [f"Use `rucio_get_did {did}` for structure and size information"]
        )
        payload = RucioGetMetadataResult(did=did, plugin=plugin, metadata=result)
        return CallToolResult(
            content=[TextContent(type="text", text=format_dict(result) + hints)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List parent DIDs", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_list_parent_dids(
        did: str,
        limit: int = 50,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioListParentDidsResult]:
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
            return error_result(str(exc))

        client = get_rucio_client(ctx)
        try:
            it = client.list_parent_dids(scope, name)
            page, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not page:
            return CallToolResult(
                content=[TextContent(type="text", text="No parent DIDs found.")],
                structured_content=RucioListParentDidsResult(
                    did=did, parents=[], offset=offset, limit=limit, truncated=False
                ).model_dump(mode="json"),
            )

        hints = build_hints(
            ["Use `rucio_get_did <scope:name>` to inspect any parent DID"]
        )
        text = format_list(page) + footer + hints
        payload = RucioListParentDidsResult(
            did=did, parents=page, offset=offset, limit=limit, truncated=bool(footer)
        )
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )
