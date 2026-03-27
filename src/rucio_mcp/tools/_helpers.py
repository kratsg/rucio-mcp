"""Shared helpers for MCP tool implementations."""

from __future__ import annotations

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
    """Format a dict as a markdown key-value bullet list."""
    return "\n".join(f"- **{k}:** {v}" for k, v in data.items() if v is not None)


_READ_ONLY_ERROR = (
    "Error: server is running in read-only mode (--read-only flag). "
    "This operation modifies Rucio state and is not permitted."
)


def check_write_allowed(lifespan_context: dict[str, Any]) -> str | None:
    """Return an error string if write operations are disabled, else None."""
    if lifespan_context.get("read_only"):
        return _READ_ONLY_ERROR
    return None


def _format_markdown_table(items: list[dict[str, Any]], keys: list[str]) -> str:
    """Render a list of dicts as a markdown table."""
    header = "| " + " | ".join(str(k) for k in keys) + " |"
    separator = "| " + " | ".join("---" for _ in keys) + " |"
    rows = [
        "| " + " | ".join(str(item.get(k, "")) for k in keys) + " |" for item in items
    ]
    return "\n".join([header, separator, *rows])


def format_list(items: list[Any]) -> str:
    """Format a list of items as markdown.

    If all items are dicts with the same keys, renders as a markdown table.
    Otherwise renders as a bulleted list.
    """
    if not items:
        return ""

    if all(isinstance(item, dict) for item in items):
        all_keys = list(items[0].keys())
        if all(list(item.keys()) == all_keys for item in items):
            return _format_markdown_table(items, all_keys)

    lines = []
    for item in items:
        if isinstance(item, dict):
            parts = [f"**{k}:** {v}" for k, v in item.items() if v is not None]
            lines.append("- " + ", ".join(parts))
        else:
            lines.append(f"- {item}")
    return "\n".join(lines)
