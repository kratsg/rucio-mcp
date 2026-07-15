"""FastMCP server setup for rucio-mcp."""

from __future__ import annotations

import configparser
import json
import os
import sys
import time
from contextlib import AsyncExitStack, asynccontextmanager
from importlib.metadata import version as _pkg_version
from importlib.resources import files as _pkg_files
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

import uvicorn

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, MutableMapping

    from starlette.requests import Request
    from starlette.types import ASGIApp

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl
from rucio.client import Client
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse, Response
from starlette.routing import BaseRoute, Mount, Route

from rucio_mcp.auth.bridge_provider import RucioBridgeProvider, _authorize_redirect_uri
from rucio_mcp.auth.bridge_routes import register_bridge_routes
from rucio_mcp.auth.factory import BearerTokenClientFactory, EnvBasedClientFactory
from rucio_mcp.auth.rucio_cfg import RucioCfg
from rucio_mcp.auth.rucio_oidc_poller import RucioOidcPoller
from rucio_mcp.auth.session_cache import SessionCache
from rucio_mcp.auth.shared_secret import SharedSecretVerifier
from rucio_mcp.landing import make_landing_html
from rucio_mcp.metrics import (
    TOOL_CALL_DURATION,
    TOOL_CALLS,
    PrometheusMiddleware,
    current_tool_labels,
    start_metrics_server,
)
from rucio_mcp.presets import PRESETS, Preset
from rucio_mcp.resources import register as register_resources
from rucio_mcp.tools import (
    account,
    dids,
    locks,
    ping,
    proxy,
    replicas,
    rses,
    rucio_requests,
    rules,
    scopes,
    subscriptions,
)

_STDIO_PREAMBLE = (
    "MCP server for Rucio data management. "
    "Provides tools to discover datasets, check replica locations, "
    "inspect and manage replication rules, and verify proxy authentication. "
    "Authentication is configured via environment variables "
    "(RUCIO_AUTH_TYPE, RUCIO_ACCOUNT, X509_USER_PROXY, etc.) "
    "before starting the server."
)

_HTTP_PREAMBLE = (
    "MCP server for Rucio data management. "
    "Provides tools to discover datasets, check replica locations, "
    "inspect and manage replication rules, and verify authentication. "
    "Authentication uses OIDC via the OAuth 2.1 bridge — no environment "
    "variables or proxy certificates are required. "
    "Use `rucio_token_info` to check how long the current session remains valid."
)

_NOMENCLATURE_HINT = (
    "Dataset naming conventions for this site are available "
    "via the `rucio://nomenclature` resource."
)


def _build_instructions(preset: Preset, *, transport: str = "stdio") -> str:
    """Build the server instructions string for *preset* and *transport*."""
    preamble = _HTTP_PREAMBLE if transport == "http" else _STDIO_PREAMBLE
    if preset.nomenclature_resource is not None:
        return preamble + "\n\n" + _NOMENCLATURE_HINT
    return preamble


