"""Tests for JWT identity extraction used to label per-user metrics."""

from __future__ import annotations

import base64
import json

from rucio_mcp.auth.identity import decode_jwt_claims, user_label


def _make_jwt(payload: dict) -> str:
    """Build a minimal (unsigned) JWT string for testing."""
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    body = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    )
    return f"{header}.{body}.fakesig"


class TestDecodeJwtClaims:
    def test_decodes_standard_claims(self) -> None:
        token = _make_jwt({"sub": "alice", "iss": "https://idp.example.com"})
        claims = decode_jwt_claims(token)
        assert claims["sub"] == "alice"
        assert claims["iss"] == "https://idp.example.com"

    def test_returns_empty_dict_for_opaque_string(self) -> None:
        assert decode_jwt_claims("opaque-rucio-token") == {}

    def test_returns_empty_dict_for_empty_string(self) -> None:
        assert decode_jwt_claims("") == {}

    def test_returns_empty_dict_for_malformed_payload(self) -> None:
        # Valid base64 but not JSON
        header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
        bad = base64.urlsafe_b64encode(b"not-json").rstrip(b"=").decode()
        assert decode_jwt_claims(f"{header}.{bad}.sig") == {}

    def test_returns_empty_dict_when_payload_missing_padding(self) -> None:
        # A JWT where padding stripping works without error
        token = _make_jwt({"sub": "bob"})
        claims = decode_jwt_claims(token)
        assert claims.get("sub") == "bob"


class TestUserLabel:
    def test_prefers_preferred_username(self) -> None:
        token = _make_jwt({"sub": "uid123", "preferred_username": "alice"})
        assert user_label(token) == "alice"

    def test_falls_back_to_sub(self) -> None:
        token = _make_jwt({"sub": "uid123"})
        assert user_label(token) == "uid123"

    def test_returns_unknown_for_opaque_token(self) -> None:
        assert user_label("opaque-token") == "unknown"

    def test_returns_unknown_for_empty_string(self) -> None:
        assert user_label("") == "unknown"

    def test_returns_unknown_when_no_identifying_claim(self) -> None:
        token = _make_jwt({"iss": "https://idp.example.com", "aud": "rucio"})
        assert user_label(token) == "unknown"
