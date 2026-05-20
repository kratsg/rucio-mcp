"""Per-session rucio client cache with JWT exp-based TTL eviction."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rucio.client import Client


class SessionCache:
    """Thread-safe cache of rucio Clients keyed by MCP session ID.

    Each entry expires at the JWT exp epoch of the access token used to
    create it, so a new TokenInjectedClient is built once per session and
    evicted when the token expires.
    """

    def __init__(self) -> None:
        """Initialise an empty cache with a threading lock."""
        self._lock = threading.Lock()
        self._data: dict[str, tuple[Client, float]] = {}

    def get(self, session_id: str) -> Client | None:
        """Return the cached client if present and unexpired, else None."""
        with self._lock:
            entry = self._data.get(session_id)
            if entry is None:
                return None
            client, exp = entry
            if exp < time.time():
                del self._data[session_id]
                return None
            return client

    def put(self, session_id: str, client: Client, expires_at: float) -> None:
        """Store a client under session_id, expiring at the given epoch."""
        with self._lock:
            self._data[session_id] = (client, expires_at)

    def close(self) -> None:
        """Evict all cached clients."""
        with self._lock:
            self._data.clear()
