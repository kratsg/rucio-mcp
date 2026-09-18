"""Tests for the voms proxy tool."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.mcpserver import MCPServer

from rucio_mcp.tools.proxy import register

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mcp.types import CallToolResult


@pytest.fixture
def proxy_tool() -> Any:
    mcp = MCPServer("test")
    register(mcp)
    return next(
        tool for tool in mcp._tool_manager.list_tools() if tool.name == "rucio_voms_proxy_info"
    )


@pytest.fixture
def registered_tools(proxy_tool: Any) -> dict[str, Callable[..., Awaitable[CallToolResult]]]:
    return {proxy_tool.name: proxy_tool.fn}


class TestRucioVomsProxyInfoRegistration:
    def test_declares_read_only_annotations(self, proxy_tool: Any) -> None:
        assert proxy_tool.annotations is not None
        assert proxy_tool.annotations.read_only_hint is True
        assert proxy_tool.annotations.open_world_hint is True

    def test_publishes_an_output_schema(self, proxy_tool: Any) -> None:
        assert proxy_tool.output_schema is not None
        assert "output" in proxy_tool.output_schema["properties"]


class TestRucioVomsProxyInfo:
    async def test_returns_proxy_info(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        tool_text: Callable[[CallToolResult], str],
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
        output = tool_text(result)
        assert "timeleft" in output
        assert "Giordon" in output
        assert result.is_error is not True
        assert result.structured_content is not None
        assert "Giordon" in result.structured_content["output"]

    async def test_missing_binary(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        fn = registered_tools["rucio_voms_proxy_info"]
        with patch("shutil.which", return_value=None):
            result = await fn()
        assert "not found in PATH" in tool_text(result)
        assert result.is_error is True

    async def test_proxy_not_found(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        tool_text: Callable[[CallToolResult], str],
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
        assert "Proxy check failed" in tool_text(result)
        assert result.is_error is True

    async def test_timeout(
        self,
        registered_tools: dict[str, Callable[..., Awaitable[CallToolResult]]],
        tool_text: Callable[[CallToolResult], str],
    ) -> None:
        async def _hang() -> tuple[bytes, bytes]:
            await asyncio.sleep(3600)
            return b"", b""

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.communicate = _hang
        mock_proc.kill = MagicMock()

        fn = registered_tools["rucio_voms_proxy_info"]
        with (
            patch("shutil.which", return_value="/usr/bin/voms-proxy-info"),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("rucio_mcp.tools.proxy._PROXY_TIMEOUT_S", 0.01),
        ):
            result = await fn()
        assert "timed out" in tool_text(result).lower()
        assert result.is_error is True
        mock_proc.kill.assert_called_once()
