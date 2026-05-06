"""Helpers for rucio-mcp managed configuration paths."""

from __future__ import annotations

import os
from pathlib import Path


def managed_rucio_config() -> Path:
    """Return the path to the rucio-mcp-managed rucio.cfg file.

    Resolution order:
    1. $XDG_CONFIG_HOME/rucio-mcp/rucio.cfg  (if XDG_CONFIG_HOME is set)
    2. ~/.config/rucio-mcp/rucio.cfg
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "rucio-mcp" / "rucio.cfg"
    return Path.home() / ".config" / "rucio-mcp" / "rucio.cfg"
