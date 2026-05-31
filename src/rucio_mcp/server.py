"""FastMCP server setup for rucio-mcp."""

from __future__ import annotations

import os
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from importlib.resources import files as _pkg_files
from pathlib import Path
from typing import TYPE_CHECKING, Any

import uvicorn

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl
from rucio.client import Client
from starlette.applications import Starlette
from starlette.routing import Mount

from rucio_mcp.auth.bridge_provider import RucioBridgeProvider
from rucio_mcp.auth.bridge_routes import register_bridge_routes
from rucio_mcp.auth.factory import BearerTokenClientFactory, EnvBasedClientFactory
from rucio_mcp.auth.rucio_cfg import RucioCfg
from rucio_mcp.auth.rucio_oidc_poller import RucioOidcPoller
from rucio_mcp.auth.session_cache import SessionCache
from rucio_mcp.nomenclature import ATLAS_NOMENCLATURE
from rucio_mcp.presets import PRESETS
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


def _bundled_cfg_path(site_name: str) -> Path:
    """Return the filesystem path to the bundled preset .cfg for *site_name*."""
    if site_name not in PRESETS:
        known = ", ".join(PRESETS)
        sys.stderr.write(
            f"[rucio-mcp] Error: unknown site {site_name!r}. Known sites: {known}\n"
        )
        sys.exit(1)
    resource = PRESETS[site_name].config_resource
    return Path(str(_pkg_files("rucio_mcp.data").joinpath(resource)))


def _resolve_cfg_path(site: str, rucio_cfg_override: Path | None) -> Path:
    """Resolve cfg path: explicit override > bundled preset > RUCIO_CONFIG env."""
    if rucio_cfg_override is not None:
        return rucio_cfg_override
    if site in PRESETS:
        return _bundled_cfg_path(site)
    env_cfg = os.environ.get("RUCIO_CONFIG")
    if env_cfg:
        return Path(env_cfg)
    sys.stderr.write(
        f"[rucio-mcp] Error: unknown site {site!r} and RUCIO_CONFIG is not set.\n"
        f"    Use --site <name> (available: {', '.join(PRESETS)}) "
        "or --rucio-cfg <path>.\n"
    )
    sys.exit(1)


