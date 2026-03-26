from __future__ import annotations

import importlib.metadata

import rucio_mcp as m


def test_version() -> None:
    assert importlib.metadata.version("rucio_mcp") == m.__version__
