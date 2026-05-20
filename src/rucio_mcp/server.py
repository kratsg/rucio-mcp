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

from rucio_mcp.auth.factory import EnvBasedClientFactory
from rucio_mcp.auth.site_config import SiteAuthConfig
from rucio_mcp.config_paths import managed_rucio_config
from rucio_mcp.nomenclature import ATLAS_NOMENCLATURE
from rucio_mcp.resources import register as register_resources
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

    # --- rucio.cfg resolution ---
    rucio_config = os.environ.get("RUCIO_CONFIG")
    if rucio_config:
        if not Path(rucio_config).exists():
            errors.append(
                f"RUCIO_CONFIG={rucio_config!r} is set but the file does not exist.\n"
                "    Verify the path or run: rucio-mcp init atlas"
            )
    else:
        managed_cfg = managed_rucio_config()
        if managed_cfg.exists():
            os.environ["RUCIO_CONFIG"] = str(managed_cfg)
        else:
            errors.append(
                "RUCIO_CONFIG is not set and no managed config was found.\n"
                "    Run one of the following to get started:\n"
                "      rucio-mcp init atlas\n"
                "      rucio-mcp init --list\n"
                "    Or set RUCIO_CONFIG manually:\n"
                "      export RUCIO_CONFIG=/path/to/rucio.cfg"
            )

    # --- auth type --- defaults to x509_proxy
    os.environ.setdefault("RUCIO_AUTH_TYPE", "x509_proxy")
    auth_type = os.environ["RUCIO_AUTH_TYPE"]

    # --- x509 proxy specifics ---
    if auth_type == "x509_proxy":
        # Default proxy path to /tmp/x509up_u<uid> if not set
        os.environ.setdefault("X509_USER_PROXY", f"/tmp/x509up_u{os.getuid()}")

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


def ping_server() -> None:
    """Check connectivity to the Rucio server and print version/account info."""
    _preflight_check()
    client = Client()
    info = client.ping()
    who = client.whoami()
    sys.stdout.write(f"version: {info.get('version', 'unknown')}\n")
    sys.stdout.write(f"account: {who.get('account', 'unknown')}\n")
    sys.stdout.write("status: ok\n")


def _make_stdio_mcp(read_only: bool = False) -> FastMCP:
    """Build and return a configured FastMCP instance for stdio transport."""

    @asynccontextmanager
    async def _lifespan(_server: FastMCP) -> AsyncGenerator[dict[str, Any], None]:
        """Initialize the Rucio client for the lifetime of the MCP server.

        The client reads authentication configuration from environment variables
        and/or the rucio.cfg file automatically:
          - RUCIO_AUTH_TYPE  (e.g. x509_proxy, userpass, oidc)
          - RUCIO_ACCOUNT
          - RUCIO_CONFIG     (direct path to rucio.cfg)
          - X509_USER_PROXY  (path to proxy cert when RUCIO_AUTH_TYPE=x509_proxy)
        """
        factory = EnvBasedClientFactory(client=Client())
        try:
            yield {"client_factory": factory, "read_only": read_only}
        finally:
            factory.close()

    mcp = FastMCP("rucio-mcp", lifespan=_lifespan, instructions=_INSTRUCTIONS)

    # Register tools from each module by calling their register() function.
    # Each module defines register(mcp: FastMCP) which attaches its tools to the
    # server. This pattern gives each module full control over its tools while
    # keeping server.py as the single wiring point.
    for _module in [ping, dids, replicas, scopes, rses, rules, account, proxy]:
        _module.register(mcp)

    register_resources(mcp)

    return mcp


def _make_http_mcp(
    *,
    read_only: bool,
    host: str,
    port: int,
    site_cfg: SiteAuthConfig,
    resource_url: str,
    issuer_override: str,
    audiences: list[str],
    required_scopes: list[str],
) -> FastMCP:
    """Build and return a configured FastMCP instance for HTTP transport.

    Auth wiring (JWKSTokenVerifier, BearerTokenClientFactory) is added in
    Phase 5. This stub provides the correct transport parameters.
    """

    @asynccontextmanager
    async def _http_lifespan(_server: FastMCP) -> AsyncGenerator[dict[str, Any], None]:
        # Per-session client_factory is wired in Phase 4.
        yield {"read_only": read_only}

    mcp = FastMCP(
        "rucio-mcp",
        instructions=_INSTRUCTIONS,
        host=host,
        port=port,
        lifespan=_http_lifespan,
    )

    for _module in [ping, dids, replicas, scopes, rses, rules, account, proxy]:
        _module.register(mcp)

    register_resources(mcp)

    return mcp


def serve(
    read_only: bool = False,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    site: str = "atlas",
    resource_url: str | None = None,
    issuer_url: str | None = None,
    audience: list[str] | None = None,
    required_scope: list[str] | None = None,
) -> None:
    """Start the MCP server over the selected transport."""
    if transport == "stdio":
        _preflight_check()
        _make_stdio_mcp(read_only=read_only).run(transport="stdio")
        return

    # HTTP transport
    if not resource_url:
        sys.stderr.write(
            "[rucio-mcp] Error: --resource-url is required for HTTP transport.\n"
        )
        sys.exit(1)

    try:
        site_cfg = SiteAuthConfig.from_preset(site)
    except ValueError as exc:
        sys.stderr.write(f"[rucio-mcp] Error: {exc}\n")
        sys.exit(1)

    _make_http_mcp(
        read_only=read_only,
        host=host,
        port=port,
        site_cfg=site_cfg,
        resource_url=resource_url,
        issuer_override=issuer_url or site_cfg.issuer,
        audiences=audience or [site_cfg.audience],
        required_scopes=required_scope or site_cfg.required_scopes,
    ).run(transport="streamable-http")