class _InstrumentedFastMCP(FastMCP):
    """FastMCP subclass that records per-tool call count and duration."""

    def __init__(self, *args: Any, site_name: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._site_name = site_name

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        TOOL_CALLS.labels(site=self._site_name, tool=name).inc()
        current_tool_labels.set((self._site_name, name))
        t0 = time.perf_counter()
        try:
            return await super().call_tool(name, arguments)
        finally:
            TOOL_CALL_DURATION.labels(site=self._site_name, tool=name).observe(
                time.perf_counter() - t0
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

    # auth type: explicit override flag > existing env var > cfg file > x509_proxy default
    # 'x509' is a user-friendly alias for 'x509_proxy' (VOMS proxy auth).
    if auth_type_override:
        os.environ["RUCIO_AUTH_TYPE"] = (
            "x509_proxy" if auth_type_override == "x509" else auth_type_override
        )
    elif "RUCIO_AUTH_TYPE" not in os.environ:
        # Bundled presets omit auth_type; default to oidc so users don't need --auth-type.
        cp = configparser.ConfigParser()
        cp.read(cfg_path)
        os.environ["RUCIO_AUTH_TYPE"] = cp.get("client", "auth_type", fallback="oidc")
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
                "    Run: voms-proxy-init -voms <site>"
            )

    elif auth_type == "x509":
        # Bare cert auth (not VOMS proxy): default cert/key to standard globus locations.
        os.environ.setdefault(
            "RUCIO_CLIENT_CERT", str(Path("~/.globus/usercert.pem").expanduser())
        )
        os.environ.setdefault(
            "RUCIO_CLIENT_KEY", str(Path("~/.globus/userkey.pem").expanduser())
        )

        cert_path = os.environ.get("RUCIO_CLIENT_CERT")
        if cert_path and not Path(cert_path).exists():
            warnings.append(
                f"RUCIO_CLIENT_CERT={cert_path!r} is set but the file does not exist.\n"
                "    Provide a valid certificate at that path or set RUCIO_CLIENT_CERT."
            )

        key_path = os.environ.get("RUCIO_CLIENT_KEY")
        if key_path and not Path(key_path).exists():
            warnings.append(
                f"RUCIO_CLIENT_KEY={key_path!r} is set but the file does not exist.\n"
                "    Provide a valid key at that path or set RUCIO_CLIENT_KEY."
            )

    for w in warnings:
        sys.stderr.write(f"[rucio-mcp] WARNING: {w}\n")

    if errors:
        sys.stderr.write("[rucio-mcp] Cannot start: configuration is incomplete.\n")
        for i, e in enumerate(errors, 1):
            sys.stderr.write(f"\n  ({i}) {e}\n")
        sys.stderr.write("\n")
        sys.exit(1)


def ping_server(site: str = "escape", rucio_cfg: Path | None = None) -> None:
    """Check connectivity to the Rucio server and print version/account info."""
    cfg_path = _resolve_cfg_path(site, rucio_cfg)
    _preflight_check(cfg_path)
    client = Client()
    info = client.ping()
    who = client.whoami()
    sys.stdout.write(f"version: {info.get('version', 'unknown')}\n")
    sys.stdout.write(f"account: {who.get('account', 'unknown')}\n")
    sys.stdout.write("status: ok\n")


def _make_stdio_mcp(
    read_only: bool = False, site_name: str = "escape"
) -> _InstrumentedFastMCP:
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
        client = Client()
        try:
            scope_list: list[str] | None = list(client.list_scopes())
        except Exception:  # noqa: BLE001
            sys.stderr.write(
                "warning: could not pre-fetch scopes; scope extraction will use"
                " site defaults\n"
            )
            scope_list = None
        factory = EnvBasedClientFactory(client=client)
        try:
            yield {
                "client_factory": factory,
                "read_only": read_only,
                "scopes": scope_list,
            }
        finally:
            factory.close()

    preset = PRESETS.get(site_name, PRESETS["escape"])
    mcp = _InstrumentedFastMCP(
        "rucio-mcp",
        site_name=site_name,
        lifespan=_lifespan,
        instructions=_build_instructions(preset, transport="stdio"),
    )

    for _module in [
        dids,
        replicas,
        scopes,
        rses,
        rules,
        account,
        proxy,
        locks,
        rucio_requests,
        subscriptions,
    ]:
        _module.register(mcp)
    ping.register(mcp, transport="stdio")

    register_resources(mcp, site_name, preset.nomenclature_resource)
    return mcp


def _make_site_mcp(
    *,
    site_name: str,
    cfg: RucioCfg,
    resource_url: str,
    read_only: bool,
    host: str,
    port: int,
    poll_timeout: float = 180.0,
) -> tuple[FastMCP, RucioBridgeProvider, SessionCache]:
    """Build a single-site FastMCP for HTTP transport.

    The *resource_url* must already include the ``/site/{name}`` prefix so that
    OAuth metadata advertises the correct per-site endpoints.

    Returns ``(mcp, provider, cache)`` so callers can register the session store
    and client cache with the metrics collector.
    """
    poller = RucioOidcPoller(
        auth_host=cfg.auth_host,
        account=cfg.account,
        oidc_audience=cfg.oidc_audience,
        oidc_scope=cfg.oidc_scope,
        oidc_issuer=cfg.oidc_issuer,
    )
    provider = RucioBridgeProvider(
        poller=poller,
        resource_url=resource_url,
        poll_timeout=poll_timeout,
        site_name=site_name,
    )
    cache = SessionCache()

    @asynccontextmanager
    async def _site_lifespan(_server: FastMCP) -> AsyncGenerator[dict[str, Any], None]:
        factory = BearerTokenClientFactory(cache=cache, cfg=cfg)
        try:
            yield {"client_factory": factory, "read_only": read_only, "scopes": None}
        finally:
            factory.close()

    preset = PRESETS.get(site_name, PRESETS["escape"])
    mcp = _InstrumentedFastMCP(
        f"rucio-mcp-{site_name}",
        site_name=site_name,
        instructions=_build_instructions(preset, transport="http"),
        host=host,
        port=port,
        streamable_http_path="/",
        lifespan=_site_lifespan,
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(resource_url),
            resource_server_url=AnyHttpUrl(resource_url),
            # DCR disabled: this server authenticates clients via CIMD (Client ID
            # Metadata Documents) only — no /register endpoint, no per-client
            # registry.  See https://github.com/kratsg/rucio-mcp/issues/33.
            client_registration_options=ClientRegistrationOptions(enabled=False),
            required_scopes=[],
        ),
    )

    register_bridge_routes(mcp, provider)
    for _module in [
        dids,
        replicas,
        scopes,
        rses,
        rules,
        account,
        locks,
        rucio_requests,
        subscriptions,
    ]:
        _module.register(mcp)
    ping.register(mcp, transport="http")
    register_resources(mcp, site_name, preset.nomenclature_resource)
    return mcp, provider, cache


