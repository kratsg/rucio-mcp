"""JWT verifier that validates bearer tokens against an IdP's JWKS endpoint."""

from __future__ import annotations

import jwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken, TokenVerifier


class JWKSTokenVerifier(TokenVerifier):
    """Verify MCP bearer tokens against a JWKS-advertised public key.

    Checks RS256 signature, issuer, audience (any-of), and required scopes.
    Full validation only — no token introspection, no client secret.
    """

    def __init__(
        self,
        *,
        jwks_uri: str,
        issuer: str,
        accepted_audiences: list[str],
        required_scopes: list[str],
    ) -> None:
        self._jwks_client = PyJWKClient(jwks_uri, cache_keys=True)
        self._issuer = issuer
        self._accepted_audiences = list(accepted_audiences)
        self._required_scopes = set(required_scopes)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token).key
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._accepted_audiences,
                options={"require": ["exp", "aud", "iss"]},
            )
        except jwt.PyJWTError:
            return None

        scopes = set((payload.get("scope") or "").split())
        if not self._required_scopes.issubset(scopes):
            return None

        return AccessToken(
            token=token,
            client_id=payload.get("azp") or payload.get("client_id", "unknown"),
            scopes=list(scopes),
            expires_at=payload["exp"],
            resource=payload.get("aud"),
        )
