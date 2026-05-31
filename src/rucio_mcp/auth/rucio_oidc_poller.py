"""Async wrapper around Rucio's /auth/oidc polling flow.

Mirrors what baseclient.py:634-674 does but uses httpx.AsyncClient so it
can run inside an asyncio event loop without blocking the server.
"""

from __future__ import annotations

import asyncio
import logging
import os
import ssl
from dataclasses import dataclass
from pathlib import Path

import httpx

_log = logging.getLogger(__name__)


def _ssl_context() -> ssl.SSLContext | bool:
    """Return an SSL context using X509_CERT_DIR if set, otherwise True (system CAs).

    Rucio auth servers at CERN use a certificate chain that is not in the
    standard system CA bundle.  The rucio client resolves this via X509_CERT_DIR;
    we do the same so the httpx poller can verify those certificates.
    """
    cert_dir = os.environ.get("X509_CERT_DIR")
    if cert_dir and Path(cert_dir).is_dir():
        ctx = ssl.create_default_context()
        ctx.load_verify_locations(capath=cert_dir)
        return ctx
    return True


@dataclass
class RucioOidcPoller:
    """Orchestrates the two-step Rucio OIDC flow for a single account.

    Step 1 — :meth:`request_auth_url`: GET /auth/oidc with polling headers;
    the Rucio auth server returns the IdP redirect URL in
    ``X-Rucio-OIDC-Auth-URL``. The URL already has a ``_polling`` suffix.

    Step 2 — :meth:`poll_for_token`: repeatedly GET that URL with
    ``X-Rucio-Client-Fetch-Token: True`` until Rucio mints a session token
    (``X-Rucio-Auth-Token`` response header) or the timeout is reached.
    """

    auth_host: str
    account: str
    oidc_audience: str
    oidc_scope: str
    oidc_issuer: str

    def _base_headers(self) -> dict[str, str]:
        h: dict[str, str] = {
            "X-Rucio-Account": self.account,
            "X-Rucio-Client-Authorize-Auto": "False",
            "X-Rucio-Client-Authorize-Polling": "True",
            "X-Rucio-Client-Authorize-Scope": self.oidc_scope,
            "X-Rucio-Client-Authorize-Refresh-Lifetime": "96",
        }
        if self.oidc_audience:
            h["X-Rucio-Client-Authorize-Audience"] = self.oidc_audience
        if self.oidc_issuer:
            h["X-Rucio-Client-Authorize-Issuer"] = self.oidc_issuer
        return h

    async def request_auth_url(self) -> str:
        """GET /auth/oidc and return the polling URL from the response header."""
        _log.info("Requesting OIDC auth URL from %s for account %s", self.auth_host, self.account)
        async with httpx.AsyncClient(
            base_url=self.auth_host, timeout=30.0, verify=_ssl_context()
        ) as client:
            response = await client.get("/auth/oidc", headers=self._base_headers())
            response.raise_for_status()
            url = response.headers.get("X-Rucio-OIDC-Auth-URL")
            if not url:
                raise RuntimeError(
                    "Rucio auth server returned no X-Rucio-OIDC-Auth-URL"
                )
            _log.info("Got OIDC auth URL (polling suffix expected): %s", url)
            return url

    async def poll_for_token(
        self,
        polling_url: str,
        *,
        timeout: float = 180.0,
        interval: float = 2.0,
    ) -> str:
        """Poll *polling_url* until Rucio issues a session token or *timeout* expires.

        Returns the value of ``X-Rucio-Auth-Token`` from the response header.
        Raises :exc:`asyncio.TimeoutError` if the token is not received within
        *timeout* seconds.
        """
        headers = {**self._base_headers(), "X-Rucio-Client-Fetch-Token": "True"}

        _log.info("Starting token poll (timeout=%.0fs, interval=%.1fs)", timeout, interval)

        async def _loop() -> str:
            attempt = 0
            async with httpx.AsyncClient(timeout=30.0, verify=_ssl_context()) as client:
                while True:
                    attempt += 1
                    response = await client.get(polling_url, headers=headers)
                    token = response.headers.get("X-Rucio-Auth-Token")
                    if response.status_code == 200 and token:
                        _log.info("Rucio session token received after %d poll(s)", attempt)
                        return token
                    _log.debug("Poll %d: no token yet (status=%d)", attempt, response.status_code)
                    await asyncio.sleep(interval)

        return await asyncio.wait_for(_loop(), timeout=timeout)
