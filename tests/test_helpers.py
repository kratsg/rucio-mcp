"""Tests for shared helper functions in _helpers.py."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from prometheus_client import REGISTRY

if TYPE_CHECKING:
    from collections.abc import Callable

from rucio_mcp.auth.factory import EnvBasedClientFactory
from rucio_mcp.metrics import current_tool_labels
from rucio_mcp.tools._helpers import (
    classify_error,
    format_dict,
    format_list,
    get_rucio_client,
    get_scopes,
)


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


class TestGetScopes:
    def test_returns_none_when_key_absent(self) -> None:
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {"client_factory": MagicMock()}
        assert get_scopes(ctx) is None

    def test_returns_scopes_when_present(self) -> None:
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {
            "client_factory": MagicMock(),
            "scopes": ["scope_a", "scope_b"],
        }
        assert get_scopes(ctx) == ["scope_a", "scope_b"]

    def test_returns_none_when_explicitly_none(self) -> None:
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {
            "client_factory": MagicMock(),
            "scopes": None,
        }
        assert get_scopes(ctx) is None


class TestGetRucioClient:
    def test_returns_client_from_factory(self) -> None:
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


@pytest.fixture(autouse=False)
def tool_labels_ctx():
    """Set current_tool_labels to a unique (site, tool) for each test."""
    tok = current_tool_labels.set(("errsite", "errtool"))
    yield
    current_tool_labels.reset(tok)


def _counter_delta(site: str, tool: str, category: str, fn: Callable[[], str]) -> float:
    """Return the increment to TOOL_ERRORS after calling fn()."""
    before = (
        REGISTRY.get_sample_value(
            "rucio_mcp_tool_errors_total",
            {"site": site, "tool": tool, "category": category},
        )
        or 0.0
    )
    fn()
    after = (
        REGISTRY.get_sample_value(
            "rucio_mcp_tool_errors_total",
            {"site": site, "tool": tool, "category": category},
        )
        or 0.0
    )
    return after - before


class _DataIdentifierNotFound(Exception):
    pass


class _RSENotFound(Exception):
    pass


class _RuleNotFound(Exception):
    pass


class _DuplicateRule(Exception):
    pass


class _InsufficientAccountLimit(Exception):
    pass


class _AccessDenied(Exception):
    pass


@pytest.mark.usefixtures("tool_labels_ctx")
class TestClassifyErrorCounter:
    def test_did_not_found_category(self) -> None:
        exc = _DataIdentifierNotFound("no such DID")
        delta = _counter_delta(
            "errsite",
            "errtool",
            "did_not_found",
            lambda: classify_error(exc),
        )
        assert delta == 1.0

    def test_rse_not_found_category(self) -> None:
        exc = _RSENotFound("no such RSE")
        delta = _counter_delta(
            "errsite",
            "errtool",
            "rse_not_found",
            lambda: classify_error(exc),
        )
        assert delta == 1.0

    def test_rule_not_found_category(self) -> None:
        exc = _RuleNotFound("no such rule")
        delta = _counter_delta(
            "errsite",
            "errtool",
            "rule_not_found",
            lambda: classify_error(exc),
        )
        assert delta == 1.0

    def test_duplicate_rule_category(self) -> None:
        exc = _DuplicateRule("a matching rule already exists")
        delta = _counter_delta(
            "errsite",
            "errtool",
            "duplicate_rule",
            lambda: classify_error(exc),
        )
        assert delta == 1.0

    def test_quota_category(self) -> None:
        exc = _InsufficientAccountLimit("account limit exceeded")
        delta = _counter_delta(
            "errsite",
            "errtool",
            "quota",
            lambda: classify_error(exc),
        )
        assert delta == 1.0

    def test_access_denied_category(self) -> None:
        exc = _AccessDenied("not allowed to perform this action")
        delta = _counter_delta(
            "errsite",
            "errtool",
            "access_denied",
            lambda: classify_error(exc),
        )
        assert delta == 1.0

    def test_ssl_proxy_category_via_message(self) -> None:
        exc = Exception("certificate verify failed")
        delta = _counter_delta(
            "errsite",
            "errtool",
            "ssl_proxy",
            lambda: classify_error(exc),
        )
        assert delta == 1.0

    def test_network_category_via_message(self) -> None:
        exc = Exception("connection refused")
        delta = _counter_delta(
            "errsite",
            "errtool",
            "network",
            lambda: classify_error(exc),
        )
        assert delta == 1.0

    def test_other_category(self) -> None:
        exc = Exception("something completely unexpected")
        delta = _counter_delta(
            "errsite",
            "errtool",
            "other",
            lambda: classify_error(exc),
        )
        assert delta == 1.0

    def test_labels_come_from_contextvar(self) -> None:
        exc = _DataIdentifierNotFound("gone")
        delta = _counter_delta(
            "errsite",
            "errtool",
            "did_not_found",
            lambda: classify_error(exc),
        )
        assert delta == 1.0
