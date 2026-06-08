"""Tests for MCP resources."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.resources import register


@pytest.fixture
def mcp_with_nomenclature() -> FastMCP:
    mcp = FastMCP("test")
    register(mcp, site_name="atlas", nomenclature_resource="nomenclature/atlas.md")
    return mcp


@pytest.fixture
def mcp_without_nomenclature() -> FastMCP:
    mcp = FastMCP("test")
    register(mcp, site_name="escape", nomenclature_resource=None)
    return mcp


class TestNomenclatureResource:
    async def test_resource_uri_is_site_qualified(
        self, mcp_with_nomenclature: FastMCP
    ) -> None:
        resources = await mcp_with_nomenclature.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "rucio://atlas/nomenclature" in uris

    async def test_resource_not_registered_when_none(
        self, mcp_without_nomenclature: FastMCP
    ) -> None:
        resources = await mcp_without_nomenclature.list_resources()
        uris = [str(r.uri) for r in resources]
        assert not any("nomenclature" in u for u in uris)

    async def test_resource_returns_nomenclature_content(
        self, mcp_with_nomenclature: FastMCP
    ) -> None:
        content = list(
            await mcp_with_nomenclature.read_resource("rucio://atlas/nomenclature")
        )
        text = content[0].content
        assert "scope:name" in text
        assert "DAOD_PHYS" in text
        assert "AMI" in text

    async def test_resource_mime_type_is_markdown(
        self, mcp_with_nomenclature: FastMCP
    ) -> None:
        resources = await mcp_with_nomenclature.list_resources()
        resource = next(
            r for r in resources if str(r.uri) == "rucio://atlas/nomenclature"
        )
        assert resource.mimeType == "text/markdown"

    async def test_resource_name_includes_site(
        self, mcp_with_nomenclature: FastMCP
    ) -> None:
        resources = await mcp_with_nomenclature.list_resources()
        resource = next(
            r for r in resources if str(r.uri) == "rucio://atlas/nomenclature"
        )
        assert "atlas" in resource.name.lower()
