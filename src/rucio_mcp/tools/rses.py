"""Tools for querying Rucio Storage Elements (RSEs)."""

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
    paginate_iter,
)

_RSE_USAGE_KEYS = ["source", "used", "free", "total", "files"]
_RSE_USAGE_BYTE_KEYS = frozenset({"used", "free", "total"})


class RucioListRsesResult(BaseModel):
    """Structured result of ``rucio_list_rses``."""

    rse_expression: str
    rses: list[str]
    offset: int
    limit: int
    truncated: bool


class RucioListRseAttributesResult(BaseModel):
    """Structured result of ``rucio_list_rse_attributes``."""

    rse: str
    attributes: dict[str, Any]


class RucioGetRseUsageResult(BaseModel):
    """Structured result of ``rucio_get_rse_usage``."""

    rse: str
    usage: list[dict[str, Any]]


class RucioGetRseResult(BaseModel):
    """Structured result of ``rucio_get_rse``."""

    rse: str
    details: dict[str, Any]


class RucioGetRseLimitsResult(BaseModel):
    """Structured result of ``rucio_get_rse_limits``."""

    rse: str
    limits: dict[str, Any]


class RucioGetRseProtocolsResult(BaseModel):
    """Structured result of ``rucio_get_rse_protocols``."""

    rse: str
    protocols: list[dict[str, Any]]


class RucioGetDistanceResult(BaseModel):
    """Structured result of ``rucio_get_distance``."""

    source: str
    destination: str
    distances: list[dict[str, Any]]


class RucioListTransferLimitsResult(BaseModel):
    """Structured result of ``rucio_list_transfer_limits``."""

    limits: list[dict[str, Any]]
    offset: int
    limit: int
    truncated: bool


