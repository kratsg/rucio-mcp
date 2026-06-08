"""MCP resources exposing per-site documentation."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP  # noqa: TC002

from rucio_mcp.nomenclature import load_nomenclature


def register(mcp: FastMCP, site_name: str, nomenclature_resource: str | None) -> None:
    """Register documentation resources with the MCP server.

    A ``rucio://nomenclature`` resource is registered only when
    *nomenclature_resource* is not None.  The resource name includes
    *site_name* so the LLM knows which site's conventions it is reading.
    """
    if nomenclature_resource is None:
        return

    @mcp.resource(
        "rucio://nomenclature",
        name=f"{site_name.upper()} Dataset Nomenclature",
        description="Dataset naming conventions: DID format, scopes, and common data types.",
        mime_type="text/markdown",
    )
    def get_nomenclature() -> str:
        return load_nomenclature(nomenclature_resource) or ""
