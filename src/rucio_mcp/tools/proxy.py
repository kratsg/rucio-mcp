"""Tools for checking VOMS proxy certificate status."""

from __future__ import annotations

import asyncio
import contextlib
import shutil

from mcp.server.fastmcp import FastMCP  # noqa: TC002

_PROXY_TIMEOUT_S = 30.0


def register(mcp: FastMCP) -> None:
    """Register proxy tools with the MCP server."""

    @mcp.tool()
    async def rucio_voms_proxy_info() -> str:
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
            return (
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
            return (
                f"Error: 'voms-proxy-info' timed out after {_PROXY_TIMEOUT_S:.0f}s. "
                "The command may be hung; check your grid environment."
            )

        if proc.returncode != 0:
            error_text = stderr.decode().strip()
            return f"Proxy check failed: {error_text}"
        return stdout.decode().strip()