def _make_shared_secret_mcp(
    *,
    site_name: str,
    read_only: bool,
    resource_url: str,
    secret: str,
    host: str,
    port: int,
) -> _InstrumentedFastMCP:
    """Build a single-site FastMCP for HTTP transport gated by a static bearer.

    Serves one pre-authenticated rucio client built from env vars (exactly like
    stdio, e.g. an x509 proxy instance), behind a server-wide shared secret
    enforced by ``SharedSecretVerifier``.  No OAuth bridge, OIDC poller, or
    per-session client cache is involved — every request shares the one client.
    """

    @asynccontextmanager
    async def _lifespan(_server: FastMCP) -> AsyncGenerator[dict[str, Any], None]:
        client = Client()
        try:
            scope_list: list[str] | None = list(client.list_scopes())
        except Exception:  # noqa: BLE001
            sys.stderr.write(
                "warning: could not pre-fetch scopes; scope extraction will use"
                " site defaults\n"
            )
            scope_list = None
        factory = EnvBasedClientFactory(client=client)
        try:
            yield {
                "client_factory": factory,
                "read_only": read_only,
                "scopes": scope_list,
            }
        finally:
            factory.close()

    preset = PRESETS.get(site_name, PRESETS["escape"])
    mcp = _InstrumentedFastMCP(
        f"rucio-mcp-{site_name}",
        site_name=site_name,
        # The backend auth model is env-based (like stdio), not the OIDC bridge,
        # so use the stdio instructions/tool set; the bearer is a static gate,
        # not a decodable session token (no rucio_token_info tool).
        instructions=_build_instructions(preset, transport="stdio"),
        host=host,
        port=port,
        streamable_http_path="/",
        lifespan=_lifespan,
        token_verifier=SharedSecretVerifier(secret),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(resource_url),
            # No OAuth authorization server backs this resource; clients present
            # the static bearer out-of-band, so do not advertise a (non-existent)
            # protected-resource discovery chain.
            resource_server_url=None,
            client_registration_options=ClientRegistrationOptions(enabled=False),
            required_scopes=[],
        ),
    )

    for _module in [
        dids,
        replicas,
        scopes,
        rses,
        rules,
        account,
        proxy,
        locks,
        rucio_requests,
        subscriptions,
    ]:
        _module.register(mcp)
    ping.register(mcp, transport="stdio")
    register_resources(mcp, site_name, preset.nomenclature_resource)
    return mcp


