"""Request id, JSON logs and the access line, so one call can be followed end to end.

The AF MCP broker sends its correlation id as ``X-Request-ID`` on every request
to a backend. ``RequestLogMiddleware`` binds it for the request and writes the
access line; ``JsonFormatter`` puts it on every line written meanwhile; and
``LoggingMCPServer`` writes one ``tool.call`` line per tool invocation.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TextIO

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver import MCPServer
from starlette.datastructures import Headers

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEALTH_PATH = "/healthz"
MAX_REQUEST_ID_CHARS = 128

log = logging.getLogger("rucio_mcp")
# The broker's X-Request-ID for the request being served. A ContextVar so tool
# code and library log calls carry it without passing it around.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    """One JSON object per line with the standard fields.

    Call-specific fields travel as ``extra={"fields": {...}}``.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Render the record as a single JSON line."""
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        if request_id := request_id_var.get():
            entry["request_id"] = request_id
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str, stream: TextIO | None = None) -> None:
    """Send every log line, the server's and uvicorn's, to *stream* as JSON.

    *level* is applied to the root logger so library loggers reach the
    handler. *stream* defaults to stdout, which is safe here because only the
    HTTP transport calls this; stdio uses stdout for the MCP protocol.
    """
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(handlers=[handler], force=True)
    logging.getLogger().setLevel(level.upper())


class RequestLogMiddleware:
    """Bind ``X-Request-ID`` for the request and write its access line.

    The broker's id is authoritative; one is generated only when the header is
    absent, so every line still carries an id. A health probe that succeeds
    writes no access line; a failing one does.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap *app*."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve one request inside its request-id context."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header = Headers(scope=scope).get("x-request-id", "")
        reset = request_id_var.set(header[:MAX_REQUEST_ID_CHARS] or uuid.uuid4().hex)
        status = 500
        started = time.perf_counter()

        async def send_and_note_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_note_status)
        finally:
            if scope["path"] != HEALTH_PATH or status >= 400:
                log.info(
                    "http.request",
                    extra={
                        "fields": {
                            "method": scope["method"],
                            "path": scope["path"],
                            "status": status,
                            "duration_ms": round(
                                (time.perf_counter() - started) * 1000, 1
                            ),
                        }
                    },
                )
            request_id_var.reset(reset)


class LoggingMCPServer(MCPServer):
    """MCPServer that writes one ``tool.call`` log line per tool invocation.

    The line carries the tool name, duration and outcome, never the tool's
    arguments or result. With ``log_subject`` it also carries the verified
    token's subject; leave it off where the bearer is not a user identity
    (the OIDC bridge's bearer is an opaque Rucio session token).
    """

    def __init__(self, *args: Any, log_subject: bool = False, **kwargs: Any) -> None:
        """Build the server; *log_subject* adds the token subject to each line."""
        super().__init__(*args, **kwargs)
        self._log_subject = log_subject

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Any = None
    ) -> Any:
        """Run the tool, then log how it went."""
        outcome = "error"
        started = time.perf_counter()
        try:
            result = await super().call_tool(name, arguments, context)
            outcome = "error" if getattr(result, "is_error", False) else "success"
        finally:
            fields: dict[str, Any] = {
                "tool": name,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "outcome": outcome,
            }
            token = get_access_token() if self._log_subject else None
            if token:
                fields["subject"] = token.client_id
            log.info("tool.call", extra={"fields": fields})
        return result
