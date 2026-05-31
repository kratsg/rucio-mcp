"""RucioBridgeProvider — OAuthAuthorizationServerProvider for the rucio polling bridge.

MCP clients speak standard auth-code+PKCE+DCR. This provider bridges that to
Rucio's custom /auth/oidc polling flow and returns the resulting Rucio session
token to the MCP client as the OAuth access_token.

Flow:
  authorize()      → kicks off rucio /auth/oidc + starts bg poll task
  /bridge page     → user opens the rucio IdP URL in browser, logs in
  _bg_poll()       → receives X-Rucio-Auth-Token, mints local auth_code
  /bridge/status   → JS polls until status=done, redirects to redirect_uri
  /token exchange  → returns rucio session token as access_token (passthrough)
  MCP tool calls   → bearer = rucio session token → TokenInjectedClient
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import threading
import time
from typing import Protocol, runtime_checkable

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from rucio_mcp.auth.bridge_state import BridgeSession, BridgeStateStore

_log = logging.getLogger(__name__)


@runtime_checkable
class BridgePoller(Protocol):
    """Structural protocol for rucio auth-polling back-ends.

    Both ``request_auth_url`` and ``poll_for_token`` are async; the concrete
    implementation today is :class:`~rucio_mcp.auth.rucio_oidc_poller.RucioOidcPoller`.
    """

    auth_host: str

    async def request_auth_url(self) -> str:
        """Initiate the auth flow and return the URL the user must open."""

    async def poll_for_token(self, polling_url: str) -> str:
        """Poll until a rucio session token is available and return it."""


class RucioBridgeProvider:
    """Implements :class:`OAuthAuthorizationServerProvider` via rucio's polling flow.

    One instance per site; shared state is in :attr:`store` and ``_clients``.
    The caller constructs the :class:`BridgePoller` (e.g. :class:`RucioOidcPoller`)
    and passes it in; the provider is auth-back-end agnostic.
    """

    def __init__(self, *, poller: BridgePoller, resource_url: str) -> None:
        """Initialize rucio bridge provider."""
        self._resource_url = resource_url.rstrip("/")
        self._poller = poller
        self.store = BridgeStateStore()
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._clients_lock = threading.Lock()
        self._bg_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # Client registry (in-memory DCR)
    # ------------------------------------------------------------------

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Store a dynamically registered client."""
        with self._clients_lock:
            self._clients[client_info.client_id or ""] = client_info

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Look up a previously registered client."""
        with self._clients_lock:
            return self._clients.get(client_id)

    # ------------------------------------------------------------------
    # Authorization flow
    # ------------------------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Start the rucio OIDC polling flow and return the interstitial /bridge URL."""
        try:
            polling_url = await self._poller.request_auth_url()
        except Exception as exc:
            _log.error(
                "Failed to reach Rucio auth server (%s): %s — "
                "check auth_host in rucio.cfg and that X509_CERT_DIR is set",
                self._poller.auth_host,
                exc,
            )
            raise
        session_id = secrets.token_urlsafe(32)
        session = BridgeSession(
            session_id=session_id,
            polling_url=polling_url,
            code_challenge=params.code_challenge,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            client_id=client.client_id or "",
            scopes=params.scopes or [],
            resource=params.resource,
            state=params.state,
            expires_at=time.time() + 300,
        )
        self.store.put(session)
        _log.info(
            "Bridge session %s started for client %s", session_id[:8], client.client_id
        )
        task = asyncio.create_task(self._bg_poll(session_id))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return f"{self._resource_url}/bridge?session={session_id}"

    async def _bg_poll(self, session_id: str) -> None:
        """Background task: poll rucio for the session token, then mark done/error."""
        session = self.store.get_by_session_id(session_id)
        if session is None:
            return
        try:
            token = await self._poller.poll_for_token(session.polling_url)
            auth_code = secrets.token_urlsafe(32)
            self.store.mark_done(session_id, rucio_token=token, auth_code=auth_code)
            _log.info("Bridge session %s: authentication complete", session_id[:8])
        except Exception as exc:  # noqa: BLE001
            _log.error("Bridge session %s: polling failed: %s", session_id[:8], exc)
            self.store.mark_error(session_id, str(exc))

    async def load_authorization_code(
        self, _client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        """Return an :class:`AuthorizationCode` if *authorization_code* maps to a done session."""
        session = self.store.get_by_auth_code(authorization_code)
        if session is None or session.status != "done":
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=session.scopes,
            expires_at=session.expires_at,
            client_id=session.client_id,
            code_challenge=session.code_challenge,
            redirect_uri=session.redirect_uri,  # type: ignore[arg-type]
            redirect_uri_provided_explicitly=session.redirect_uri_provided_explicitly,
            resource=session.resource,
        )

    async def exchange_authorization_code(
        self, _client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Return the rucio session token verbatim as the OAuth access_token."""
        session = self.store.get_by_auth_code(authorization_code.code)
        if session is None or session.rucio_token is None:
            raise TokenError(
                error="invalid_grant",
                error_description="Authorization code not found or expired",
            )
        return OAuthToken(
            access_token=session.rucio_token,
            token_type="Bearer",
            expires_in=300,
            refresh_token=None,
        )

    # ------------------------------------------------------------------
    # Access / refresh token handling
    # ------------------------------------------------------------------

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Return a synthetic AccessToken wrapping the rucio session token.

        No signature validation is performed — the bearer IS the rucio session
        token and Rucio will reject it with 401 if it is invalid.
        """
        return AccessToken(
            token=token,
            client_id="rucio-bridge",
            scopes=[],
            expires_at=None,
        )

    async def load_refresh_token(
        self, _client: OAuthClientInformationFull, _refresh_token: str
    ) -> RefreshToken | None:
        """Refresh tokens are not issued in v1; always returns None."""
        return None

    async def exchange_refresh_token(
        self,
        _client: OAuthClientInformationFull,
        _refresh_token: RefreshToken,
        _scopes: list[str],
    ) -> OAuthToken:
        """Refresh tokens are not supported; always raises."""
        raise TokenError(
            error="unsupported_grant_type",
            error_description="Refresh tokens are not supported; re-authenticate",
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """No-op: Rucio does not expose a token revocation endpoint."""
