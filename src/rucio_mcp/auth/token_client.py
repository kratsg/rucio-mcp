"""TokenInjectedClient: a rucio Client that uses a pre-acquired bearer token."""

from __future__ import annotations

import logging

from rucio.client import Client
from rucio.common.exception import CannotAuthenticate

_log = logging.getLogger(__name__)


class TokenInjectedClient(Client):
    """A rucio Client that uses a pre-acquired bearer token verbatim.

    Bypasses the auth-server round-trip; never reads or writes disk token
    caches. Multi-tenant safe: no shared state across instances.

    On 401 (token expired/rejected), raises CannotAuthenticate — the MCP
    client must re-acquire a token and reconnect.
    """

    def __init__(
        self,
        *,
        bearer_token: str,
        account: str,
        rucio_host: str | None = None,
        auth_host: str | None = None,
        auth_type: str = "oidc",
    ) -> None:
        """Store the bearer token before super().__init__ triggers authentication."""
        self._injected_bearer = bearer_token
        super().__init__(
            rucio_host=rucio_host,
            auth_host=auth_host,
            auth_type=auth_type,
            account=account,
            creds={"oidc_auto": False},
        )

    def _BaseClient__authenticate(self) -> None:  # pylint: disable=invalid-name
        self.auth_token = self._injected_bearer
        self.headers["X-Rucio-Auth-Token"] = self.auth_token

    def _BaseClient__get_token(self) -> None:  # pylint: disable=invalid-name
        _log.warning(
            "__get_token called — Rucio returned 401 for bearer prefix=%s…; "
            "token is expired or rejected",
            self._injected_bearer[:12],
        )
        msg = (
            "Bearer token expired or rejected by Rucio. "
            "Re-acquire via the MCP OAuth flow and reconnect."
        )
        raise CannotAuthenticate(msg)
