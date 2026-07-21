"""Prometheus metrics for the rucio-mcp HTTP transport.

Exposes:
- Standard HTTP request/response counters and histograms (via PrometheusMiddleware)
- Per-tool call counter and duration histogram (via _InstrumentedFastMCP in server.py)
- Per-site bridge session gauge and cached Rucio client gauge (via BridgeStatsCollector)

The PrometheusMiddleware tracks every inbound HTTP request at the Starlette app
level.  Tool-call metrics are incremented at the FastMCP dispatch layer.
Bridge gauges are computed on demand when the collector is scraped — there is
no background flush thread.

``serve()`` in ``server.py`` calls ``start_metrics_server(port, bridge_stores)``
which registers a ``BridgeStatsCollector`` and starts a dedicated HTTP server
(``prometheus_client.start_http_server``) on a separate port so that scrape
traffic is isolated from the MCP endpoint.
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from prometheus_client import (
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    disable_created_metrics,
    start_http_server,
)
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from starlette.routing import Match
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

# Suppress the _created timestamp series that prometheus_client emits by default
# for every Counter and Histogram.  These are pure noise for our dashboards.
# Must be called before any Counter/Histogram is instantiated (below).
disable_created_metrics()

if TYPE_CHECKING:
    from rucio_mcp.auth.bridge_state import BridgeStateStore
    from rucio_mcp.auth.session_cache import SessionCache

# ---------------------------------------------------------------------------
# HTTP request counters — registered once at module import time
# ---------------------------------------------------------------------------

REQUESTS = Counter(
    "starlette_requests_total",
    "Total count of requests by method, path and site.",
    ["method", "path_template", "site"],
)
RESPONSES = Counter(
    "starlette_responses_total",
    "Total count of responses by method, path, status code and site.",
    ["method", "path_template", "status_code", "site"],
)
REQUESTS_PROCESSING_TIME = Histogram(
    "starlette_requests_processing_time_seconds",
    "Histogram of requests processing time by path and site (in seconds)",
    ["method", "path_template", "site"],
)
EXCEPTIONS = Counter(
    "starlette_exceptions_total",
    "Total count of exceptions by method, path, exception type and site.",
    ["method", "path_template", "exception_type", "site"],
)
REQUESTS_IN_PROGRESS = Gauge(
    "starlette_requests_in_progress",
    "Gauge of requests by method, path and site currently being processed.",
    ["method", "path_template", "site"],
)

# ---------------------------------------------------------------------------
# Authentication outcome counter — registered once at module import time
# ---------------------------------------------------------------------------

BRIDGE_AUTH = Counter(
    "rucio_mcp_bridge_auth_total",
    "Total OAuth bridge auth events by site and outcome (started|success|failure|timeout).",
    ["site", "outcome"],
)

# ---------------------------------------------------------------------------
# Tool-call metrics — registered once at module import time
# ---------------------------------------------------------------------------

TOOL_CALLS = Counter(
    "rucio_mcp_tool_calls_total",
    "Total count of MCP tool invocations by site and tool name.",
    ["site", "tool"],
)
TOOL_CALL_DURATION = Histogram(
    "rucio_mcp_tool_call_duration_seconds",
    "Histogram of MCP tool execution time by site and tool name (seconds).",
    ["site", "tool"],
)
TOOL_ERRORS = Counter(
    "rucio_mcp_tool_errors_total",
    "Total count of tool errors by site, tool, and error category.",
    ["site", "tool", "category"],
)

# Set by _InstrumentedFastMCP.call_tool before dispatching to the tool handler.
# Carries (site, tool) so classify_error() can label TOOL_ERRORS without
# threading the labels through every tool call site.
current_tool_labels: ContextVar[tuple[str, str]] = ContextVar(
    "current_tool_labels", default=("unknown", "unknown")
)


# ---------------------------------------------------------------------------
# Bridge-specific gauges — computed on each scrape via a custom Collector
# ---------------------------------------------------------------------------


class BridgeStatsCollector(Collector):
    """Emit live bridge-session and cached-client gauges from in-memory stores."""

    def __init__(
        self,
        bridge_stores: dict[str, tuple[BridgeStateStore, SessionCache]],
    ) -> None:
        """Store a reference to the live bridge and cache stores."""
        self._bridge_stores = bridge_stores

    def collect(self) -> Any:
        """Yield bridge-session and cached-client gauge families on each scrape."""
        sessions = GaugeMetricFamily(
            "rucio_mcp_bridge_sessions",
            "Current number of in-flight OAuth bridge sessions by site and status.",
            labels=["site", "status"],
        )
        clients = GaugeMetricFamily(
            "rucio_mcp_cached_clients",
            "Current number of cached Rucio client instances by site.",
            labels=["site"],
        )
        for site, (store, cache) in self._bridge_stores.items():
            for status, count in store.session_counts().items():
                sessions.add_metric([site, status], count)
            clients.add_metric([site], cache.size())
        yield sessions
        yield clients


def start_metrics_server(
    port: int,
    bridge_stores: dict[str, tuple[BridgeStateStore, SessionCache]],
) -> None:
    """Register bridge stats collector and start a dedicated Prometheus HTTP server.

    The server runs in a daemon thread owned by prometheus_client and binds to
    0.0.0.0:<port>.  Call this once from ``serve()`` before ``uvicorn.run``.
    """
    REGISTRY.register(BridgeStatsCollector(bridge_stores))
    start_http_server(port)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class PrometheusMiddleware:
    """Record per-route request counts, response codes, latency, and exceptions.

    Pure ASGI middleware: the duration histogram and in-progress gauge span the
    whole request, up to the last response body message.  A ``BaseHTTPMiddleware``
    version would close its measurement once the response starts, understating
    latency for streamed/SSE responses.
    """

    def __init__(
        self,
        app: Any,
        *,
        filter_unhandled_paths: bool = False,
        excluded_paths: frozenset[str] = frozenset(),
        site_names: frozenset[str] = frozenset(),
    ) -> None:
        """Wrap *app*.

        *filter_unhandled_paths* skips unmatched routes.
        *excluded_paths* lists exact paths (e.g. ``{"/healthz"}``) that are
        served but must never be recorded in metrics.
        *site_names* is the set of known site identifiers (e.g. ``{"atlas",
        "escape"}``).  Any matched path containing ``/site/<name>`` for a
        known name will record ``site=<name>`` and have that segment
        normalised to ``/site/{site}`` in ``path_template``, collapsing the
        per-site well-known variant paths into a single template each.
        """
        self.app = app
        self.filter_unhandled_paths = filter_unhandled_paths
        self.excluded_paths = excluded_paths
        self.site_names = site_names

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        """Instrument the request and delegate to the wrapped app."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        path = scope["path"]

        if path in self.excluded_paths:
            await self.app(scope, receive, send)
            return

        path_template, is_handled = self._path_template(scope)

        if self.filter_unhandled_paths and not is_handled:
            await self.app(scope, receive, send)
            return

        site, path_template = self._normalize_site(path_template)

        status_code = HTTP_500_INTERNAL_SERVER_ERROR

        async def _send(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        REQUESTS_IN_PROGRESS.labels(
            method=method, path_template=path_template, site=site
        ).inc()
        REQUESTS.labels(method=method, path_template=path_template, site=site).inc()
        t0 = time.perf_counter()
        try:
            await self.app(scope, receive, _send)
        except BaseException as exc:
            EXCEPTIONS.labels(
                method=method,
                path_template=path_template,
                exception_type=type(exc).__name__,
                site=site,
            ).inc()
            raise
        finally:
            elapsed = time.perf_counter() - t0
            REQUESTS_PROCESSING_TIME.labels(
                method=method, path_template=path_template, site=site
            ).observe(elapsed)
            RESPONSES.labels(
                method=method,
                path_template=path_template,
                status_code=str(status_code),
                site=site,
            ).inc()
            REQUESTS_IN_PROGRESS.labels(
                method=method, path_template=path_template, site=site
            ).dec()

    def _normalize_site(self, path_template: str) -> tuple[str, str]:
        """Return ``(site, normalized_path_template)`` for the matched route.

        If the path contains ``/site/<known_name>``, returns that name as
        ``site`` and replaces the literal segment with ``/site/{site}`` so
        all per-site variants collapse to a single template in metrics.
        """
        for name in self.site_names:
            segment = f"/site/{name}"
            if segment in path_template:
                return name, path_template.replace(segment, "/site/{site}", 1)
        return "", path_template

    @staticmethod
    def _path_template(scope: Any) -> tuple[str, bool]:
        for route in scope["app"].routes:
            match, _ = route.matches(scope)
            if match == Match.FULL:
                return route.path, True
        return scope["path"], False