def register(mcp: MCPServer) -> None:
    """Register RSE tools with the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List RSEs", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_list_rses(
        rse_expression: str = "",
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioListRsesResult]:
        """List Rucio Storage Elements (RSEs) matching an expression.

        RSEs are the storage sites where data physically resides. Without a
        filter, all registered RSEs are returned. Use an RSE expression to
        narrow results by site, country, or type.

        Args:
            rse_expression: Boolean RSE expression for filtering.
                Examples:
                  ``CERN-PROD_DATADISK`` — a specific RSE by name
                  ``country=US&type=DISK`` — US disk sites
                  ``tier=1`` — Tier-1 sites only
            limit: Maximum number of RSEs to return (default 100).
            offset: Number of RSEs to skip for pagination.
        """
        client = get_rucio_client(ctx)
        try:
            rse_filter = rse_expression or None
            it = iter(client.list_rses(rse_expression=rse_filter))
            results, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return CallToolResult(
                content=[TextContent(type="text", text="No RSEs found.")],
                structured_content=RucioListRsesResult(
                    rse_expression=rse_expression,
                    rses=[],
                    offset=offset,
                    limit=limit,
                    truncated=False,
                ).model_dump(mode="json"),
            )

        rse_names = [r["rse"] for r in results if isinstance(r, dict)]
        lines = "\n".join(f"- `{name}`" for name in rse_names)
        hints = build_hints(
            [
                "Use `rucio_list_rse_attributes <rse>` to see RSE properties (type, tier, country)",
                "Use `rucio_get_rse_usage <rse>` to check storage capacity",
            ]
        )
        payload = RucioListRsesResult(
            rse_expression=rse_expression,
            rses=rse_names,
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
            title="List RSE attributes", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_list_rse_attributes(
        rse: str,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioListRseAttributesResult]:
        """List the attributes (key-value pairs) of a specific RSE.

        RSE attributes describe properties like type (DISK/TAPE), tier,
        country, and site-specific configuration used in RSE expressions.

        Args:
            rse: The exact RSE name (e.g. ``CERN-PROD_DATADISK``).
        """
        client = get_rucio_client(ctx)
        try:
            result = client.list_rse_attributes(rse)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [f"Use `rucio_get_rse_usage {rse}` to check storage capacity"]
        )
        payload = RucioListRseAttributesResult(rse=rse, attributes=result)
        return CallToolResult(
            content=[TextContent(type="text", text=format_dict(result) + hints)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Show RSE storage usage", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_get_rse_usage(
        rse: str,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioGetRseUsageResult]:
        """Show total, used, and free storage space for an RSE.

        Args:
            rse: The exact RSE name (e.g. ``CERN-PROD_DATADISK``).
        """
        client = get_rucio_client(ctx)
        try:
            results = list(client.get_rse_usage(rse))
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [
                f"Use `rucio_list_rse_attributes {rse}` to see RSE properties (type, tier, country)"
            ]
        )
        text = (
            format_list(
                results, include_keys=_RSE_USAGE_KEYS, byte_keys=_RSE_USAGE_BYTE_KEYS
            )
            + hints
        )
        payload = RucioGetRseUsageResult(rse=rse, usage=results)
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Show RSE details", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_get_rse(
        rse: str,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioGetRseResult]:
        """Show detailed information about a specific RSE.

        Returns RSE type, deterministic flag, volatile flag, and other
        configuration details for the named storage element.

        Args:
            rse: The exact RSE name (e.g. ``CERN-PROD_DATADISK``).
        """
        client = get_rucio_client(ctx)
        try:
            result = client.get_rse(rse)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [
                f"Use `rucio_list_rse_attributes {rse}` to see RSE properties (type, tier, country)",
                f"Use `rucio_get_rse_usage {rse}` to check storage capacity",
            ]
        )
        payload = RucioGetRseResult(rse=rse, details=result)
        return CallToolResult(
            content=[TextContent(type="text", text=format_dict(result) + hints)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Show RSE space limits", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_get_rse_limits(
        rse: str,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioGetRseLimitsResult]:
        """Show the configured space limits for an RSE.

        Returns limit entries such as ``MaxBeingDeletedFiles`` and
        ``MinFreeSpace`` set by the site administrators.

        Args:
            rse: The exact RSE name (e.g. ``CERN-PROD_DATADISK``).
        """
        client = get_rucio_client(ctx)
        try:
            # RSEClient.get_rse_limits returns a single {name: value} dict
            # despite its Iterator annotation.
            result = client.get_rse_limits(rse)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not result:
            return CallToolResult(
                content=[
                    TextContent(type="text", text="No limits configured for this RSE.")
                ],
                structured_content=RucioGetRseLimitsResult(
                    rse=rse, limits={}
                ).model_dump(mode="json"),
            )

        hints = build_hints(
            [f"Use `rucio_get_rse_usage {rse}` to check current space consumption"]
        )
        payload = RucioGetRseLimitsResult(rse=rse, limits=result)
        return CallToolResult(
            content=[TextContent(type="text", text=format_dict(result) + hints)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List RSE transfer protocols",
            read_only_hint=True,
            open_world_hint=True,
        )
    )
    async def rucio_get_rse_protocols(
        rse: str,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioGetRseProtocolsResult]:
        """List the transfer protocols supported by an RSE.

        Returns protocol details including scheme (root, https, srm), hostname,
        port, and prefix for each supported protocol.

        Args:
            rse: The exact RSE name (e.g. ``CERN-PROD_DATADISK``).
        """
        client = get_rucio_client(ctx)
        try:
            result = client.get_protocols(rse)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [f"Use `rucio_list_rse_attributes {rse}` to see RSE properties"]
        )
        # Different rucio-clients versions return either a dict wrapping a
        # "protocols" list, or a bare list of protocol dicts -- normalize
        # both shapes into a flat list for structured_content.
        if isinstance(result, dict):
            text = format_dict(result) + hints
            protocols = result.get("protocols", [])
        elif isinstance(result, list):
            text = format_list(result) + hints
            protocols = result
        else:
            text = str(result) + hints
            protocols = []
        payload = RucioGetRseProtocolsResult(rse=rse, protocols=protocols)
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Show distance between RSEs",
            read_only_hint=True,
            open_world_hint=True,
        )
    )
    async def rucio_get_distance(
        source: str,
        destination: str,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioGetDistanceResult]:
        """Show the network distance (ranking) between two RSEs.

        The distance ranking is used by Rucio's transfer scheduler to prefer
        closer RSEs when choosing a data source. Lower ranking = closer.

        Args:
            source: The source RSE name (e.g. ``CERN-PROD_DATADISK``).
            destination: The destination RSE name.
        """
        client = get_rucio_client(ctx)
        try:
            results = client.get_distance(source, destination)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"No distance information found between {source} and {destination}.",
                    )
                ],
                structured_content=RucioGetDistanceResult(
                    source=source, destination=destination, distances=[]
                ).model_dump(mode="json"),
            )

        hints = build_hints(["Use `rucio_list_rses` to find valid RSE names"])
        payload = RucioGetDistanceResult(
            source=source, destination=destination, distances=results
        )
        return CallToolResult(
            content=[TextContent(type="text", text=format_list(results) + hints)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List transfer limit policies",
            read_only_hint=True,
            open_world_hint=True,
        )
    )
    async def rucio_list_transfer_limits(
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioListTransferLimitsResult]:
        """List global transfer limit policies.

        Returns the transfer limit entries that constrain concurrent transfers
        by activity and RSE.

        Args:
            limit: Maximum number of entries to return (default 100).
            offset: Number of entries to skip for pagination.
        """
        client = get_rucio_client(ctx)
        try:
            it = client.list_transfer_limits()
            results, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return CallToolResult(
                content=[
                    TextContent(type="text", text="No transfer limits configured.")
                ],
                structured_content=RucioListTransferLimitsResult(
                    limits=[], offset=offset, limit=limit, truncated=False
                ).model_dump(mode="json"),
            )

        hints = build_hints(["Use `rucio_list_rses` to look up RSE details"])
        text = format_list(results) + footer + hints
        payload = RucioListTransferLimitsResult(
            limits=results, offset=offset, limit=limit, truncated=bool(footer)
        )
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )
