"""Shared helpers for MCP tool implementations."""

from __future__ import annotations

import itertools
from typing import Any, TypeVar

T = TypeVar("T")


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


def human_bytes(n: float | None) -> str:
    """Convert a byte count to a human-readable string.

    Uses binary units (1024-based): B, KB, MB, GB, TB, PB.

    Examples:
        >>> human_bytes(0)
        '0 B'
        >>> human_bytes(50000000000000)
        '45.47 TB'
        >>> human_bytes(None)
        'N/A'
    """
    if n is None:
        return "N/A"
    n = int(n)
    if n == 0:
        return "0 B"
    negative = n < 0
    n = abs(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024 or unit == "PB":
            result = f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} B"
            return f"-{result}" if negative else result
        n /= 1024
    return f"{n:.2f} PB"  # unreachable but satisfies type checker


def paginate(
    items: list[T],
    limit: int,
    offset: int = 0,
) -> tuple[list[T], str]:
    """Truncate a list to a page window and generate a pagination footer.

    Args:
        items: The full list of items (already offset+limit sliced from source).
        limit: Maximum number of items to return per page.
        offset: Starting index (for footer display only).

    Returns:
        A tuple of ``(page_items, footer_text)``. ``footer_text`` is empty if
        all items fit within ``limit``.
    """
    if len(items) <= limit:
        return items, ""
    page = items[:limit]
    shown = offset + limit
    footer = (
        f"\n\n---\nShowing {limit} results (offset={offset}). "
        f"Pass `offset={shown}` to see more."
    )
    return page, footer


def paginate_iter(
    it: Any,
    limit: int,
    offset: int = 0,
) -> tuple[list[Any], str]:
    """Consume an iterator up to ``offset + limit + 1`` items for pagination.

    More efficient than materializing the full iterator.

    Args:
        it: An iterable to consume.
        limit: Maximum items to return per page.
        offset: Number of items to skip before collecting results.

    Returns:
        A tuple of ``(page_items, footer_text)``.
    """
    # consume offset items first, then up to limit+1 to detect "more"
    consumed = list(itertools.islice(it, offset + limit + 1))
    window = consumed[offset : offset + limit + 1]
    if len(window) <= limit:
        return window, ""
    page = window[:limit]
    shown = offset + limit
    footer = (
        f"\n\n---\nShowing {limit} results (offset={offset}). "
        f"Pass `offset={shown}` to see more."
    )
    return page, footer


def build_hints(hints: list[str]) -> str:
    """Build a 'Next steps' footer from a list of hint strings.

    Args:
        hints: List of hint strings. Empty list returns empty string.

    Returns:
        A formatted markdown block, or empty string if no hints.
    """
    if not hints:
        return ""
    lines = "\n".join(f"- {h}" for h in hints)
    return f"\n\n**Next steps:**\n{lines}"


def classify_error(exc: Exception) -> str:
    """Return an actionable error message with recovery guidance.

    Pattern-matches on exception type name and message text to provide
    specific recovery steps rather than a bare traceback string.

    Args:
        exc: The caught exception.

    Returns:
        A formatted error string with recovery guidance.
    """
    exc_type = type(exc).__name__
    exc_msg = str(exc)

    # Match on exception type name and message substrings
    msg_lower = exc_msg.lower()
    type_lower = exc_type.lower()

    if (
        "dataidentifiernotfound" in type_lower
        or "data identifier not found" in msg_lower
    ):
        guidance = (
            "The DID does not exist in Rucio. "
            "Use `rucio_list_dids` with a wildcard pattern to search for it."
        )
    elif "rsenotfound" in type_lower or "rse not found" in msg_lower:
        guidance = (
            "The RSE name is not recognised. "
            "Use `rucio_list_rses` to find valid RSE names or expressions."
        )
    elif "rulenotfound" in type_lower or "rule not found" in msg_lower:
        guidance = (
            "The rule ID does not exist or has been deleted. "
            "Use `rucio_list_rules <did>` to find valid rule IDs."
        )
    elif "duplicaterule" in type_lower or "duplicate rule" in msg_lower:
        guidance = (
            "A rule with the same parameters already exists. "
            "Use `rucio_list_rules <did>` to inspect the existing rule."
        )
    elif (
        "insufficientaccountlimit" in type_lower
        or "quota" in msg_lower
        or "account limit" in msg_lower
    ):
        guidance = (
            "Your account has insufficient quota for this operation. "
            "Use `rucio_list_account_limits` to check your quotas and "
            "`rucio_list_account_usage` to see current consumption."
        )
    elif (
        "accessdenied" in type_lower
        or "access denied" in msg_lower
        or "not allowed" in msg_lower
        or "permission" in msg_lower
    ):
        guidance = (
            "Access denied. "
            "Use `rucio_whoami` to verify your authenticated account and "
            "`rucio_voms_proxy_info` to check your proxy certificate status."
        )
    elif (
        "ssl" in type_lower
        or "ssl" in msg_lower
        or "proxy" in msg_lower
        or "certificate" in msg_lower
        or "x509" in msg_lower
    ):
        guidance = (
            "SSL or proxy certificate error. "
            "Run `rucio_voms_proxy_info` to check your proxy certificate. "
            "If expired, run: voms-proxy-init -voms atlas"
        )
    elif (
        "connectionerror" in type_lower
        or "connection" in msg_lower
        or "timeout" in msg_lower
        or "database" in type_lower
    ):
        guidance = (
            "Network or server error — this may be transient. "
            "Use `rucio_ping` to check server connectivity and try again."
        )
    else:
        # Generic fallback — preserve original error text, no recovery guidance
        return f"Error: {exc_msg}"

    return f"Error: {exc_msg}\n\n**Recovery:** {guidance}"


