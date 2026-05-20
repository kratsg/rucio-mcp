"""Verify that an ATLAS IAM OIDC token works end-to-end with Rucio.

This script tests the exact code path that rucio-mcp HTTP mode uses:
  1. Decode the token claims (no signature check) and print a summary.
  2. Build a TokenInjectedClient with the token.
  3. Call rucio ping  -> confirms the rucio server is reachable.
  4. Call rucio whoami -> confirms the token is accepted by Rucio.

---

How to get an ATLAS IAM token with audience=rucio
--------------------------------------------------

Option A - oidc-agent (most common on UChicago AF and CERN lxplus):

    eval $(oidc-agent)           # start the agent if not running
    oidc-add atlas               # load the ATLAS IAM account (one-time)
    export RUCIO_MCP_TOKEN=$(oidc-token atlas --aud rucio)

Option B - htgettoken (Fermilab / FNAL sites):

    htgettoken -a atlas --audience rucio -o /tmp/atlas-rucio-token.txt
    export RUCIO_MCP_TOKEN=$(cat /tmp/atlas-rucio-token.txt)

Option C - paste a token directly (e.g. from a web portal or another tool):

    export RUCIO_MCP_TOKEN=<paste-token-here>

---

Usage
-----

    # With pixi (recommended on UChicago AF):
    RUCIO_MCP_TOKEN=$(oidc-token atlas --aud rucio) \\
        pixi run test-oidc-token

    # Or set the env var first:
    export RUCIO_MCP_TOKEN=$(oidc-token atlas --aud rucio)
    pixi run test-oidc-token

    # You can override the Rucio account (defaults to preferred_username / sub):
    RUCIO_MCP_TOKEN=... RUCIO_ACCOUNT=gstark pixi run test-oidc-token
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time

from rucio_mcp.auth.token_client import TokenInjectedClient


def _decode_claims(token: str) -> dict:
    """Decode JWT payload without signature verification."""
    parts = token.split(".")
    if len(parts) != 3:
        sys.exit(f"ERROR: token does not look like a JWT (got {len(parts)} parts)")
    payload = parts[1]
    payload += "=" * (4 - len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def _check_token(token: str) -> tuple[str, float]:
    """Print token summary and return (account, exp)."""
    claims = _decode_claims(token)

    iss = claims.get("iss", "?")
    aud = claims.get("aud", "?")
    sub = claims.get("sub", "?")
    username = claims.get("preferred_username", sub)
    exp = float(claims.get("exp", 0))
    iat = float(claims.get("iat", 0))
    scope = claims.get("scope", "")
    now = time.time()

    print("=== Token claims ===")
    print(f"  issuer    : {iss}")
    print(f"  audience  : {aud}")
    print(f"  subject   : {sub}")
    print(f"  username  : {username}")
    print(f"  scope     : {scope}")
    issued_ago = int(now - iat) if iat else "?"
    expires_in = int(exp - now) if exp else "?"
    print(f"  issued    : {issued_ago}s ago")
    if isinstance(expires_in, int) and expires_in < 0:
        sys.exit(f"ERROR: token expired {-expires_in}s ago -- get a fresh one")
    print(f"  expires   : in {expires_in}s")
    print()

    if aud not in ("rucio", ["rucio"]):
        print(f"WARNING: aud={aud!r} -- Rucio expects aud=rucio; re-fetch with --aud rucio")

    account: str = os.environ.get("RUCIO_ACCOUNT") or username
    return account, exp


def main() -> None:
    """Run the token verification test."""
    token = os.environ.get("RUCIO_MCP_TOKEN", "").strip()
    if not token:
        sys.exit(
            "ERROR: set RUCIO_MCP_TOKEN to your ATLAS IAM token.\n\n"
            "  export RUCIO_MCP_TOKEN=$(oidc-token atlas --aud rucio)\n"
            "  pixi run test-oidc-token"
        )

    account, _exp = _check_token(token)
    print(f"Using Rucio account: {account}")
    print()

    print("=== Building TokenInjectedClient ===")
    try:
        client = TokenInjectedClient(bearer_token=token, account=account)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"ERROR constructing client: {exc}")
    print("  OK")
    print()

    print("=== rucio ping ===")
    try:
        result = client.ping()
        print(f"  server version: {result.get('version', result)}")
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"ERROR pinging Rucio: {exc}")
    print()

    print("=== rucio whoami ===")
    try:
        identity = client.whoami()
        for key, val in identity.items():
            print(f"  {key}: {val}")
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"ERROR calling whoami: {exc}")
    print()

    print("SUCCESS: OIDC token is accepted by Rucio.")


if __name__ == "__main__":
    main()
