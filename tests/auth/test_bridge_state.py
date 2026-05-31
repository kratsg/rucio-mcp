"""Tests for BridgeSession and BridgeStateStore."""

from __future__ import annotations

import time

from rucio_mcp.auth.bridge_state import BridgeSession, BridgeStateStore


def _make_session(session_id: str = "sess-1", **kwargs: object) -> BridgeSession:
    defaults: dict[str, object] = {
        "session_id": session_id,
        "polling_url": "https://rucio-auth.example.com/auth/oidc_redirect?state=xyz_polling",
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


class TestBridgeSession:
    def test_default_status_is_pending(self) -> None:
        s = _make_session()
        assert s.status == "pending"

    def test_rucio_token_none_by_default(self) -> None:
        s = _make_session()
        assert s.rucio_token is None

    def test_auth_code_none_by_default(self) -> None:
        s = _make_session()
        assert s.auth_code is None

    def test_error_message_none_by_default(self) -> None:
        s = _make_session()
        assert s.error_message is None


class TestBridgeStateStore:
    def test_get_returns_none_for_unknown_session(self) -> None:
        store = BridgeStateStore()
        assert store.get_by_session_id("nonexistent") is None

    def test_put_and_get_by_session_id(self) -> None:
        store = BridgeStateStore()
        s = _make_session("abc")
        store.put(s)
        assert store.get_by_session_id("abc") is s

    def test_get_by_auth_code_returns_none_before_registration(self) -> None:
        store = BridgeStateStore()
        assert store.get_by_auth_code("code-xyz") is None

    def test_mark_done_sets_status_token_and_code(self) -> None:
        store = BridgeStateStore()
        store.put(_make_session("s1"))
        store.mark_done("s1", rucio_token="rucio-tok-abc", auth_code="mcp-code-123")
        s = store.get_by_session_id("s1")
        assert s is not None
        assert s.status == "done"
        assert s.rucio_token == "rucio-tok-abc"
        assert s.auth_code == "mcp-code-123"

    def test_mark_done_enables_get_by_auth_code(self) -> None:
        store = BridgeStateStore()
        store.put(_make_session("s1"))
        store.mark_done("s1", rucio_token="tok", auth_code="code-abc")
        s = store.get_by_auth_code("code-abc")
        assert s is not None
        assert s.session_id == "s1"

    def test_mark_error_sets_status_and_message(self) -> None:
        store = BridgeStateStore()
        store.put(_make_session("s1"))
        store.mark_error("s1", "timeout waiting for user")
        s = store.get_by_session_id("s1")
        assert s is not None
        assert s.status == "error"
        assert s.error_message == "timeout waiting for user"

    def test_expired_sessions_are_evicted(self) -> None:
        store = BridgeStateStore()
        expired = _make_session("old", expires_at=time.time() - 1)
        store.put(expired)
        # put() evicts; get() also evicts before lookup
        assert store.get_by_session_id("old") is None

    def test_non_expired_sessions_survive_eviction(self) -> None:
        store = BridgeStateStore()
        store.put(_make_session("live", expires_at=time.time() + 300))
        store.put(_make_session("dead", expires_at=time.time() - 1))
        assert store.get_by_session_id("live") is not None
        assert store.get_by_session_id("dead") is None

    def test_expired_auth_code_index_also_evicted(self) -> None:
        store = BridgeStateStore()
        s = _make_session("s1", expires_at=time.time() - 1)
        store.put(s)
        store.mark_done("s1", rucio_token="tok", auth_code="code-xyz")
        # force eviction via a fresh put
        store.put(_make_session("s2"))
        assert store.get_by_auth_code("code-xyz") is None

    def test_mark_done_on_unknown_session_is_noop(self) -> None:
        store = BridgeStateStore()
        store.mark_done("ghost", rucio_token="tok", auth_code="code")  # must not raise

    def test_mark_error_on_unknown_session_is_noop(self) -> None:
        store = BridgeStateStore()
        store.mark_error("ghost", "oops")  # must not raise

    def test_session_counts_empty_store(self) -> None:
        store = BridgeStateStore()
        assert sum(store.session_counts().values()) == 0

    def test_session_counts_all_pending(self) -> None:
        store = BridgeStateStore()
        store.put(_make_session("s1"))
        store.put(_make_session("s2"))
        counts = store.session_counts()
        assert counts.get("pending", 0) == 2

    def test_session_counts_mixed_statuses(self) -> None:
        store = BridgeStateStore()
        store.put(_make_session("s1"))
        store.put(_make_session("s2"))
        store.put(_make_session("s3"))
        store.mark_done("s1", rucio_token="tok", auth_code="code-1")
        store.mark_error("s2", "timeout")
        counts = store.session_counts()
        assert counts.get("pending", 0) == 1
        assert counts.get("done", 0) == 1
        assert counts.get("error", 0) == 1

    def test_session_counts_excludes_expired(self) -> None:
        store = BridgeStateStore()
        store.put(_make_session("live", expires_at=time.time() + 300))
        store.put(_make_session("dead", expires_at=time.time() - 1))
        counts = store.session_counts()
        assert counts.get("pending", 0) == 1
