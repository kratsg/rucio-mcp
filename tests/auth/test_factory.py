"""Tests for RucioClientFactory and EnvBasedClientFactory."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_env_factory_returns_same_client_each_call():
    from rucio_mcp.auth.factory import EnvBasedClientFactory

    pre_built = MagicMock(name="rucio_client")
    factory = EnvBasedClientFactory(client=pre_built)
    ctx = MagicMock()
    assert factory.get_client(ctx) is pre_built
    assert factory.get_client(ctx) is pre_built


def test_factory_is_abstract():
    from rucio_mcp.auth.factory import RucioClientFactory

    with pytest.raises(TypeError):
        RucioClientFactory()  # type: ignore[abstract]


def test_env_factory_close_is_noop():
    from rucio_mcp.auth.factory import EnvBasedClientFactory

    factory = EnvBasedClientFactory(client=MagicMock())
    factory.close()  # should not raise
