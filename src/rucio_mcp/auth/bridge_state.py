"""In-memory state store for in-flight OAuth bridge sessions.

Each bridge session tracks the lifecycle of one user's authentication:
  pending  →  (rucio polling succeeds)  →  done
  pending  →  (timeout / error)         →  error

Sessions are evicted after 5 minutes (matching rucio's OAuthRequest.expired_at).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class BridgeSession:
    """State for one in-flight bridge session."""

    session_id: str
    polling_url: str
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    client_id: str
    scopes: list[str]
    resource: str | None
    state: str | None
    expires_at: float
    status: str = "pending"  # "pending" | "done" | "error"
    rucio_token: str | None = None
    auth_code: str | None = None
    error_message: str | None = None


class BridgeStateStore:
    """Thread-safe in-memory store for :class:`BridgeSession` objects.

    Two indices are maintained:
    - ``_by_session``: session_id → session
    - ``_by_code``: auth_code → session_id  (populated by :meth:`mark_done`)

    Expired sessions are evicted lazily on every :meth:`put` and :meth:`get_by_session_id`
    call to prevent unbounded memory growth.
    """

    _TTL: float = 300.0  # seconds — matches rucio's OAuthRequest.expired_at

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_session: dict[str, BridgeSession] = {}
        self._by_code: dict[str, str] = {}  # auth_code → session_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def put(self, session: BridgeSession) -> None:
        """Store *session*, replacing any existing entry with the same ID."""
        with self._lock:
            self._evict_locked()
            self._by_session[session.session_id] = session

    def get_by_session_id(self, session_id: str) -> BridgeSession | None:
        """Return the session or ``None`` if it does not exist or has expired."""
        with self._lock:
            self._evict_locked()
            return self._by_session.get(session_id)

    def get_by_auth_code(self, auth_code: str) -> BridgeSession | None:
        """Return the session associated with *auth_code*, or ``None``."""
        with self._lock:
            session_id = self._by_code.get(auth_code)
            if session_id is None:
                return None
            return self._by_session.get(session_id)

    def mark_done(self, session_id: str, *, rucio_token: str, auth_code: str) -> None:
        """Transition *session_id* to ``done`` and register the auth code index."""
        with self._lock:
            s = self._by_session.get(session_id)
            if s is None:
                return
            s.status = "done"
            s.rucio_token = rucio_token
            s.auth_code = auth_code
            self._by_code[auth_code] = session_id

    def mark_error(self, session_id: str, message: str) -> None:
        """Transition *session_id* to ``error`` with a human-readable *message*."""
        with self._lock:
            s = self._by_session.get(session_id)
            if s is None:
                return
            s.status = "error"
            s.error_message = message

    # ------------------------------------------------------------------
    # Internal helpers (must be called with _lock held)
    # ------------------------------------------------------------------

    def _evict_locked(self) -> None:
        now = time.time()
        expired = [sid for sid, s in self._by_session.items() if s.expires_at <= now]
        for sid in expired:
            s = self._by_session.pop(sid)
            if s.auth_code:
                self._by_code.pop(s.auth_code, None)
