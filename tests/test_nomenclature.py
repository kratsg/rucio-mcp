"""Tests for the nomenclature loader."""

from __future__ import annotations

from rucio_mcp.nomenclature import load_nomenclature


class TestLoadNomenclature:
    def test_returns_none_for_none_resource(self) -> None:
        assert load_nomenclature(None) is None

    def test_atlas_returns_nonempty_markdown(self) -> None:
        text = load_nomenclature("nomenclature/atlas.md")
        assert text is not None
        assert len(text) > 100

    def test_atlas_contains_daod_physlite(self) -> None:
        text = load_nomenclature("nomenclature/atlas.md")
        assert text is not None
        assert "DAOD_PHYSLITE" in text

    def test_atlas_contains_scope_name_format(self) -> None:
        text = load_nomenclature("nomenclature/atlas.md")
        assert text is not None
        assert "scope:name" in text
