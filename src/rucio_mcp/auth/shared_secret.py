"""Static shared-secret bearer verification for HTTP transport.

In shared-secret mode the server exposes a single pre-authenticated rucio client
(built from env vars, like stdio) over HTTP, gated by a server-wide bearer
secret.  This module provides the FastMCP ``TokenVerifier`` that checks incoming
bearer tokens against that secret; no OAuth bridge is involved.
"""

from __future__ import annotations

import secrets

from mcp.server.auth.provider import AccessToken, TokenVerifier


class SharedSecretVerifier(TokenVerifier):
    """Verify the static server-wide bearer secret in constant time."""

    def __init__(self, secret: str) -> None:
        """Store the shared secret every request must present."""
        self._secret = secret

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return an AccessToken if *token* matches the secret, else None."""
        if secrets.compare_digest(token, self._secret):
            return AccessToken(
                token=token,
                client_id="shared-secret",
                scopes=[],
                expires_at=None,
            )
        return None
