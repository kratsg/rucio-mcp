"""JWT identity helpers for per-user Prometheus labels.

Decodes JWT claims without signature verification — consistent with how
``BriderProvider.load_access_token`` treats the bearer token (Rucio will
reject a bad token with 401; we don't re-validate it here).  No new
dependencies: uses only stdlib base64 and json.
"""

from __future__ import annotations

import base64
import json
from functools import lru_cache
from typing import Any


def decode_jwt_claims(token: str) -> dict[str, Any]:
    """Return the payload claims from a JWT string without verifying the signature.

    Returns an empty dict if *token* is not a three-part JWT or if the payload
    cannot be base64-decoded or JSON-parsed.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload_b64 = parts[1]
    # Restore standard base64 padding that urlsafe_b64encode strips
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    try:
        raw = base64.urlsafe_b64decode(payload_b64)
        result: dict[str, Any] = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}
    else:
        return result


@lru_cache(maxsize=1024)
def user_label(token: str) -> str:
    """Return a stable user identifier from *token* for Prometheus label use.

    Preference order: ``preferred_username`` → ``sub`` → ``"unknown"``.
    Returns ``"unknown"`` for opaque (non-JWT) tokens.
    """
    claims = decode_jwt_claims(token)
    return claims.get("preferred_username") or claims.get("sub") or "unknown"
