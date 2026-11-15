"""End-to-end observability tests over HTTP, for both deployed modes.

Broker mode (``rucio-mcp``) verifies broker JWTs against a real local JWKS
endpoint; OIDC bridge mode (``rucio-mcp-oidc``) takes an opaque Rucio session
token and has no JWKS at all. Tools fail against a closed local port, which is
a real, deterministic error outcome that needs no Rucio server.
"""

from __future__ import annotations

import json
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from rucio_mcp.auth.rucio_cfg import RucioCfg
from rucio_mcp.server import _make_broker_app, _make_http_app

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from conftest import JsonLog

AUDIENCE = "rucio"
KID = "test-kid"
JWKS_PATH = "/.well-known/jwks.json"
SITE_PATH = "/site/atlas/"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


class BrokerStub:
    """A local HTTP server: serves one RSA key as a JWKS, counts JWKS fetches.

    Every other path answers 404, which is how a broker that cannot redeem a
    proxy looks to the backend.
    """

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        self._body = json.dumps(
            {"keys": [{**jwk, "kid": KID, "alg": "RS256"}]}
        ).encode()
        self.jwks_fetches = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                is_jwks = self.path == JWKS_PATH
                outer.jwks_fetches += is_jwks
                self.send_response(200 if is_jwks else 404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(outer._body if is_jwks else b"{}")

            def log_message(self, *_args: object) -> None:
                """Keep the test output pristine."""

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> None:
        """Begin serving in a background thread."""
        self._thread.start()

    def stop(self) -> None:
        """Stop serving and release the port."""
        self._server.shutdown()
        self._server.server_close()

    def token(self, sub: str = "user-sub-1") -> str:
        """Sign a broker identity token for this stub's issuer and the rucio audience."""
        now = int(time.time())
        claims = {
            "iss": self.url,
            "sub": sub,
            "aud": AUDIENCE,
            "jti": "jti-1",
            "iat": now,
            "exp": now + 600,
        }
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": KID})


def _call_tool(client: TestClient, bearer: str, request_id: str) -> None:
    """Run initialize and one tool call, the second carrying the X-Request-ID."""
    base = {**HEADERS, "Authorization": f"Bearer {bearer}"}
    init = client.post(SITE_PATH, json=INITIALIZE, headers=base)
    assert init.status_code == 200
    session = init.headers.get("mcp-session-id")
    if session:
        base["mcp-session-id"] = session
    client.post(
        SITE_PATH,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=base,
    )
    response = client.post(
        SITE_PATH,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "rucio_list_scopes", "arguments": {}},
        },
        headers={**base, "X-Request-ID": request_id},
    )
    assert response.status_code == 200


@pytest.fixture
def closed_port_cfg(tmp_path: Path) -> Path:
    """A rucio.cfg whose servers refuse connections, so a tool call fails fast."""
    path = tmp_path / "rucio.cfg"
    path.write_text(
        textwrap.dedent("""\
            [client]
            rucio_host = http://127.0.0.1:9
            auth_host = http://127.0.0.1:9
            account = tester
            oidc_audience = rucio
            oidc_issuer = atlas
            oidc_scope = openid profile
        """)
    )
    return path


@pytest.fixture
def broker() -> Iterator[BrokerStub]:
    stub = BrokerStub()
    stub.start()
    yield stub
    stub.stop()


