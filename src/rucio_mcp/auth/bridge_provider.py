"""RucioBridgeProvider — OAuthAuthorizationServerProvider for the rucio polling bridge.

MCP clients speak standard auth-code+PKCE and are identified via CIMD (Client ID
Metadata Documents — an https client_id URL; no DCR). This provider bridges that
to Rucio's custom /auth/oidc polling flow and returns the resulting Rucio session
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
import base64
import contextvars
import json as _json
import logging
import secrets
import threading
import time
from typing import Protocol, runtime_checkable
from urllib.parse import parse_qs, urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from rucio_mcp.auth.bridge_state import BridgeSession, BridgeStateStore
from rucio_mcp.auth.cimd import CimdError, is_cimd_client_id, resolve_cimd_client
from rucio_mcp.metrics import BRIDGE_AUTH

_log = logging.getLogger(__name__)

# Set by _AuthorizeContextMiddleware (server.py) for the duration of each
# /authorize request.  Gives _resolve_cimd() the requested redirect_uri so a
# CIMD client's ephemeral-port loopback redirect can be matched port-agnostically
# against its Client ID Metadata Document.
_authorize_redirect_uri: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_authorize_redirect_uri", default=None
)

_DEFAULT_EXPIRES_IN = 3600  # fallback when token is opaque or has no exp claim


def _jwt_expires_in(token: str) -> int:
    """Return seconds until the JWT expires, or _DEFAULT_EXPIRES_IN for opaque tokens."""
    parts = token.split(".")
    if len(parts) != 3:
        return _DEFAULT_EXPIRES_IN
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(padded))
        exp = payload.get("exp")
        if exp is None:
            return _DEFAULT_EXPIRES_IN
        remaining = int(exp) - int(time.time())
        return max(remaining, 0)
    except Exception:  # noqa: BLE001
        return _DEFAULT_EXPIRES_IN


@runtime_checkable
class BridgePoller(Protocol):
    """Structural protocol for rucio auth-polling back-ends.

    Both ``request_auth_url`` and ``poll_for_token`` are async; the concrete
    implementation today is :class:`~rucio_mcp.auth.rucio_oidc_poller.RucioOidcPoller`.
    """

    auth_host: str

    async def request_auth_url(self, *, account: str | None = None) -> str:
        """Initiate the auth flow and return the URL the user must open."""

    async def poll_for_token(
        self, polling_url: str, *, account: str | None = None, timeout: float = 180.0
    ) -> str:
        """Poll until a rucio session token is available and return it."""


class RucioBridgeProvider:
    """Implements :class:`OAuthAuthorizationServerProvider` via rucio's polling flow.

    One instance per site; shared state is in :attr:`store` and ``_clients``.
    The caller constructs the :class:`BridgePoller` (e.g. :class:`RucioOidcPoller`)
    and passes it in; the provider is auth-back-end agnostic.
    """

    def __init__(
        self,
        *,
        poller: BridgePoller,
        resource_url: str,
        poll_timeout: float = 180.0,
        site_name: str = "",
    ) -> None:
        """Initialize rucio bridge provider.

        *site_name* labels the auth-outcome Prometheus counter.  Pass the
        site identifier (e.g. ``"atlas"``) for hosted deployments; leave
        empty in tests that don't care about metrics.
        """
        self._resource_url = resource_url.rstrip("/")
        self._poller = poller
        self._poll_timeout = poll_timeout
        self._site_name = site_name
        self.store = BridgeStateStore()
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._clients_lock = threading.Lock()
        self._bg_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # Client identity (CIMD only — no DCR)
    # ------------------------------------------------------------------

    async def register_client(self, _client_info: OAuthClientInformationFull) -> None:
        """Not supported: this server identifies clients via CIMD, not DCR.

        Dynamic Client Registration is disabled
        (``ClientRegistrationOptions(enabled=False)`` in server.py) so the SDK
        never routes a ``/register`` request here.  The provider protocol allows
        raising :class:`NotImplementedError` when DCR is unsupported.
        """
        msg = (
            "Dynamic Client Registration is not supported; use CIMD "
            "(an https client_id URL)"
        )
        raise NotImplementedError(msg)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Resolve a CIMD client_id URL to its client information.

        1. In-memory cache hit (a previously-resolved CIMD client).
        2. CIMD: if ``client_id`` is an https URL, dereference it (Client ID
           Metadata Document) and cache the result.
        3. Otherwise unknown → ``None`` (the SDK emits "Client ID not found").
        """
        with self._clients_lock:
            client = self._clients.get(client_id)
        if client is not None:
            _log.debug(
                "[%s] get_client: hit for client_id=%s", self._site_name, client_id
            )
            return client

        if is_cimd_client_id(client_id):
            return await self._resolve_cimd(client_id)

        _log.debug(
            "[%s] get_client: miss for non-CIMD client_id=%s",
            self._site_name,
            client_id,
        )
        return None

    async def _resolve_cimd(self, client_id: str) -> OAuthClientInformationFull | None:
        """Dereference a CIMD client_id URL, caching the resolved public client.

        The requested redirect_uri is taken from the ``_authorize_redirect_uri``
        contextvar (set by ``_AuthorizeContextMiddleware`` during /authorize) so
        an ephemeral-port loopback redirect can be matched port-agnostically.
        On the /token leg the contextvar is unset, but the client resolved during
        /authorize is already cached, so no re-fetch is needed.
        """
        redirect_uri = _authorize_redirect_uri.get()
        try:
            resolved = await resolve_cimd_client(client_id, redirect_uri)
        except CimdError as exc:
            _log.warning(
                "[%s] get_client: CIMD resolution failed for client_id=%s: %s",
                self._site_name,
                client_id,
                exc,
            )
            return None
        with self._clients_lock:
            self._clients[client_id] = resolved
        _log.debug(
            "[%s] get_client: resolved CIMD client_id=%s", self._site_name, client_id
        )
        return resolved

    # ------------------------------------------------------------------
    # Authorization flow
    # ------------------------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Start the rucio OIDC polling flow and return the interstitial /bridge URL."""
        account = ""
        if params.resource:
            qs = parse_qs(urlparse(params.resource).query)
            account_vals = qs.get("account", [])
            if account_vals:
                account = account_vals[0]
        try:
            polling_url = await self._poller.request_auth_url(account=account or None)
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
            account=account,
        )
        self.store.put(session)
        BRIDGE_AUTH.labels(site=self._site_name, outcome="started").inc()
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
            token = await self._poller.poll_for_token(
                session.polling_url,
                account=session.account or None,
                timeout=self._poll_timeout,
            )
            auth_code = secrets.token_urlsafe(32)
            self.store.mark_done(session_id, rucio_token=token, auth_code=auth_code)
            BRIDGE_AUTH.labels(site=self._site_name, outcome="success").inc()
            _log.info("Bridge session %s: authentication complete", session_id[:8])
        except asyncio.TimeoutError:
            _log.error("Bridge session %s: polling timed out", session_id[:8])
            self.store.mark_error(session_id, "polling timed out")
            BRIDGE_AUTH.labels(site=self._site_name, outcome="timeout").inc()
        except Exception as exc:  # noqa: BLE001
            _log.error("Bridge session %s: polling failed: %s", session_id[:8], exc)
            self.store.mark_error(session_id, str(exc))
            BRIDGE_AUTH.labels(site=self._site_name, outcome="failure").inc()

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
        expires_in = _jwt_expires_in(session.rucio_token)
        _log.debug("exchange_authorization_code: expires_in=%ds", expires_in)
        return OAuthToken(
            access_token=session.rucio_token,
            token_type="Bearer",
            expires_in=expires_in,
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
        _log.debug("load_access_token called, token prefix=%s…", token[:12])
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