def _make_shared_secret_app(
    *,
    site_name: str,
    resource_url: str,
    read_only: bool,
    secret: str,
    host: str,
    port: int,
) -> Starlette:
    """Build a single-site Starlette app for shared-secret HTTP transport.

    Mounts the FastMCP streamable app under ``/site/{name}/`` (parity with OIDC
    deployments) plus ``/healthz`` and a ``/`` landing page.  No OAuth metadata,
    bridge routes, or CIMD middleware — the only auth is the static bearer.
    """
    mcp = _make_shared_secret_mcp(
        site_name=site_name,
        read_only=read_only,
        resource_url=resource_url.rstrip("/") + f"/site/{site_name}",
        secret=secret,
        host=host,
        port=port,
    )
    sub_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def _combined_lifespan(_app: Starlette) -> AsyncGenerator[None, None]:
        # Mounted sub-apps don't get lifespan propagation, so start the
        # session_manager explicitly from the parent lifespan.
        async with mcp.session_manager.run():
            yield

    _version = _pkg_version("rucio-mcp")

    async def root_handler(request: Request) -> Response:
        html = make_landing_html(
            sites=request.app.state.sites,
            resource_url=request.app.state.resource_url,
            version=_version,
            read_only=request.app.state.read_only,
        )
        return Response(html, media_type="text/html")

    async def healthz_handler(_request: Request) -> Response:
        return PlainTextResponse("ok")

    routes: list[BaseRoute] = [
        Mount(f"/site/{site_name}", app=sub_app),
        Route("/healthz", endpoint=healthz_handler, methods=["GET"]),
        Route("/", endpoint=root_handler, methods=["GET"]),
    ]
    site_prefixes = frozenset({f"/site/{site_name}"})
    app = Starlette(
        routes=routes,
        lifespan=_combined_lifespan,
        middleware=[
            Middleware(_SitePathNormalizerMiddleware, site_prefixes=site_prefixes),
            Middleware(
                PrometheusMiddleware,
                filter_unhandled_paths=True,
                excluded_paths=frozenset({"/healthz"}),
                site_names=frozenset({site_name}),
            ),
        ],
    )
    # See _make_http_app: prevent 307 slash redirects that loop behind nginx.
    app.router.redirect_slashes = False
    app.state.sites = [site_name]
    app.state.resource_url = resource_url
    app.state.read_only = read_only
    return app


def _augment_as_metadata(body: bytes) -> bytes:
    """Add CIMD advertisement to the SDK's AS metadata JSON.

    The mcp SDK's ``build_metadata`` does not emit
    ``client_id_metadata_document_supported`` and hard-codes
    ``token_endpoint_auth_methods_supported`` without ``"none"``.  Claude selects
    CIMD only when both are present (the CIMD client authenticates as a public
    client — PKCE only, no secret), so we patch them in here.  See
    https://github.com/kratsg/rucio-mcp/issues/33.
    """
    try:
        meta = json.loads(body)
    except ValueError:
        return body
    meta["client_id_metadata_document_supported"] = True
    methods = meta.get("token_endpoint_auth_methods_supported") or []
    if "none" not in methods:
        meta["token_endpoint_auth_methods_supported"] = ["none", *methods]
    return json.dumps(meta).encode()


