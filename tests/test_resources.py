"""Tests for MCP resources."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.resources import register


@pytest.fixture
def registered_mcp() -> FastMCP:
    mcp = FastMCP("test")
    register(mcp)
    return mcp


class TestAtlasNomenclatureResource:
    async def test_resource_is_registered(self, registered_mcp: FastMCP) -> None:
        resources = await registered_mcp.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "rucio://atlas-nomenclature" in uris

    async def test_resource_returns_nomenclature_content(
        self, registered_mcp: FastMCP
    ) -> None:
        content = await registered_mcp.read_resource("rucio://atlas-nomenclature")
        text = content[0].content
        assert "scope:name" in text
        assert "DAOD_PHYS" in text
        assert "AMI" in text

    async def test_resource_mime_type_is_plain_text(
        self, registered_mcp: FastMCP
    ) -> None:
        resources = await registered_mcp.list_resources()
        resource = next(
            r for r in resources if str(r.uri) == "rucio://atlas-nomenclature"
        )
        assert resource.mimeType == "text/plain"
