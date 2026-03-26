"""FastMCP server setup for rucio-mcp."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from mcp.server.fastmcp import FastMCP
from rucio.client import Client

from rucio_mcp.nomenclature import ATLAS_NOMENCLATURE
from rucio_mcp.tools import account, dids, ping, proxy, replicas, rses, rules, scopes

_INSTRUCTIONS = (
    "MCP server for ATLAS Rucio data management. "
    "Provides tools to discover datasets, check replica locations, "
    "inspect and manage replication rules, and verify proxy authentication. "
    "Authentication is configured via environment variables "
    "(RUCIO_AUTH_TYPE, RUCIO_ACCOUNT, X509_USER_PROXY, etc.) "
    "before starting the server.\n\n" + ATLAS_NOMENCLATURE
)


def _preflight_check() -> None:
    """Check environment before starting the MCP server.

    Prints clear diagnostics to stderr and exits non-zero if required
    configuration is missing, rather than letting errors surface as
    cryptic exception groups deep inside the asyncio stack.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- rucio.cfg ---
    rucio_home = os.environ.get("RUCIO_HOME")
    if rucio_home:
        cfg = Path(rucio_home) / "etc" / "rucio.cfg"
        if not cfg.exists():
            errors.append(
                f"RUCIO_HOME={rucio_home!r} is set but {cfg} does not exist.\n"
                "    Verify RUCIO_HOME points to a valid rucio-clients installation."
            )
    else:
        errors.append(
            "RUCIO_HOME is not set. Set it to the rucio-clients directory\n"
            "    that contains etc/rucio.cfg.\n"
            "    Example:\n"
            "      export RUCIO_HOME=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase"
            "/x86_64/rucio-clients/35.6.0"
        )

    # --- auth type ---
    auth_type = os.environ.get("RUCIO_AUTH_TYPE")
    if auth_type is None:
        errors.append(
            "RUCIO_AUTH_TYPE is not set. Set it to your authentication method,\n"
            "    or add 'auth_type = ...' to the [client] section of rucio.cfg.\n"
            "    Example:\n"
            "      export RUCIO_AUTH_TYPE=x509_proxy"
        )

    # --- x509 proxy specifics ---
    if auth_type == "x509_proxy":
        cert_dir = os.environ.get("X509_CERT_DIR")
        if cert_dir is None:
            warnings.append(
                "X509_CERT_DIR is not set. SSL certificate verification will fail\n"
                "    when tools try to contact the Rucio server.\n"
                "    Example:\n"
                "      export X509_CERT_DIR=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase"
                "/etc/grid-security-emi/certificates"
            )
        elif not Path(cert_dir).is_dir():
            warnings.append(
                f"X509_CERT_DIR={cert_dir!r} does not exist or is not a directory.\n"
                "    SSL certificate verification will fail."
            )

        proxy_path = os.environ.get("X509_USER_PROXY")
        if proxy_path and not Path(proxy_path).exists():
            warnings.append(
                f"X509_USER_PROXY={proxy_path!r} is set but the file does not exist.\n"
                "    Run: voms-proxy-init -voms atlas"
            )

    for w in warnings:
        sys.stderr.write(f"[rucio-mcp] WARNING: {w}\n")

    if errors:
        sys.stderr.write("[rucio-mcp] Cannot start: configuration is incomplete.\n")
        for i, e in enumerate(errors, 1):
            sys.stderr.write(f"\n  ({i}) {e}\n")
        sys.stderr.write("\n")
        sys.exit(1)


def _make_mcp(read_only: bool = False) -> FastMCP:
    """Build and return a configured FastMCP instance.

    Args:
        read_only: If True, write operations (add/delete/update rules, etc.)
            will be blocked. The lifespan context exposes this flag so each
            write tool can enforce it.
    """

    @asynccontextmanager
    async def _lifespan(_server: FastMCP) -> AsyncGenerator[dict[str, Any], None]:
        """Initialize the Rucio client for the lifetime of the MCP server.

        The client reads authentication configuration from environment variables
        and/or the rucio.cfg file automatically:
          - RUCIO_AUTH_TYPE  (e.g. x509_proxy, userpass, oidc)
          - RUCIO_ACCOUNT
          - RUCIO_HOME       (directory containing rucio.cfg)
          - X509_USER_PROXY  (path to proxy cert when RUCIO_AUTH_TYPE=x509_proxy)
        """
        client = Client()
        yield {"rucio_client": client, "read_only": read_only}

    mcp = FastMCP("rucio-mcp", lifespan=_lifespan, instructions=_INSTRUCTIONS)

    # Register tools from each module by calling their register() function.
    # Each module defines register(mcp: FastMCP) which attaches its tools to the
    # server. This pattern gives each module full control over its tools while
    # keeping server.py as the single wiring point.
    for _module in [ping, dids, replicas, scopes, rses, rules, account, proxy]:
        _module.register(mcp)

    return mcp


def serve(read_only: bool = False) -> None:
    """Start the MCP server over stdio."""
    _preflight_check()
    _make_mcp(read_only=read_only).run(transport="stdio")
