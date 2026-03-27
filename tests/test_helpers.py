"""Tests for shared helper functions in _helpers.py."""

from __future__ import annotations

from rucio_mcp.tools._helpers import format_dict, format_list


class TestFormatDict:
    def test_produces_markdown_bullet_per_key(self) -> None:
        result = format_dict({"account": "gstark", "status": "ACTIVE"})
        assert "- **account:** gstark" in result
        assert "- **status:** ACTIVE" in result

    def test_skips_none_values(self) -> None:
        result = format_dict({"a": "yes", "b": None, "c": "also"})
        assert "b" not in result
        assert "- **a:** yes" in result

    def test_empty_dict_returns_empty_string(self) -> None:
        assert format_dict({}) == ""

    def test_all_none_values_returns_empty_string(self) -> None:
        assert format_dict({"x": None, "y": None}) == ""


class TestFormatList:
    def test_uniform_dicts_render_as_markdown_table(self) -> None:
        items = [
            {"rse": "CERN-PROD", "bytes": 1000, "files": 5},
            {"rse": "BNL-OSG2", "bytes": 2000, "files": 10},
        ]
        result = format_list(items)
        # Header row
        assert "| rse | bytes | files |" in result
        # Separator row
        assert "| --- | --- | --- |" in result
        # Data rows
        assert "| CERN-PROD | 1000 | 5 |" in result
        assert "| BNL-OSG2 | 2000 | 10 |" in result

    def test_dicts_with_different_keys_render_as_bullet_list(self) -> None:
        items = [
            {"a": 1, "b": 2},
            {"a": 3, "c": 4},
        ]
        result = format_list(items)
        # No table header
        assert "| a |" not in result
        # Bullet format
        assert result.startswith("- ")

    def test_non_dict_items_render_as_bullet_list(self) -> None:
        result = format_list(["scope1", "scope2"])
        assert "- scope1" in result
        assert "- scope2" in result

    def test_empty_list_returns_empty_string(self) -> None:
        assert format_list([]) == ""

    def test_single_dict_renders_as_table(self) -> None:
        result = format_list([{"key": "value"}])
        assert "| key |" in result
        assert "| value |" in result
