"""Shared helpers for MCP tool implementations."""

from __future__ import annotations

import json
from typing import Any


def parse_did(did: str) -> tuple[str, str]:
    """Split a ``scope:name`` DID string into its components.

    Args:
        did: A data identifier in ``scope:name`` format.

    Returns:
        A ``(scope, name)`` tuple.

    Raises:
        ValueError: If the DID does not contain a ``:`` separator.
    """
    if ":" not in did:
        msg = f"Invalid DID '{did}': expected 'scope:name' format."
        raise ValueError(msg)
    scope, name = did.split(":", 1)
    return scope, name


def format_dict(data: dict[str, Any]) -> str:
    """Format a dict as readable key: value lines."""
    return "\n".join(f"{k}: {v}" for k, v in data.items() if v is not None)


_READ_ONLY_ERROR = (
    "Error: server is running in read-only mode (--read-only flag). "
    "This operation modifies Rucio state and is not permitted."
)


def check_write_allowed(lifespan_context: dict[str, Any]) -> str | None:
    """Return an error string if write operations are disabled, else None."""
    if lifespan_context.get("read_only"):
        return _READ_ONLY_ERROR
    return None


def format_list(items: list[Any]) -> str:
    """Format a list of items, one per line.

    Dicts are rendered as compact JSON; other types use str().
    """
    lines = []
    for item in items:
        if isinstance(item, dict):
            lines.append(json.dumps(item, default=str))
        else:
            lines.append(str(item))
    return "\n".join(lines)
