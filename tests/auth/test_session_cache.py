"""Tests for SessionCache."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock


class TestSessionCache:
    def test_put_and_get_round_trip(self) -> None:
        from rucio_mcp.auth.session_cache import SessionCache

        cache = SessionCache()
        client = MagicMock()
        cache.put("sid-1", client, time.time() + 3600)
        assert cache.get("sid-1") is client

    def test_get_returns_none_for_unknown_session(self) -> None:
        from rucio_mcp.auth.session_cache import SessionCache

        cache = SessionCache()
        assert cache.get("no-such-session") is None

    def test_expired_entry_is_evicted_on_get(self) -> None:
        from rucio_mcp.auth.session_cache import SessionCache

        cache = SessionCache()
        client = MagicMock()
        # expires in the past
        cache.put("sid-expired", client, time.time() - 1)
        assert cache.get("sid-expired") is None

    def test_close_clears_all_entries(self) -> None:
        from rucio_mcp.auth.session_cache import SessionCache

        cache = SessionCache()
        cache.put("a", MagicMock(), time.time() + 3600)
        cache.put("b", MagicMock(), time.time() + 3600)
        cache.close()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_concurrent_access_does_not_corrupt(self) -> None:
        from rucio_mcp.auth.session_cache import SessionCache

        cache = SessionCache()
        errors: list[Exception] = []

        def writer(i: int) -> None:
            try:
                client = MagicMock()
                cache.put(f"sid-{i}", client, time.time() + 3600)
                result = cache.get(f"sid-{i}")
                assert result is client
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