@pytest.fixture
def broker_client(broker: BrokerStub, closed_port_cfg: Path) -> Iterator[TestClient]:
    app = _make_broker_app(
        site_name="atlas",
        cfg=RucioCfg.from_path(closed_port_cfg),
        resource_url="http://127.0.0.1:8000",
        read_only=True,
        broker_url=broker.url,
        jwks_url=broker.url + JWKS_PATH,
        issuer=broker.url,
        audience=AUDIENCE,
        host="127.0.0.1",
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client


@pytest.fixture
def oidc_client(closed_port_cfg: Path) -> Iterator[TestClient]:
    app = _make_http_app(
        sites=["atlas"],
        resource_url="http://127.0.0.1:8000",
        read_only=True,
        host="127.0.0.1",
        rucio_cfg_overrides={"atlas": closed_port_cfg},
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client


def _tool_calls(json_log: JsonLog) -> list[dict[str, Any]]:
    return [line for line in json_log.lines() if line["event"] == "tool.call"]


class TestBrokerModeLogging:
    """The ``rucio-mcp`` deployment: broker JWT in, JWKS verification."""

    def test_tool_call_and_access_lines_carry_the_request_id(
        self, broker_client: TestClient, broker: BrokerStub, json_log: JsonLog
    ) -> None:
        _call_tool(broker_client, broker.token(), "abc")

        carrying = [ln for ln in json_log.lines() if ln.get("request_id") == "abc"]
        assert {"tool.call", "http.request"} <= {ln["event"] for ln in carrying}
        (call,) = _tool_calls(json_log)
        assert call["request_id"] == "abc"

    def test_tool_call_line_has_the_standard_fields(
        self, broker_client: TestClient, broker: BrokerStub, json_log: JsonLog
    ) -> None:
        _call_tool(broker_client, broker.token("kratsg"), "abc")

        (call,) = _tool_calls(json_log)
        assert call["tool"] == "rucio_list_scopes"
        assert call["subject"] == "kratsg"
        assert call["outcome"] == "error"
        assert call["duration_ms"] >= 0
        assert call["level"] == "info"
        assert call["logger"]
        assert call["timestamp"]

    def test_no_line_contains_the_token(
        self, broker_client: TestClient, broker: BrokerStub, json_log: JsonLog
    ) -> None:
        token = broker.token()

        _call_tool(broker_client, token, "abc")

        assert token not in json_log.stream.getvalue()

    def test_successful_probe_writes_no_line(
        self, broker_client: TestClient, json_log: JsonLog
    ) -> None:
        for _ in range(3):
            assert broker_client.get("/healthz").status_code == 200

        assert json_log.lines() == []

    def test_unauthenticated_mcp_request_keeps_its_access_line(
        self, broker_client: TestClient, json_log: JsonLog
    ) -> None:
        broker_client.post(SITE_PATH, json=INITIALIZE, headers=HEADERS)

        access = [ln for ln in json_log.lines() if ln["event"] == "http.request"]
        assert [(ln["path"], ln["status"]) for ln in access] == [(SITE_PATH, 401)]

    def test_repeated_requests_fetch_the_jwks_once(
        self, broker_client: TestClient, broker: BrokerStub
    ) -> None:
        token = broker.token()

        for index in range(5):
            _call_tool(broker_client, token, f"req-{index}")

        assert broker.jwks_fetches == 1


class TestOidcBridgeModeLogging:
    """The ``rucio-mcp-oidc`` deployment: opaque Rucio token, no JWKS, no broker."""

    def test_tool_call_carries_a_request_id_and_no_subject(
        self, oidc_client: TestClient, json_log: JsonLog
    ) -> None:
        _call_tool(oidc_client, "opaque-rucio-token", "abc")

        (call,) = _tool_calls(json_log)
        assert call["request_id"] == "abc"
        assert call["tool"] == "rucio_list_scopes"
        assert "subject" not in call

    def test_request_without_the_header_still_gets_an_id(
        self, oidc_client: TestClient, json_log: JsonLog
    ) -> None:
        oidc_client.get("/")

        (access,) = json_log.lines()
        assert access["event"] == "http.request"
        assert access["request_id"]

    def test_no_line_contains_the_rucio_token(
        self, oidc_client: TestClient, json_log: JsonLog
    ) -> None:
        _call_tool(oidc_client, "opaque-rucio-token", "abc")

        assert "opaque-rucio-token" not in json_log.stream.getvalue()

    def test_successful_probe_writes_no_line(
        self, oidc_client: TestClient, json_log: JsonLog
    ) -> None:
        for _ in range(3):
            assert oidc_client.get("/healthz").status_code == 200

        assert json_log.lines() == []
