"""Tests for the voms proxy tool."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from rucio_mcp.tools.proxy import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@pytest.fixture
def registered_tools() -> dict[str, Callable[..., Awaitable[str]]]:
    mcp = FastMCP("test")
    register(mcp)
    return {tool.name: tool.fn for tool in mcp._tool_manager.list_tools()}


class TestRucioVomsProxyInfo:
    async def test_returns_proxy_info(
        self, registered_tools: dict[str, Callable[..., Awaitable[str]]]
    ) -> None:
        proxy_output = (
            "subject   : /DC=ch/DC=cern/CN=Giordon Stark\n"
            "timeleft  : 11:59:57\n"
            "path      : /home/kratsg/x509_u33155"
        )
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(proxy_output.encode(), b""))

        fn = registered_tools["rucio_voms_proxy_info"]
        with (
            patch("shutil.which", return_value="/usr/bin/voms-proxy-info"),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            result = await fn()
        assert "timeleft" in result
        assert "Giordon" in result

    async def test_missing_binary(
        self, registered_tools: dict[str, Callable[..., Awaitable[str]]]
    ) -> None:
        fn = registered_tools["rucio_voms_proxy_info"]
        with patch("shutil.which", return_value=None):
            result = await fn()
        assert "not found in PATH" in result

    async def test_proxy_not_found(
        self, registered_tools: dict[str, Callable[..., Awaitable[str]]]
    ) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(
            return_value=(b"", b"Proxy not found: /home/kratsg/x509_u33155")
        )
        fn = registered_tools["rucio_voms_proxy_info"]
        with (
            patch("shutil.which", return_value="/usr/bin/voms-proxy-info"),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            result = await fn()
        assert "Proxy check failed" in result
