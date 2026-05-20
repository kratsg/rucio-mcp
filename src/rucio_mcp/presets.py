"""Preset rucio.cfg configurations for known experiments."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    """A bundled rucio.cfg preset for a known experiment."""

    name: str
    description: str
    config_resource: str  # filename inside the rucio_mcp.data package
    post_init_hint: str  # guidance printed after a successful init
    auth_resource: str | None = None  # optional <site>-auth.toml inside rucio_mcp.data


PRESETS: dict[str, Preset] = {
    "atlas": Preset(
        name="atlas",
        description="ATLAS at CERN",
        config_resource="atlas.cfg",
        auth_resource="atlas-auth.toml",
        post_init_hint=textwrap.dedent("""\
            Next steps:
              export RUCIO_ACCOUNT=<your-atlas-account>
              voms-proxy-init -voms atlas

            Then run: rucio-mcp serve
        """).rstrip(),
    ),
}