def _preflight_check(cfg_path: Path, auth_type_override: str | None = None) -> None:
    """Validate *cfg_path* and set RUCIO_CONFIG; do auth-type-specific checks.

    Prints clear diagnostics to stderr and exits non-zero if required
    configuration is missing, rather than letting errors surface as
    cryptic exception groups deep inside the asyncio stack.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not cfg_path.exists():
        errors.append(
            f"rucio.cfg not found at {cfg_path}.\n"
            "    Use --site <name> to select a bundled preset, or\n"
            "    --rucio-cfg <path> to point at a custom config file."
        )
    else:
        os.environ["RUCIO_CONFIG"] = str(cfg_path)

    # auth type: explicit override flag > env var > x509_proxy default
    if auth_type_override:
        os.environ["RUCIO_AUTH_TYPE"] = auth_type_override
    else:
        os.environ.setdefault("RUCIO_AUTH_TYPE", "x509_proxy")
    auth_type = os.environ["RUCIO_AUTH_TYPE"]

    # x509 proxy specifics
    if auth_type == "x509_proxy":
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


def ping_server(site: str = "atlas", rucio_cfg: Path | None = None) -> None:
    """Check connectivity to the Rucio server and print version/account info."""
    cfg_path = _resolve_cfg_path(site, rucio_cfg)
    _preflight_check(cfg_path)
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

    for _module in [ping, dids, replicas, scopes, rses, rules, account, proxy]:
        _module.register(mcp)

    register_resources(mcp)
    return mcp


def _make_site_mcp(
    *,
    site_name: str,
    cfg: RucioCfg,
    resource_url: str,
    read_only: bool,
    host: str,
    port: int,
) -> FastMCP:
    """Build a single-site FastMCP for HTTP transport.

    The *resource_url* must already include the ``/site/{name}`` prefix so that
    OAuth metadata advertises the correct per-site endpoints.
    """
    poller = RucioOidcPoller(
        auth_host=cfg.auth_host,
        account=cfg.account,
        oidc_audience=cfg.oidc_audience,
        oidc_scope=cfg.oidc_scope,
        oidc_issuer=cfg.oidc_issuer,
    )
    provider = RucioBridgeProvider(poller=poller, resource_url=resource_url)
    cache = SessionCache()

    @asynccontextmanager
    async def _site_lifespan(_server: FastMCP) -> AsyncGenerator[dict[str, Any], None]:
        factory = BearerTokenClientFactory(cache=cache, cfg=cfg)
        try:
            yield {"client_factory": factory, "read_only": read_only}
        finally:
            factory.close()

    mcp = FastMCP(
        f"rucio-mcp-{site_name}",
        instructions=_INSTRUCTIONS,
        host=host,
        port=port,
        streamable_http_path="/",
        lifespan=_site_lifespan,
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(resource_url),
            resource_server_url=AnyHttpUrl(resource_url),
            client_registration_options=ClientRegistrationOptions(enabled=True),
            required_scopes=[],
        ),
    )

    register_bridge_routes(mcp, provider)
    for _module in [ping, dids, replicas, scopes, rses, rules, account, proxy]:
        _module.register(mcp)
    register_resources(mcp)
    return mcp


def _make_http_app(
    *,
    sites: list[str],
    resource_url: str,
    read_only: bool,
    host: str,
    port: int,
    rucio_cfg_overrides: dict[str, Path] | None = None,
) -> Starlette:
    """Build a parent Starlette app with one FastMCP per site under /site/{name}/."""
    site_mcps: list[tuple[str, FastMCP]] = []
    for site_name in sites:
        cfg_path = (rucio_cfg_overrides or {}).get(site_name) or _bundled_cfg_path(
            site_name
        )
        if not cfg_path.exists():
            sys.stderr.write(
                f"[rucio-mcp] Error: rucio.cfg not found at {cfg_path} for site {site_name!r}.\n"
                "    Use --rucio-cfg to point at a custom config file.\n"
            )
            sys.exit(1)
        cfg = RucioCfg.from_path(cfg_path)
        if cfg.auth_type != "oidc":
            sys.stderr.write(
                f"[rucio-mcp] Error: site {site_name!r} has auth_type={cfg.auth_type!r}. "
                "HTTP mode requires auth_type=oidc.\n"
                f"    For x509/userpass sites use stdio mode: rucio-mcp serve --site {site_name}\n"
            )
            sys.exit(1)
        site_url = resource_url.rstrip("/") + f"/site/{site_name}"
        mcp = _make_site_mcp(
            site_name=site_name,
            cfg=cfg,
            resource_url=site_url,
            read_only=read_only,
            host=host,
            port=port,
        )
        site_mcps.append((site_name, mcp))

    # Initialise session managers by calling streamable_http_app() on each.
    # The returned sub-Starletttes are mounted under /site/{name}; their own
    # lifespans are NOT run (mounted sub-apps don't get lifespan propagation),
    # so we start each session_manager explicitly from the parent lifespan below.
    sub_apps = [(name, mcp.streamable_http_app()) for name, mcp in site_mcps]

    @asynccontextmanager
    async def _combined_lifespan(_app: Starlette) -> AsyncGenerator[None, None]:
        async with AsyncExitStack() as stack:
            for _, mcp in site_mcps:
                await stack.enter_async_context(mcp.session_manager.run())
            yield

    return Starlette(
        routes=[Mount(f"/site/{name}", app=sub) for name, sub in sub_apps],
        lifespan=_combined_lifespan,
    )


def serve(
    read_only: bool = False,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    sites: list[str] | None = None,
    resource_url: str | None = None,
    rucio_cfg: Path | None = None,
    auth_type: str | None = None,
) -> None:
    """Start the MCP server over the selected transport."""
    if sites is None:
        sites = ["atlas"]

    if transport == "stdio":
        cfg_path = _resolve_cfg_path(sites[0], rucio_cfg)
        _preflight_check(cfg_path, auth_type_override=auth_type)
        _make_stdio_mcp(read_only=read_only).run(transport="stdio")
        return

    # HTTP transport
    if not resource_url:
        sys.stderr.write(
            "[rucio-mcp] Error: --resource-url is required for HTTP transport.\n"
        )
        sys.exit(1)

    cfg_overrides: dict[str, Path] = {}
    if rucio_cfg is not None and len(sites) == 1:
        cfg_overrides[sites[0]] = rucio_cfg

    app = _make_http_app(
        sites=sites,
        resource_url=resource_url,
        read_only=read_only,
        host=host,
        port=port,
        rucio_cfg_overrides=cfg_overrides or None,
    )
    uvicorn.run(app, host=host, port=port)
