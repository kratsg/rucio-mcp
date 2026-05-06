"""Implementation of the rucio-mcp init subcommand."""

from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path

from rucio_mcp.config_paths import managed_rucio_config
from rucio_mcp.presets import PRESETS


def init(
    preset: str | None,
    *,
    force: bool,
    prefix: Path | None,
    list_presets: bool,
) -> int:
    """Write a preset rucio.cfg to the managed config location.

    Returns an exit code (0 = success, non-zero = error).
    """
    if list_presets:
        for p in PRESETS.values():
            sys.stdout.write(f"  {p.name:<20} {p.description}\n")
        return 0

    if preset is None:
        sys.stdout.write(
            "Error: a preset name is required. "
            "Use --list to see available presets.\n"
            "  rucio-mcp init <preset> [--force] [--prefix DIR]\n"
        )
        return 1

    if preset not in PRESETS:
        sys.stdout.write(f"Error: unknown preset {preset!r}. Available presets:\n")
        for p in PRESETS.values():
            sys.stdout.write(f"  {p.name:<20} {p.description}\n")
        return 1

    entry = PRESETS[preset]
    if prefix is not None:
        cfg_path = prefix / "rucio.cfg"
    else:
        cfg_path = managed_rucio_config()

    if cfg_path.exists() and not force:
        sys.stdout.write(
            f"Error: {cfg_path} already exists.\n"
            "  Use --force to overwrite.\n"
        )
        return 1

    cfg_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = files("rucio_mcp.data").joinpath(entry.config_resource).read_bytes()
    cfg_path.write_bytes(data)

    sys.stdout.write(f"Created {cfg_path}\n\n{entry.post_init_hint}\n")
    return 0
