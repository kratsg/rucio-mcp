"""Tests for SharedSecretVerifier."""

from __future__ import annotations

from mcp.server.auth.provider import AccessToken

from rucio_mcp.auth.shared_secret import SharedSecretVerifier


class TestSharedSecretVerifier:
    async def test_correct_secret_returns_access_token(self) -> None:
        """A token matching the secret yields an AccessToken wrapping it."""
        verifier = SharedSecretVerifier("s3cr3t")

        result = await verifier.verify_token("s3cr3t")

        assert isinstance(result, AccessToken)
        assert result.token == "s3cr3t"
        assert result.client_id == "shared-secret"

    async def test_wrong_secret_returns_none(self) -> None:
        """A token not matching the secret is rejected with None."""
        verifier = SharedSecretVerifier("s3cr3t")

        assert await verifier.verify_token("wrong") is None

    async def test_empty_token_returns_none(self) -> None:
        """An empty token is rejected even though the secret is non-empty."""
        verifier = SharedSecretVerifier("s3cr3t")

        assert await verifier.verify_token("") is None
