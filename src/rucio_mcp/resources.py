"""MCP resources exposing per-site documentation."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP  # noqa: TC002

from rucio_mcp.nomenclature import load_nomenclature


def register(mcp: FastMCP, site_name: str, nomenclature_resource: str | None) -> None:
    """Register documentation resources with the MCP server.

    A ``rucio://{site_name}/nomenclature`` resource is registered only when
    *nomenclature_resource* is not None.
    """
    if nomenclature_resource is None:
        return

    @mcp.resource(
        f"rucio://{site_name}/nomenclature",
        name=f"{site_name.upper()} Dataset Nomenclature",
        description="Dataset naming conventions: DID format, scopes, and common data types.",
        mime_type="text/markdown",
    )
    def get_nomenclature() -> str:
        return load_nomenclature(nomenclature_resource) or ""
