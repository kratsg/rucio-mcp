"""Integration tests against a live Rucio instance.

These tests require a valid Rucio environment (authentication, network access).
Run with: ``pixi run test-slow``

Setup on UChicago Analysis Facility (or any site with Rucio + VOMS):
  1. Ensure rucio.cfg is configured (typically in $RUCIO_HOME/etc/rucio.cfg
     or /etc/rucio.cfg) with the correct rucio_host and auth_host.
  2. Set RUCIO_ACCOUNT to your ATLAS account (e.g. ``export RUCIO_ACCOUNT=gstark``).
  3. For x509_proxy auth: run ``voms-proxy-init -voms atlas`` and set
     ``export RUCIO_AUTH_TYPE=x509_proxy``.
  4. Verify setup: ``rucio whoami`` should return your account name.

Then run: ``pixi run test-slow``
"""

from __future__ import annotations

import pytest
from rucio.client import Client


@pytest.mark.slow
def test_rucio_client_importable() -> None:
    """Rucio client library must be importable."""
    assert Client is not None


@pytest.mark.slow
def test_ping() -> None:
    """Live ping to the configured Rucio server."""
    client = Client()
    result = client.ping()
    assert result is not None


@pytest.mark.slow
def test_whoami() -> None:
    """Live whoami — requires valid authentication."""
    client = Client()
    result = client.whoami()
    assert "account" in result


@pytest.mark.slow
def test_list_scopes() -> None:
    """Live scope listing — returns the full scope list."""
    client = Client()
    scopes = client.list_scopes()
    assert len(scopes) > 0
    assert "mc16_13TeV" in scopes or any("mc" in s for s in scopes)
