"""Per-site nomenclature loader for MCP tool descriptions."""

from __future__ import annotations

from importlib.resources import files as _pkg_files


def load_nomenclature(resource: str | None) -> str | None:
    """Return the bundled nomenclature markdown for *resource*, or None.

    *resource* is a relative path inside ``rucio_mcp.data`` (e.g.
    ``"nomenclature/atlas.md"``).  Pass ``None`` for sites with no
    nomenclature file.
    """
    if resource is None:
        return None
    return _pkg_files("rucio_mcp.data").joinpath(resource).read_text(encoding="utf-8")
