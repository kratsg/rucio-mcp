"""MCP resources exposing static ATLAS documentation."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP  # noqa: TC002

from rucio_mcp.nomenclature import ATLAS_NOMENCLATURE


def register(mcp: FastMCP) -> None:
    """Register documentation resources with the MCP server."""

    @mcp.resource(
        "rucio://atlas-nomenclature",
        name="ATLAS Dataset Nomenclature",
        description=(
            "ATLAS dataset naming conventions: DID format, scopes, "
            "AMI tags, and common data types."
        ),
        mime_type="text/plain",
    )
    def get_atlas_nomenclature() -> str:
        return ATLAS_NOMENCLATURE
