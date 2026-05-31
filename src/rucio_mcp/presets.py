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


PRESETS: dict[str, Preset] = {
    "atlas": Preset(
        name="atlas",
        description="ATLAS at CERN (x509 proxy — stdio mode only)",
        config_resource="atlas.cfg",
        post_init_hint=textwrap.dedent("""\
            Next steps:
              export RUCIO_ACCOUNT=<your-atlas-account>
              voms-proxy-init -voms atlas

            Then run: rucio-mcp serve --site atlas

            Note: ATLAS uses x509 proxy auth. HTTP mode is not supported
            for ATLAS until rucio adds OIDC for end-users.
        """).rstrip(),
    ),
    "escape": Preset(
        name="escape",
        description="ESCAPE Virtual Research Environment at CERN (OIDC — stdio and HTTP mode)",
        config_resource="escape.cfg",
        post_init_hint=textwrap.dedent("""\
            Next steps:
              export RUCIO_ACCOUNT=<your-escape-account>

            For stdio mode (OIDC polling):
              rucio-mcp serve --site escape

            For HTTP mode (OAuth bridge):
              rucio-mcp serve --transport http --site escape \\
                              --resource-url http://localhost:8000
        """).rstrip(),
    ),
}
