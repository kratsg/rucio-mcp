"""Tests for TokenInjectedClient."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestTokenInjectedClientMethods:
    def test_authenticate_sets_auth_token(self) -> None:
        """_BaseClient__authenticate injects the bearer into auth_token and headers."""
        from rucio_mcp.auth.token_client import TokenInjectedClient

        instance = MagicMock()
        instance._injected_bearer = "test-bearer-token"
        instance.headers = {}

        TokenInjectedClient._BaseClient__authenticate(instance)  # type: ignore[attr-defined]

        assert instance.auth_token == "test-bearer-token"
        assert instance.headers["X-Rucio-Auth-Token"] == "test-bearer-token"

    def test_get_token_raises_cannot_authenticate(self) -> None:
        """_BaseClient__get_token raises CannotAuthenticate — bearer is immutable."""
        from rucio.common.exception import CannotAuthenticate

        from rucio_mcp.auth.token_client import TokenInjectedClient

        instance = MagicMock()

        with pytest.raises(CannotAuthenticate):
            TokenInjectedClient._BaseClient__get_token(instance)  # type: ignore[attr-defined]

    def test_injected_bearer_stored_before_super_init(self) -> None:
        """_injected_bearer is available before super().__init__ triggers __authenticate."""
        from unittest.mock import patch

        from rucio.client import Client

        from rucio_mcp.auth.token_client import TokenInjectedClient

        captured: dict[str, str] = {}

        original_authenticate = TokenInjectedClient._BaseClient__authenticate  # type: ignore[attr-defined]

        def spy_authenticate(self: object) -> None:
            captured["bearer"] = self._injected_bearer  # type: ignore[attr-defined]
            original_authenticate(self)

        with (
            patch.object(Client, "__init__", lambda self, **kwargs: None),
            patch.object(
                TokenInjectedClient,
                "_BaseClient__authenticate",
                spy_authenticate,
            ),
        ):
            client = TokenInjectedClient(bearer_token="secret", account="alice")

        assert client._injected_bearer == "secret"
