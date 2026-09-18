"""Tools for querying Rucio transfer requests."""

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
)

# Full state name -> single-letter code, from rucio.db.sqla.constants
# RequestState (not importable from the rucio-clients distribution). The rucio
# server resolves each state with ``RequestState(<letter>)``, a lookup by value.
_REQUEST_STATE_CODES = {
    "QUEUED": "Q",
    "SUBMITTING": "G",
    "SUBMITTED": "S",
    "FAILED": "F",
    "DONE": "D",
    "LOST": "L",
    "NO_SOURCES": "N",
    "ONLY_TAPE_SOURCES": "O",
    "SUBMISSION_FAILED": "B",
    "MISMATCH_SCHEME": "M",
    "SUSPEND": "U",
    "WAITING": "W",
    "PREPARING": "P",
}


def _parse_states(request_states: str) -> str:
    """Map full state names to a comma-joined string of rucio letter codes.

    rucio interpolates the value straight into the query string, so a plain
    string (not a Python list) must be passed.

    Raises:
        ValueError: If a state name is not recognised.
    """
    names = request_states.replace(",", " ").split()
    codes = []
    for name in names:
        code = _REQUEST_STATE_CODES.get(name.upper())
        if code is None:
            valid = ", ".join(_REQUEST_STATE_CODES)
            msg = f"Error: unknown request state '{name}'. Valid states: {valid}."
            raise ValueError(msg)
        codes.append(code)
    return ",".join(codes)


class RucioListRequestsResult(BaseModel):
    """Structured result of ``rucio_list_requests``."""

    src_rse: str
    dst_rse: str
    requests: list[dict[str, Any]]
    offset: int
    limit: int
    truncated: bool


class RucioListRequestsHistoryResult(BaseModel):
    """Structured result of ``rucio_list_requests_history``."""

    src_rse: str
    dst_rse: str
    requests: list[dict[str, Any]]
    offset: int
    limit: int
    truncated: bool


def register(mcp: MCPServer) -> None:
    """Register transfer request tools with the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List transfer requests", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_list_requests(
        src_rse: str,
        dst_rse: str,
        request_states: str,
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioListRequestsResult]:
        """List current transfer requests between two RSEs.

        Returns in-flight transfer requests filtered by source RSE, destination
        RSE, and one or more states. Useful for monitoring active transfers.

        Args:
            src_rse: Source RSE name (e.g. ``CERN-PROD_DATADISK``).
            dst_rse: Destination RSE name (e.g. ``BNL-OSG2_DATADISK``).
            request_states: Comma- or space-separated list of states to include.
                Common values: ``SUBMITTED``, ``WAITING``, ``FAILED``, ``DONE``.
            limit: Maximum number of requests to return (default 100).
            offset: Number of requests to skip for pagination.
        """
        client = get_rucio_client(ctx)
        try:
            states = _parse_states(request_states)
        except ValueError as exc:
            return error_result(str(exc))
        try:
            it = client.list_requests(src_rse, dst_rse, states)
            results, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return CallToolResult(
                content=[TextContent(type="text", text="No requests found.")],
                structured_content=RucioListRequestsResult(
                    src_rse=src_rse,
                    dst_rse=dst_rse,
                    requests=[],
                    offset=offset,
                    limit=limit,
                    truncated=False,
                ).model_dump(mode="json"),
            )

        hints = build_hints(
            [
                f"Use `rucio_list_requests_history {src_rse} {dst_rse} DONE` to see completed transfers"
            ]
        )
        text = format_list(results) + footer + hints
        payload = RucioListRequestsResult(
            src_rse=src_rse,
            dst_rse=dst_rse,
            requests=results,
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
            title="List historical transfer requests", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_list_requests_history(
        src_rse: str,
        dst_rse: str,
        request_states: str,
        limit: int = 100,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> Annotated[CallToolResult, RucioListRequestsHistoryResult]:
        """List historical transfer requests between two RSEs.

        Returns past transfer requests. The rucio server handles offset/limit
        pagination natively for this endpoint.

        Args:
            src_rse: Source RSE name (e.g. ``CERN-PROD_DATADISK``).
            dst_rse: Destination RSE name (e.g. ``BNL-OSG2_DATADISK``).
            request_states: Comma- or space-separated list of states to include.
                Common values: ``DONE``, ``FAILED``, ``LOST``.
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip for pagination.
        """
        client = get_rucio_client(ctx)
        try:
            states = _parse_states(request_states)
        except ValueError as exc:
            return error_result(str(exc))
        try:
            it = client.list_requests_history(
                src_rse, dst_rse, states, offset=offset, limit=limit
            )
            results = list(it)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return CallToolResult(
                content=[TextContent(type="text", text="No request history found.")],
                structured_content=RucioListRequestsHistoryResult(
                    src_rse=src_rse,
                    dst_rse=dst_rse,
                    requests=[],
                    offset=offset,
                    limit=limit,
                    truncated=False,
                ).model_dump(mode="json"),
            )

        # Build a pagination footer if we received a full page (may be more)
        footer = ""
        if len(results) == limit:
            footer = (
                f"\n\n---\nShowing {limit} results (offset={offset}). "
                f"Pass offset={offset + limit} to see more."
            )

        hints = build_hints(
            [
                f"Use `rucio_list_requests {src_rse} {dst_rse} SUBMITTED` to see current transfers"
            ]
        )
        text = format_list(results) + footer + hints
        payload = RucioListRequestsHistoryResult(
            src_rse=src_rse,
            dst_rse=dst_rse,
            requests=results,
            offset=offset,
            limit=limit,
            truncated=bool(footer),
        )
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=payload.model_dump(mode="json"),
        )
