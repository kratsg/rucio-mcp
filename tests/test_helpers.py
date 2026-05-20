"""Tests for shared helper functions in _helpers.py."""

from __future__ import annotations

from unittest.mock import MagicMock

from rucio_mcp.tools._helpers import format_dict, format_list, get_rucio_client


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
        # Data rows — bytes field is humanized by default _DEFAULT_BYTE_KEYS
        assert "| CERN-PROD | 1000 B | 5 |" in result
        assert "| BNL-OSG2 | 1.95 KB | 10 |" in result

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


class TestGetRucioClient:
    def test_returns_client_from_factory(self) -> None:
        from rucio_mcp.auth.factory import EnvBasedClientFactory

        expected = MagicMock(name="rucio_client")
        factory = EnvBasedClientFactory(client=expected)
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {
            "client_factory": factory,
            "read_only": False,
        }
        assert get_rucio_client(ctx) is expected

    def test_calls_factory_get_client_with_ctx(self) -> None:
        factory = MagicMock()
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {
            "client_factory": factory,
            "read_only": False,
        }
        get_rucio_client(ctx)
        factory.get_client.assert_called_once_with(ctx)
