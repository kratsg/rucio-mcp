"""TokenInjectedClient: a rucio Client that uses a pre-acquired bearer token."""

from __future__ import annotations

from rucio.client import Client
from rucio.common.exception import CannotAuthenticate


class TokenInjectedClient(Client):
    """A rucio Client that uses a pre-acquired bearer token verbatim.

    Bypasses the auth-server round-trip; never reads or writes disk token
    caches. Multi-tenant safe: no shared state across instances.

    On 401 (token expired/rejected), raises CannotAuthenticate — the MCP
    client must re-acquire a token and reconnect.
    """

    def __init__(self, *, bearer_token: str, account: str, **kwargs: object) -> None:
        self._injected_bearer = bearer_token
        super().__init__(
            auth_type="oidc",
            account=account,
            creds={"oidc_auto": False},
            **kwargs,
        )

    def _BaseClient__authenticate(self) -> None:  # type: ignore[override]
        self.auth_token = self._injected_bearer
        self.headers["X-Rucio-Auth-Token"] = self.auth_token

    def _BaseClient__get_token(self) -> None:  # type: ignore[override]
        raise CannotAuthenticate(
            "Bearer token expired or rejected by Rucio. "
            "Re-acquire via the MCP OAuth flow and reconnect."
        )