_READ_ONLY_ERROR = (
    "Error: server is running in read-only mode (--read-only flag). "
    "This operation modifies Rucio state and is not permitted."
)


def check_write_allowed(lifespan_context: dict[str, Any]) -> str | None:
    """Return an error string if write operations are disabled, else None."""
    if lifespan_context.get("read_only"):
        return _READ_ONLY_ERROR
    return None


# Fields whose values should be treated as byte counts for humanization.
_DEFAULT_BYTE_KEYS: frozenset[str] = frozenset(
    {
        "bytes",
        "bytes_limit",
        "bytes_remaining",
        "used",
        "free",
        "total",
        "available_bytes",
        "rse_used",
    }
)


def format_dict(
    data: dict[str, Any],
    include_keys: list[str] | None = None,
    byte_keys: frozenset[str] | None = None,
) -> str:
    """Format a dict as a markdown key-value bullet list.

    Args:
        data: The dict to format.
        include_keys: If provided, only render these keys in this order.
            Keys absent from ``data`` are silently skipped.
            If ``None``, all non-None values are rendered (original behavior).
        byte_keys: Set of key names whose values should be humanized via
            ``human_bytes()``. Defaults to ``_DEFAULT_BYTE_KEYS``.
    """
    if byte_keys is None:
        byte_keys = _DEFAULT_BYTE_KEYS

    if include_keys is not None:
        pairs = [(k, data[k]) for k in include_keys if k in data]
    else:
        pairs = [(k, v) for k, v in data.items() if v is not None]

    lines = []
    for k, v in pairs:
        if v is None:
            continue
        display = (
            human_bytes(v) if k in byte_keys and isinstance(v, (int, float)) else v
        )
        lines.append(f"- **{k}:** {display}")
    return "\n".join(lines)


def _format_markdown_table(
    items: list[dict[str, Any]],
    keys: list[str],
    byte_keys: frozenset[str] | None = None,
) -> str:
    """Render a list of dicts as a markdown table."""
    if byte_keys is None:
        byte_keys = _DEFAULT_BYTE_KEYS

    def _cell(item: dict[str, Any], k: str) -> str:
        v = item.get(k, "")
        if k in byte_keys and isinstance(v, (int, float)):
            return human_bytes(v)
        return str(v) if v is not None else ""

    header = "| " + " | ".join(str(k) for k in keys) + " |"
    separator = "| " + " | ".join("---" for _ in keys) + " |"
    rows = ["| " + " | ".join(_cell(item, k) for k in keys) + " |" for item in items]
    return "\n".join([header, separator, *rows])


def format_list(
    items: list[Any],
    include_keys: list[str] | None = None,
    byte_keys: frozenset[str] | None = None,
) -> str:
    """Format a list of items as markdown.

    If all items are dicts with the same keys, renders as a markdown table.
    Otherwise renders as a bulleted list.

    Args:
        items: List of items to format.
        include_keys: If provided, only render these columns (in this order).
            Applied only when rendering as a table. For bullet-list fallback,
            also filters to these keys.
        byte_keys: Set of key names to humanize as byte counts.
            Defaults to ``_DEFAULT_BYTE_KEYS``.
    """
    if byte_keys is None:
        byte_keys = _DEFAULT_BYTE_KEYS

    if not items:
        return ""

    if all(isinstance(item, dict) for item in items):
        all_keys = list(items[0].keys())
        if all(list(item.keys()) == all_keys for item in items):
            keys = include_keys if include_keys is not None else all_keys
            # filter to only keys that actually exist in the data
            keys = [k for k in keys if k in all_keys]
            return _format_markdown_table(items, keys, byte_keys=byte_keys)

    lines = []
    for item in items:
        if isinstance(item, dict):
            if include_keys is not None:
                pairs = [(k, item[k]) for k in include_keys if k in item]
            else:
                pairs = list(item.items())
            parts = []
            for k, v in pairs:
                if v is None:
                    continue
                display = (
                    human_bytes(v)
                    if k in byte_keys and isinstance(v, (int, float))
                    else v
                )
                parts.append(f"**{k}:** {display}")
            lines.append("- " + ", ".join(parts))
        else:
            lines.append(f"- {item}")
    return "\n".join(lines)
