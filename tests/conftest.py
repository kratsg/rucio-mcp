from __future__ import annotations

import os
from importlib.resources import files as _pkg_files
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from rucio_mcp.auth.factory import EnvBasedClientFactory

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(scope="session", autouse=True)
def _rucio_config_env() -> Generator[None, None, None]:
    """Set RUCIO_CONFIG to the bundled atlas preset for the test session.

    rucio.common.utils.extract_scope (used by parse_did) initialises
    ScopeExtractionAlgorithms on each call, which reads the rucio config to
    check for multi-VO / policy-package settings.  Without a config file it
    raises ConfigNotFound.  Pointing RUCIO_CONFIG at the bundled atlas.cfg
    gives it a valid [client]-only file; the config_get_bool('common',
    'multi_vo') call then raises NoSectionError, which is caught, and the
    built-in default scope-extraction algorithm is used.
    """
    cfg = Path(str(_pkg_files("rucio_mcp.data").joinpath("atlas.cfg")))
    old = os.environ.get("RUCIO_CONFIG")
    os.environ["RUCIO_CONFIG"] = str(cfg)
    yield
    if old is None:
        os.environ.pop("RUCIO_CONFIG", None)
    else:
        os.environ["RUCIO_CONFIG"] = old


@pytest.fixture
def mock_rucio_client() -> MagicMock:
    """Return a MagicMock that mimics rucio.client.Client."""
    return MagicMock()


@pytest.fixture
def mock_ctx(mock_rucio_client: MagicMock) -> MagicMock:
    """Return a mock FastMCP Context with a factory-wrapped rucio_client."""
    ctx: MagicMock = MagicMock()
    ctx.request_context.lifespan_context = {
        "client_factory": EnvBasedClientFactory(client=mock_rucio_client),
        "read_only": False,
    }
    return ctx


@pytest.fixture
def mock_ctx_readonly(mock_rucio_client: MagicMock) -> MagicMock:
    """Return a mock FastMCP Context with read_only=True."""
    ctx: MagicMock = MagicMock()
    ctx.request_context.lifespan_context = {
        "client_factory": EnvBasedClientFactory(client=mock_rucio_client),
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
