"""Tests for JWKSTokenVerifier."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey


@pytest.fixture(scope="module")
def rsa_keys() -> tuple[RSAPrivateKey, RSAPublicKey]:
    """Generate a test RSA key pair (once per module for speed)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _make_token(
    private_key: RSAPrivateKey,
    *,
    iss: str = "https://example.com/",
    aud: str = "rucio",
    sub: str = "alice",
    scope: str = "openid profile",
    azp: str = "client-id-123",
    exp_offset: int = 3600,
) -> str:
    payload: dict[str, Any] = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "scope": scope,
        "azp": azp,
        "iat": int(time.time()),
        "exp": int(time.time()) + exp_offset,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


def _make_verifier_with_mock_jwks(
    public_key: RSAPublicKey,
    *,
    issuer: str = "https://example.com/",
    accepted_audiences: list[str] | None = None,
    required_scopes: list[str] | None = None,
) -> Any:
    from rucio_mcp.auth.jwks_verifier import JWKSTokenVerifier

    if accepted_audiences is None:
        accepted_audiences = ["rucio"]
    if required_scopes is None:
        required_scopes = ["openid"]

    verifier = JWKSTokenVerifier(
        jwks_uri="https://example.com/jwk",
        issuer=issuer,
        accepted_audiences=accepted_audiences,
        required_scopes=required_scopes,
    )
    mock_signing_key = MagicMock()
    mock_signing_key.key = public_key
    verifier._jwks_client.get_signing_key_from_jwt = MagicMock(
        return_value=mock_signing_key
    )
    return verifier


class TestJWKSTokenVerifier:
    @pytest.mark.asyncio
    async def test_valid_token_returns_access_token(
        self, rsa_keys: tuple[RSAPrivateKey, RSAPublicKey]
    ) -> None:
        private_key, public_key = rsa_keys
        token = _make_token(private_key)
        verifier = _make_verifier_with_mock_jwks(public_key)

        result = await verifier.verify_token(token)

        assert result is not None
        assert result.client_id == "client-id-123"
        assert "openid" in result.scopes
        assert result.expires_at is not None

    @pytest.mark.asyncio
    async def test_wrong_issuer_returns_none(
        self, rsa_keys: tuple[RSAPrivateKey, RSAPublicKey]
    ) -> None:
        private_key, public_key = rsa_keys
        token = _make_token(private_key, iss="https://wrong.example.com/")
        verifier = _make_verifier_with_mock_jwks(
            public_key, issuer="https://example.com/"
        )

        result = await verifier.verify_token(token)

        assert result is None

    @pytest.mark.asyncio
    async def test_wrong_audience_returns_none(
        self, rsa_keys: tuple[RSAPrivateKey, RSAPublicKey]
    ) -> None:
        private_key, public_key = rsa_keys
        token = _make_token(private_key, aud="not-rucio")
        verifier = _make_verifier_with_mock_jwks(
            public_key, accepted_audiences=["rucio"]
        )

        result = await verifier.verify_token(token)

        assert result is None

    @pytest.mark.asyncio
    async def test_missing_required_scope_returns_none(
        self, rsa_keys: tuple[RSAPrivateKey, RSAPublicKey]
    ) -> None:
        private_key, public_key = rsa_keys
        token = _make_token(private_key, scope="profile email")  # no "openid"
        verifier = _make_verifier_with_mock_jwks(
            public_key, required_scopes=["openid"]
        )

        result = await verifier.verify_token(token)

        assert result is None

    @pytest.mark.asyncio
    async def test_expired_token_returns_none(
        self, rsa_keys: tuple[RSAPrivateKey, RSAPublicKey]
    ) -> None:
        private_key, public_key = rsa_keys
        token = _make_token(private_key, exp_offset=-10)  # expired 10s ago
        verifier = _make_verifier_with_mock_jwks(public_key)

        result = await verifier.verify_token(token)

        assert result is None

    @pytest.mark.asyncio
    async def test_malformed_token_returns_none(self) -> None:
        from rucio_mcp.auth.jwks_verifier import JWKSTokenVerifier

        verifier = JWKSTokenVerifier(
            jwks_uri="https://example.com/jwk",
            issuer="https://example.com/",
            accepted_audiences=["rucio"],
            required_scopes=["openid"],
        )

        result = await verifier.verify_token("not.a.token")

        assert result is None

    @pytest.mark.asyncio
    async def test_client_id_falls_back_to_unknown(
        self, rsa_keys: tuple[RSAPrivateKey, RSAPublicKey]
    ) -> None:
        private_key, public_key = rsa_keys
        # Token without azp or client_id
        payload = {
            "iss": "https://example.com/",
            "aud": "rucio",
            "sub": "alice",
            "scope": "openid",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, private_key, algorithm="RS256")
        verifier = _make_verifier_with_mock_jwks(public_key)

        result = await verifier.verify_token(token)

        assert result is not None
        assert result.client_id == "unknown"
