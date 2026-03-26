"""Tools for checking VOMS proxy certificate status."""

from __future__ import annotations

import asyncio
import shutil

from mcp.server.fastmcp import FastMCP  # noqa: TC002


def register(mcp: FastMCP) -> None:
    """Register proxy tools with the MCP server."""

    @mcp.tool()
    async def rucio_voms_proxy_info() -> str:
        """Check the status of the current VOMS proxy certificate.

        Returns the proxy subject, issuer, identity, type, strength, path,
        and remaining validity time. Use this before running rucio operations
        to confirm that x509 authentication is set up correctly.

        Requires the ``voms-proxy-info`` command to be available in PATH.
        A valid proxy is created with ``voms-proxy-init -voms atlas`` (or the
        appropriate VO name for your experiment).
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
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_text = stderr.decode().strip()
            return f"Proxy check failed: {error_text}"
        return stdout.decode().strip()
