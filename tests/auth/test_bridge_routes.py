"""Tests for /bridge and /bridge/status routes."""

from __future__ import annotations

import time

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from rucio_mcp.auth.bridge_routes import make_bridge_handlers
from rucio_mcp.auth.bridge_state import BridgeSession, BridgeStateStore


def _make_store() -> BridgeStateStore:
    return BridgeStateStore()


def _make_session(session_id: str = "sess-1", **kwargs: object) -> BridgeSession:
    defaults: dict[str, object] = {
        "session_id": session_id,
        "polling_url": "https://idp.example.com/login?state=xyz_polling",
        "code_challenge": "abc123",
        "redirect_uri": "http://localhost:1234/callback",
        "redirect_uri_provided_explicitly": True,
        "client_id": "client-xyz",
        "scopes": ["openid"],
        "resource": None,
        "state": "oauth-state",
        "expires_at": time.time() + 300,
    }
    defaults.update(kwargs)
    return BridgeSession(**defaults)  # type: ignore[arg-type]


def _make_app(store: BridgeStateStore) -> Starlette:
    bridge_page, bridge_status = make_bridge_handlers(store)
    return Starlette(
        routes=[
            Route("/bridge", bridge_page, methods=["GET"]),
            Route("/bridge/status", bridge_status, methods=["GET"]),
        ]
    )


class TestBridgePage:
    def test_missing_session_param_returns_400(self) -> None:
        store = _make_store()
        client = TestClient(_make_app(store), raise_server_exceptions=True)
        resp = client.get("/bridge")
        assert resp.status_code == 400

    def test_unknown_session_returns_404(self) -> None:
        store = _make_store()
        client = TestClient(_make_app(store), raise_server_exceptions=True)
        resp = client.get("/bridge?session=nonexistent")
        assert resp.status_code == 404

    def test_valid_session_returns_html(self) -> None:
        store = _make_store()
        store.put(_make_session("abc"))
        client = TestClient(_make_app(store), raise_server_exceptions=True)
        resp = client.get("/bridge?session=abc")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_html_contains_polling_url_link(self) -> None:
        store = _make_store()
        store.put(_make_session("abc"))
        client = TestClient(_make_app(store), raise_server_exceptions=True)
        resp = client.get("/bridge?session=abc")
        assert "https://idp.example.com/login?state=xyz_polling" in resp.text

    def test_html_contains_js_status_poller(self) -> None:
        store = _make_store()
        store.put(_make_session("abc"))
        client = TestClient(_make_app(store), raise_server_exceptions=True)
        resp = client.get("/bridge?session=abc")
        assert "bridge/status" in resp.text  # relative URL works under any mount prefix
        assert "abc" in resp.text  # session id embedded in JS

    def test_polling_url_is_html_escaped(self) -> None:
        store = _make_store()
        store.put(
            _make_session(
                "abc",
                polling_url='https://idp.example.com/login"><script>alert(1)</script>',
            )
        )
        client = TestClient(_make_app(store), raise_server_exceptions=True)
        resp = client.get("/bridge?session=abc")
        # The raw injection must not appear; the escaped form must.
        assert "<script>alert(1)</script>" not in resp.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in resp.text

    def test_session_id_is_html_escaped(self) -> None:
        store = _make_store()
        store.put(_make_session('s"</script><b>'))
        client = TestClient(_make_app(store), raise_server_exceptions=True)
        resp = client.get('/bridge?session=s"</script><b>')
        assert "</script><b>" not in resp.text
        assert "&lt;/script&gt;&lt;b&gt;" in resp.text


class TestBridgeStatus:
    def test_missing_session_param_returns_400(self) -> None:
        store = _make_store()
        client = TestClient(_make_app(store), raise_server_exceptions=True)
        resp = client.get("/bridge/status")
        assert resp.status_code == 400

    def test_unknown_session_returns_error_json(self) -> None:
        store = _make_store()
        client = TestClient(_make_app(store), raise_server_exceptions=True)
        resp = client.get("/bridge/status?session=ghost")
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"

    def test_pending_session_returns_pending(self) -> None:
        store = _make_store()
        store.put(_make_session("abc"))
        client = TestClient(_make_app(store), raise_server_exceptions=True)
        resp = client.get("/bridge/status?session=abc")
        assert resp.status_code == 200
        assert resp.json() == {"status": "pending"}

    def test_done_session_returns_code_and_state(self) -> None:
        store = _make_store()
        store.put(_make_session("abc"))
        store.mark_done("abc", rucio_token="tok", auth_code="mcp-code-xyz")
        client = TestClient(_make_app(store), raise_server_exceptions=True)
        resp = client.get("/bridge/status?session=abc")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "done"
        assert data["code"] == "mcp-code-xyz"
        assert data["state"] == "oauth-state"
        assert data["redirect_uri"] == "http://localhost:1234/callback"

    def test_error_session_returns_error_message(self) -> None:
        store = _make_store()
        store.put(_make_session("abc"))
        store.mark_error("abc", "timeout waiting for user login")
        client = TestClient(_make_app(store), raise_server_exceptions=True)
        resp = client.get("/bridge/status?session=abc")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "timeout" in data["message"]