class _CimdMetadataMiddleware:
    """Rewrite the AS metadata response to advertise CIMD support.

    Wraps each per-site sub-app so that both the directly-mounted location
    (``/site/{name}/.well-known/oauth-authorization-server``) and the RFC 8414
    proxied location return the same CIMD-augmented document.  Buffers the
    response body to recompute Content-Length after the rewrite.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        path = scope.get("path", "")
        if scope.get("type") != "http" or not path.endswith(
            "/.well-known/oauth-authorization-server"
        ):
            await self._app(scope, receive, send)
            return

        start_message: dict[str, Any] = {}
        body_chunks: list[bytes] = []

        async def _buffer(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                start_message.update(message)
            elif message["type"] == "http.response.body":
                body_chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                body = b"".join(body_chunks)
                if start_message.get("status") == 200:
                    body = _augment_as_metadata(body)
                headers = [
                    (k, v)
                    for k, v in start_message.get("headers", [])
                    if k.lower() != b"content-length"
                ]
                headers.append((b"content-length", str(len(body)).encode()))
                await send({**start_message, "headers": headers})
                await send(
                    {"type": "http.response.body", "body": body, "more_body": False}
                )

        await self._app(scope, receive, _buffer)


def _make_well_known_proxy_route(
    parent_path: str,
    sub_app: ASGIApp,
    sub_app_path: str,
    methods: list[str] | None = None,
) -> Route:
    """Return a Route at *parent_path* that ASGI-proxies to *sub_app_path* in *sub_app*.

    Used to bridge the path-prefix gap between what the mcp library registers
    inside the mounted sub-app and what RFC-compliant clients expect:

    - RFC 8414 §3: client looks for AS metadata at ``/.well-known/oauth-authorization-server/site/name``;
      mcp registers it at ``/.well-known/oauth-authorization-server`` in the sub-app.
    - RFC 9728: client looks for ``/.well-known/oauth-protected-resource/site/name``;
      mcp registers it at ``/.well-known/oauth-protected-resource/site/name`` in the sub-app.

    The AS metadata served through *sub_app* is CIMD-augmented by
    ``_CimdMetadataMiddleware`` (which wraps each sub-app), so the proxied
    document matches the directly-mounted one.
    """
    _raw = sub_app_path.encode()
    _methods = methods or ["GET"]

    async def handler(request: Request) -> Response:
        body = b"" if request.method in ("GET", "HEAD") else await request.body()
        scope: dict[str, Any] = {
            **request.scope,
            "path": sub_app_path,
            "raw_path": _raw,
            # query_string preserved from scope so /authorize params pass through
        }
        scope.pop("path_params", None)

        status: list[int] = []
        resp_headers: list[tuple[bytes, bytes]] = []
        chunks: list[bytes] = []

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status.append(message["status"])
                resp_headers.extend(message.get("headers", []))
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        await sub_app(scope, receive, send)
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in resp_headers}
        return Response(
            b"".join(chunks),
            status_code=status[0] if status else 500,
            headers=headers,
        )

    return Route(parent_path, endpoint=handler, methods=_methods)


class _AuthorizeContextMiddleware:
    """ASGI middleware that exposes the /authorize redirect_uri to the provider.

    Wraps each per-site sub-app (after ``streamable_http_app()`` is called).
    For every ``/authorize`` request it extracts the ``redirect_uri`` query
    parameter and stores it in the ``_authorize_redirect_uri`` contextvar for
    the lifetime of that request.

    ``RucioBridgeProvider._resolve_cimd()`` reads this contextvar so that a
    CIMD client's ephemeral-port loopback ``redirect_uri`` can be matched
    port-agnostically against its Client ID Metadata Document.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        # Starlette 1.x Mounts do not strip the prefix — inner apps see the full
        # path (e.g. /site/atlas/authorize), so match with endswith not ==.
        if scope.get("type") == "http" and scope.get("path", "").endswith("/authorize"):
            qs = parse_qs(scope.get("query_string", b"").decode())
            redirect_uris = qs.get("redirect_uri", [])
            if redirect_uris:
                token = _authorize_redirect_uri.set(redirect_uris[0])
                try:
                    await self._app(scope, receive, send)
                finally:
                    _authorize_redirect_uri.reset(token)
                return
        await self._app(scope, receive, send)


