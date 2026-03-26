from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_rucio_client() -> MagicMock:
    """Return a MagicMock that mimics rucio.client.Client."""
    return MagicMock()


@pytest.fixture
def mock_ctx(mock_rucio_client: MagicMock) -> MagicMock:
    """Return a mock FastMCP Context with a rucio_client in lifespan context."""
    ctx: MagicMock = MagicMock()
    ctx.request_context.lifespan_context = {
        "rucio_client": mock_rucio_client,
        "read_only": False,
    }
    return ctx


@pytest.fixture
def mock_ctx_readonly(mock_rucio_client: MagicMock) -> MagicMock:
    """Return a mock FastMCP Context with read_only=True."""
    ctx: MagicMock = MagicMock()
    ctx.request_context.lifespan_context = {
        "rucio_client": mock_rucio_client,
        "read_only": True,
    }
    return ctx


def pytest_addoption(parser: Any) -> None:
    """Add command line options for test categories."""
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )


def pytest_collection_modifyitems(config, items):
    """Skip tests based on command line options."""
    # Skip slow tests unless --runslow option is given
    if not config.getoption("--runslow"):
        skip_slow = pytest.mark.skip(reason="need --runslow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
