"""Tools for checking VOMS proxy certificate status."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from typing import Annotated

from mcp.server.mcpserver import MCPServer  # noqa: TC002
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel

from rucio_mcp.tools._helpers import error_result

_PROXY_TIMEOUT_S = 30.0


class RucioVomsProxyInfoResult(BaseModel):
    """Structured result of ``rucio_voms_proxy_info``."""

    output: str


def register(mcp: MCPServer) -> None:
    """Register proxy tools with the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Check VOMS proxy status",
            read_only_hint=True,
            open_world_hint=True,
        )
    )
    async def rucio_voms_proxy_info() -> Annotated[
        CallToolResult, RucioVomsProxyInfoResult
    ]:
        """Check the status of the current VOMS proxy certificate.

        Returns the proxy subject, issuer, identity, type, strength, path,
        and remaining validity time. Use this before running rucio operations
        to confirm that x509 authentication is set up correctly.

        Requires the ``voms-proxy-info`` command to be available in PATH.
        A valid proxy is created with ``voms-proxy-init -voms <site>`` with the
        appropriate VO name for your experiment.
        """
        binary = shutil.which("voms-proxy-info")
        if binary is None:
            return error_result(
                "Error: 'voms-proxy-info' not found in PATH. "
                "Install voms-clients or ensure the binary is available."
            )

        proc = await asyncio.create_subprocess_exec(
            binary,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_PROXY_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
            return error_result(
                f"Error: 'voms-proxy-info' timed out after {_PROXY_TIMEOUT_S:.0f}s. "
                "The command may be hung; check your grid environment."
            )

        if proc.returncode != 0:
            error_text = stderr.decode().strip()
            return error_result(f"Proxy check failed: {error_text}")
        output = stdout.decode().strip()
        payload = RucioVomsProxyInfoResult(output=output)
        return CallToolResult(
            content=[TextContent(type="text", text=output)],
            structured_content=payload.model_dump(mode="json"),
        )