class _SitePathNormalizerMiddleware:
    """Append a trailing slash to bare /site/{name} paths before routing.

    Starlette's Mount matches /site/{name} exactly but passes an empty path to
    the sub-app, so FastMCP's route at "/" returns 404. Converting to
    /site/{name}/ lets the Mount strip the prefix cleanly and call the sub-app
    at "/". Doing it here avoids response buffering (SSE streaming works), and
    avoids Starlette's redirect_slashes which would cause an nginx ingress
    infinite-redirect loop.
    """

    def __init__(self, app: Any, *, site_prefixes: frozenset[str]) -> None:
        self._app = app
        self._site_prefixes = site_prefixes

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope.get("path") in self._site_prefixes:
            scope = {
                **scope,
                "path": scope["path"] + "/",
                "raw_path": scope["raw_path"] + b"/",
            }
        await self._app(scope, receive, send)


def _make_http_app(
    *,
    sites: list[str],
    resource_url: str,
    read_only: bool,
    host: str,
    port: int,
    rucio_cfg_overrides: dict[str, Path] | None = None,
    poll_timeout: float = 180.0,
) -> Starlette:
    """Build a parent Starlette app with one FastMCP per site under /site/{name}/."""
    site_mcps: list[tuple[str, FastMCP]] = []
    bridge_stores: dict[str, Any] = {}
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
        mcp, provider, cache = _make_site_mcp(
            site_name=site_name,
            cfg=cfg,
            resource_url=site_url,
            read_only=read_only,
            host=host,
            port=port,
            poll_timeout=poll_timeout,
        )
        site_mcps.append((site_name, mcp))
        bridge_stores[site_name] = (provider.store, cache)

    # Initialise session managers by calling streamable_http_app() on each.
    # The returned sub-Starletttes are mounted under /site/{name}; their own
    # lifespans are NOT run (mounted sub-apps don't get lifespan propagation),
    # so we start each session_manager explicitly from the parent lifespan below.
    # Each sub-app is wrapped with:
    #   • _CimdMetadataMiddleware — advertise CIMD in the AS metadata, and
    #   • _AuthorizeContextMiddleware — expose the /authorize redirect_uri to
    #     RucioBridgeProvider.get_client() for CIMD redirect matching.
    sub_apps = [
        (
            name,
            _CimdMetadataMiddleware(
                _AuthorizeContextMiddleware(mcp.streamable_http_app())
            ),
        )
        for name, mcp in site_mcps
    ]

    @asynccontextmanager
    async def _combined_lifespan(_app: Starlette) -> AsyncGenerator[None, None]:
        async with AsyncExitStack() as stack:
            for _, mcp in site_mcps:
                await stack.enter_async_context(mcp.session_manager.run())
            yield

    routes: list[BaseRoute] = [
        Mount(f"/site/{name}", app=sub) for name, sub in sub_apps
    ]
    # RFC 8414 §3: AS metadata at /.well-known/oauth-authorization-server/site/{name}
    # RFC 9728: protected resource metadata at /.well-known/oauth-protected-resource/site/{name}
    for name, sub in sub_apps:
        routes.append(
            _make_well_known_proxy_route(
                f"/.well-known/oauth-authorization-server/site/{name}",
                sub,
                "/.well-known/oauth-authorization-server",
            )
        )
        routes.append(
            _make_well_known_proxy_route(
                f"/.well-known/oauth-protected-resource/site/{name}",
                sub,
                f"/.well-known/oauth-protected-resource/site/{name}",
            )
        )
    # No root-level OAuth fallback. RFC 8414 §3.1: when every issuer has a path
    # component (e.g. http://host/site/escape), there is no host-level issuer and
    # the bare-root /.well-known/oauth-authorization-server MUST NOT be served.
    # A root document claiming issuer=…/site/<first> is a self-contradiction (a
    # no-path location advertising a path-ful issuer) that causes non-path-aware
    # clients to register at the first site's provider and then authorize at a
    # different site's provider, yielding "Client ID not found".
    # All clients must use the path-aware per-site discovery chain:
    #   401 → /.well-known/oauth-protected-resource/site/{name}
    #       → authorization_servers: ["…/site/{name}"]
    #       → /.well-known/oauth-authorization-server/site/{name}
    #       → /site/{name}/{register,authorize,token}
    _version = _pkg_version("rucio-mcp")

    async def root_handler(request: Request) -> Response:
        html = make_landing_html(
            sites=request.app.state.sites,
            resource_url=request.app.state.resource_url,
            version=_version,
            read_only=request.app.state.read_only,
        )
        return Response(html, media_type="text/html")

    async def healthz_handler(_request: Request) -> Response:
        return PlainTextResponse("ok")

    routes.append(Route("/healthz", endpoint=healthz_handler, methods=["GET"]))
    routes.append(Route("/", endpoint=root_handler, methods=["GET"]))
    site_prefixes = frozenset(f"/site/{name}" for name in sites)
    app = Starlette(
        routes=routes,
        lifespan=_combined_lifespan,
        middleware=[
            Middleware(_SitePathNormalizerMiddleware, site_prefixes=site_prefixes),
            Middleware(
                PrometheusMiddleware,
                filter_unhandled_paths=True,
                excluded_paths=frozenset({"/healthz"}),
                site_names=frozenset(sites),
            ),
        ],
    )
    # Prevent 307 redirects for /site/{name} → /site/{name}/. Without this,
    # nginx ingresses that strip trailing slashes cause an infinite redirect
    # loop: Starlette redirects POST /site/escape → /site/escape/, nginx strips
    # the slash, pod sees /site/escape again → repeat forever.
    app.router.redirect_slashes = False
    app.state.bridge_stores = bridge_stores
    app.state.sites = sites
    app.state.resource_url = resource_url
    app.state.read_only = read_only
    return app


