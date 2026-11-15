"""Unit tests for structured JSON logging, the request-id middleware and tool.call lines."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import pytest
from mcp.types import CallToolResult, TextContent
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from rucio_mcp.observability import (
    MAX_REQUEST_ID_CHARS,
    JsonFormatter,
    LoggingMCPServer,
    RequestLogMiddleware,
    request_id_var,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from conftest import JsonLog
    from mcp.server.mcpserver import MCPServer
    from starlette.requests import Request
    from starlette.responses import Response


@pytest.fixture
def client(json_log: JsonLog) -> Iterator[TestClient]:  # noqa: ARG001
    """A real Starlette app behind RequestLogMiddleware with a probe that can fail."""
    probe_status = {"code": 200}

    async def healthz(_request: Request) -> Response:
        return PlainTextResponse("probe", status_code=probe_status["code"])

    async def work(_request: Request) -> Response:
        logging.getLogger("rucio_mcp.test").info("working")
        return PlainTextResponse("done")

    async def break_probe(_request: Request) -> Response:
        probe_status["code"] = 503
        return PlainTextResponse("broken")

    app = Starlette(
        routes=[
            Route("/healthz", healthz),
            Route("/work", work),
            Route("/break", break_probe),
        ]
    )
    app.add_middleware(RequestLogMiddleware)
    with TestClient(app) as test_client:
        yield test_client


class TestJsonFormatter:
    def test_standard_fields_are_present(self) -> None:
        record = logging.LogRecord(
            "rucio_mcp.x", logging.WARNING, "f", 1, "evt", (), None
        )
        entry = json.loads(JsonFormatter().format(record))

        assert entry["logger"] == "rucio_mcp.x"
        assert entry["level"] == "warning"
        assert entry["event"] == "evt"
        assert entry["timestamp"].endswith("+00:00")

    def test_request_id_is_added_when_bound(self) -> None:
        reset = request_id_var.set("abc")
        try:
            record = logging.LogRecord("n", logging.INFO, "f", 1, "evt", (), None)
            entry = json.loads(JsonFormatter().format(record))
        finally:
            request_id_var.reset(reset)

        assert entry["request_id"] == "abc"

    def test_extra_fields_are_merged(self) -> None:
        record = logging.LogRecord("n", logging.INFO, "f", 1, "evt", (), None)
        record.fields = {"tool": "rucio_ping", "duration_ms": 1.5}
        entry = json.loads(JsonFormatter().format(record))

        assert entry["tool"] == "rucio_ping"
        assert entry["duration_ms"] == pytest.approx(1.5)


class TestRequestLogMiddleware:
    def test_header_request_id_is_on_every_line(
        self, client: TestClient, json_log: JsonLog
    ) -> None:
        client.get("/work", headers={"X-Request-ID": "abc"})

        lines = json_log.lines()
        assert {line["event"] for line in lines} == {"working", "http.request"}
        assert all(line["request_id"] == "abc" for line in lines)

    def test_missing_header_generates_an_id(
        self, client: TestClient, json_log: JsonLog
    ) -> None:
        client.get("/work")

        ids = {line["request_id"] for line in json_log.lines()}
        assert len(ids) == 1
        assert ids != {""}

    def test_overlong_id_is_truncated(
        self, client: TestClient, json_log: JsonLog
    ) -> None:
        client.get("/work", headers={"X-Request-ID": "x" * 500})

        assert {len(line["request_id"]) for line in json_log.lines()} == {
            MAX_REQUEST_ID_CHARS
        }

    def test_access_line_has_method_path_status_duration(
        self, client: TestClient, json_log: JsonLog
    ) -> None:
        client.get("/work", headers={"X-Request-ID": "abc"})

        access = next(
            line for line in json_log.lines() if line["event"] == "http.request"
        )
        assert (access["method"], access["path"], access["status"]) == (
            "GET",
            "/work",
            200,
        )
        assert access["duration_ms"] >= 0

    def test_successful_probe_writes_no_line(
        self, client: TestClient, json_log: JsonLog
    ) -> None:
        for _ in range(3):
            assert client.get("/healthz").status_code == 200

        assert json_log.lines() == []

    def test_failing_probe_is_logged(
        self, client: TestClient, json_log: JsonLog
    ) -> None:
        client.get("/break")
        json_log.clear()

        assert client.get("/healthz").status_code == 503

        (line,) = json_log.lines()
        assert (line["event"], line["path"], line["status"]) == (
            "http.request",
            "/healthz",
            503,
        )

    def test_request_id_does_not_leak_to_later_lines(self, client: TestClient) -> None:
        client.get("/work", headers={"X-Request-ID": "abc"})

        assert request_id_var.get() is None


class TestLoggingMCPServer:
    """One tool.call line per call, with the outcome of the call and never its payload."""

    @staticmethod
    def _server(**kwargs: Any) -> MCPServer:
        mcp = LoggingMCPServer("test", **kwargs)

        @mcp.tool()
        async def fine(secret: str) -> CallToolResult:
            return CallToolResult(content=[TextContent(type="text", text=secret)])

        @mcp.tool()
        async def reported_error() -> CallToolResult:
            return CallToolResult(
                content=[TextContent(type="text", text="no")], is_error=True
            )

        @mcp.tool()
        async def crashes() -> CallToolResult:
            msg = "boom"
            raise RuntimeError(msg)

        return mcp

    async def test_successful_call_is_an_ok_line(self, json_log: JsonLog) -> None:
        await self._server().call_tool("fine", {"secret": "s3cret"})

        (line,) = json_log.lines()
        assert line["event"] == "tool.call"
        assert line["tool"] == "fine"
        assert line["outcome"] == "ok"
        assert line["duration_ms"] >= 0

    async def test_error_result_is_an_error_line(self, json_log: JsonLog) -> None:
        await self._server().call_tool("reported_error", {})

        (line,) = json_log.lines()
        assert line["outcome"] == "error"

    async def test_raised_exception_is_an_error_line(self, json_log: JsonLog) -> None:
        with pytest.raises(Exception, match="crashes"):
            await self._server().call_tool("crashes", {})

        (line,) = json_log.lines()
        assert line["outcome"] == "error"

    async def test_arguments_and_results_are_never_logged(
        self, json_log: JsonLog
    ) -> None:
        await self._server().call_tool("fine", {"secret": "s3cret"})

        assert "s3cret" not in json_log.stream.getvalue()

    async def test_no_subject_without_a_token(self, json_log: JsonLog) -> None:
        await self._server(log_subject=True).call_tool("fine", {"secret": "x"})

        (line,) = json_log.lines()
        assert "subject" not in line
