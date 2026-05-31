"""Tests for TokenInjectedClient."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from rucio.client import Client
from rucio.common.exception import CannotAuthenticate

from rucio_mcp.auth.token_client import TokenInjectedClient


class TestTokenInjectedClientMethods:
    def test_authenticate_sets_auth_token(self) -> None:
        """_BaseClient__authenticate injects the bearer into auth_token and headers."""
        instance = MagicMock()
        instance._injected_bearer = "test-bearer-token"
        instance.headers = {}

        authenticate = TokenInjectedClient._BaseClient__authenticate
        authenticate(instance)

        assert instance.auth_token == "test-bearer-token"
        assert instance.headers["X-Rucio-Auth-Token"] == "test-bearer-token"

    def test_get_token_raises_cannot_authenticate(self) -> None:
        """_BaseClient__get_token raises CannotAuthenticate — bearer is immutable."""
        instance = MagicMock()
        get_token = TokenInjectedClient._BaseClient__get_token

        with pytest.raises(CannotAuthenticate):
            get_token(instance)

    def test_injected_bearer_stored_before_super_init(self) -> None:
        """_injected_bearer is available before super().__init__ triggers __authenticate."""
        captured: dict[str, str] = {}

        original_authenticate = TokenInjectedClient._BaseClient__authenticate

        def spy_authenticate(self: Any) -> None:
            captured["bearer"] = self._injected_bearer
            original_authenticate(self)

        with (
            patch.object(Client, "__init__", lambda _s, **_kw: None),
            patch.object(
                TokenInjectedClient,
                "_BaseClient__authenticate",
                spy_authenticate,
            ),
        ):
            client = TokenInjectedClient(bearer_token="secret", account="alice")

        assert client._injected_bearer == "secret"

    def test_explicit_host_args_forwarded_to_super(self) -> None:
        """rucio_host, auth_host, auth_type are forwarded to the super().__init__ call."""
        captured: dict[str, Any] = {}

        def fake_init(_self: Any, **kw: Any) -> None:
            captured.update(kw)

        with patch.object(Client, "__init__", fake_init):
            TokenInjectedClient(
                bearer_token="tok",
                account="bob",
                rucio_host="https://rucio.example.com",
                auth_host="https://auth.example.com",
                auth_type="oidc",
            )

        assert captured["rucio_host"] == "https://rucio.example.com"
        assert captured["auth_host"] == "https://auth.example.com"
        assert captured["auth_type"] == "oidc"