def serve(
    read_only: bool = False,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    metrics_port: int = 9001,
    sites: list[str] | None = None,
    resource_url: str | None = None,
    shared_secret: str | None = None,
    rucio_cfg: Path | None = None,
    auth_type: str | None = None,
    poll_timeout: float = 180.0,
    forwarded_allow_ips: str = "127.0.0.1",
    log_level: str = "info",
) -> None:
    """Start the MCP server over the selected transport."""
    if sites is None:
        sites = ["escape"]

    if transport == "stdio":
        cfg_path = _resolve_cfg_path(sites[0], rucio_cfg)
        _preflight_check(cfg_path, auth_type_override=auth_type)
        _make_stdio_mcp(read_only=read_only, site_name=sites[0]).run(transport="stdio")
        return

    # HTTP transport, shared-secret mode: serve one pre-authenticated env client
    # (e.g. x509) behind a static bearer. Distinct from the OIDC bridge below.
    if shared_secret:
        if len(sites) > 1:
            sys.stderr.write(
                "[rucio-mcp] Error: shared-secret mode serves a single "
                "pre-authenticated client; specify exactly one --site.\n"
            )
            sys.exit(1)
        cfg_path = _resolve_cfg_path(sites[0], rucio_cfg)
        _preflight_check(cfg_path, auth_type_override=auth_type)
        app = _make_shared_secret_app(
            site_name=sites[0],
            resource_url=resource_url or f"http://{host}:{port}",
            read_only=read_only,
            secret=shared_secret,
            host=host,
            port=port,
        )
        start_metrics_server(metrics_port, {})
        uvicorn.run(
            app,
            host=host,
            port=port,
            proxy_headers=True,
            forwarded_allow_ips=forwarded_allow_ips,
            log_level=log_level,
        )
        return

    # HTTP transport (OIDC bridge)
    if auth_type is not None:
        sys.stderr.write(
            "[rucio-mcp] WARNING: --auth-type is ignored in HTTP mode "
            "(HTTP mode always authenticates via the OIDC OAuth bridge).\n"
        )

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
        poll_timeout=poll_timeout,
    )
    start_metrics_server(metrics_port, app.state.bridge_stores)
    uvicorn.run(
        app,
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips=forwarded_allow_ips,
        log_level=log_level,
    )
