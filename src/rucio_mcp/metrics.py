"""Prometheus metrics for the rucio-mcp HTTP transport.

Exposes:
- Standard HTTP request/response counters and histograms (via PrometheusMiddleware)
- Per-site bridge session gauge (``rucio_mcp_bridge_sessions{site, status}``)
- Per-site cached Rucio client gauge (``rucio_mcp_cached_clients{site}``)

The PrometheusMiddleware tracks every inbound HTTP request at the Starlette app
level.  Custom bridge gauges are computed on demand when ``/metrics`` is scraped
— there is no background flush thread.

``_make_http_app`` in ``server.py`` wires this module in: it stores
``app.state.bridge_stores`` (a ``dict[site, (BridgeStateStore, SessionCache)]``)
so the metrics handler can pull live counts without holding any locks long-term.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.routing import Match
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.types import ASGIApp

    from rucio_mcp.auth.bridge_state import BridgeStateStore
    from rucio_mcp.auth.session_cache import SessionCache

# ---------------------------------------------------------------------------
# HTTP request counters — registered once at module import time
# ---------------------------------------------------------------------------

REQUESTS = Counter(
    "starlette_requests_total",
    "Total count of requests by method and path.",
    ["method", "path_template"],
)
RESPONSES = Counter(
    "starlette_responses_total",
    "Total count of responses by method, path and status codes.",
    ["method", "path_template", "status_code"],
)
REQUESTS_PROCESSING_TIME = Histogram(
    "starlette_requests_processing_time_seconds",
    "Histogram of requests processing time by path (in seconds)",
    ["method", "path_template"],
)
EXCEPTIONS = Counter(
    "starlette_exceptions_total",
    "Total count of exceptions by method, path and exception type.",
    ["method", "path_template", "exception_type"],
)
REQUESTS_IN_PROGRESS = Gauge(
    "starlette_requests_in_progress",
    "Gauge of requests by method and path currently being processed.",
    ["method", "path_template"],
)

# ---------------------------------------------------------------------------
# Bridge-specific gauges (values set on each /metrics scrape)
# ---------------------------------------------------------------------------

BRIDGE_SESSIONS = Gauge(
    "rucio_mcp_bridge_sessions",
    "Current number of in-flight OAuth bridge sessions by site and status.",
    ["site", "status"],
)
CACHED_CLIENTS = Gauge(
    "rucio_mcp_cached_clients",
    "Current number of cached Rucio client instances by site.",
    ["site"],
)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record per-route request counts, response codes, latency, and exceptions."""

    def __init__(self, app: ASGIApp, *, filter_unhandled_paths: bool = False) -> None:
        """Wrap *app*; set *filter_unhandled_paths* to skip unmatched routes."""
        super().__init__(app)
        self.filter_unhandled_paths = filter_unhandled_paths

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Instrument the request and delegate to *call_next*."""
        method = request.method
        path_template, is_handled = self._path_template(request)

        if self.filter_unhandled_paths and not is_handled:
            return await call_next(request)

        REQUESTS_IN_PROGRESS.labels(method=method, path_template=path_template).inc()
        REQUESTS.labels(method=method, path_template=path_template).inc()
        t0 = time.perf_counter()
        status_code = HTTP_500_INTERNAL_SERVER_ERROR
        try:
            response = await call_next(request)
            status_code = response.status_code
        except BaseException as exc:
            EXCEPTIONS.labels(
                method=method,
                path_template=path_template,
                exception_type=type(exc).__name__,
            ).inc()
            raise
        finally:
            elapsed = time.perf_counter() - t0
            REQUESTS_PROCESSING_TIME.labels(
                method=method, path_template=path_template
            ).observe(elapsed)
            RESPONSES.labels(
                method=method,
                path_template=path_template,
                status_code=str(status_code),
            ).inc()
            REQUESTS_IN_PROGRESS.labels(
                method=method, path_template=path_template
            ).dec()
        return response

    @staticmethod
    def _path_template(request: Request) -> tuple[str, bool]:
        for route in request.app.routes:
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                return route.path, True
        return request.url.path, False


# ---------------------------------------------------------------------------
# /metrics handler
# ---------------------------------------------------------------------------


async def metrics_handler(request: Request) -> Response:
    """Return the current Prometheus metrics snapshot.

    Bridge session and cached-client gauges are refreshed from the live
    in-memory stores on every scrape so values are always up-to-date.
    """
    bridge_stores: dict[str, tuple[BridgeStateStore, SessionCache]] = getattr(
        request.app.state, "bridge_stores", {}
    )
    for site, (store, cache) in bridge_stores.items():
        for status, count in store.session_counts().items():
            BRIDGE_SESSIONS.labels(site=site, status=status).set(count)
        CACHED_CLIENTS.labels(site=site).set(cache.size())

    return Response(
        generate_latest(REGISTRY),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )
