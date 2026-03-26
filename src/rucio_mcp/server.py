"""FastMCP server setup for rucio-mcp."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from mcp.server.fastmcp import FastMCP
from rucio.client import Client

from rucio_mcp.nomenclature import ATLAS_NOMENCLATURE
from rucio_mcp.tools import account, dids, ping, proxy, replicas, rses, rules, scopes


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
    yield {"rucio_client": client}


mcp = FastMCP(
    "rucio-mcp",
    lifespan=_lifespan,
    instructions=(
        "MCP server for ATLAS Rucio data management. "
        "Provides tools to discover datasets, check replica locations, "
        "inspect replication rules, and verify proxy authentication. "
        "Authentication is configured via environment variables "
        "(RUCIO_AUTH_TYPE, RUCIO_ACCOUNT, X509_USER_PROXY, etc.) "
        "before starting the server.\n\n" + ATLAS_NOMENCLATURE
    ),
)

# Register tools from each module by calling their register() function.
# Each module defines register(mcp: FastMCP) which attaches its tools to the
# server. This pattern gives each module full control over its tools while
# keeping server.py as the single wiring point.
for _module in [ping, dids, replicas, scopes, rses, rules, account, proxy]:
    _module.register(mcp)


def serve() -> None:
    """Start the MCP server over stdio."""
    mcp.run(transport="stdio")
