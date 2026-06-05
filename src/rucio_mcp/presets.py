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
    "atlas-x509": Preset(
        name="atlas-x509",
        description="ATLAS at CERN (x509 proxy — stdio mode only)",
        config_resource="atlas-x509.cfg",
        post_init_hint=textwrap.dedent("""\
            Next steps:
              export RUCIO_ACCOUNT=<your-atlas-account>
              voms-proxy-init -voms atlas

            Then run: rucio-mcp serve --site atlas-x509

            For HTTP mode, use the 'atlas' site.
        """).rstrip(),
    ),
    "cms-x509": Preset(
        name="cms-x509",
        description="CMS at CERN (x509 proxy — stdio mode only)",
        config_resource="cms-x509.cfg",
        post_init_hint=textwrap.dedent("""\
            Next steps:
              export RUCIO_ACCOUNT=<your-cms-account>
              voms-proxy-init -voms cms

            Then run: rucio-mcp serve --site cms-x509
        """).rstrip(),
    ),
    "cms": Preset(
        name="cms",
        description="CMS at CERN (OIDC — stdio and HTTP mode)",
        config_resource="cms.cfg",
        post_init_hint=textwrap.dedent("""\
            Next steps:
              export RUCIO_ACCOUNT=<your-cms-account>

            For stdio mode (OIDC polling):
              rucio-mcp serve --site cms

            For HTTP mode (OAuth bridge):
              rucio-mcp serve --transport http \\
                              --resource-url http://localhost:8000 \\
                              --site cms
        """).rstrip(),
    ),
    "atlas": Preset(
        name="atlas",
        description="ATLAS at CERN (OIDC — stdio and HTTP mode)",
        config_resource="atlas.cfg",
        post_init_hint=textwrap.dedent("""\
            Next steps:
              export RUCIO_ACCOUNT=<your-atlas-account>

            For stdio mode (OIDC polling):
              rucio-mcp serve --site atlas

            For HTTP mode (OAuth bridge):
              rucio-mcp serve --transport http \\
                              --resource-url http://localhost:8000 \\
                              --site atlas
        """).rstrip(),
    ),
    "dune": Preset(
        name="dune",
        description="DUNE (OIDC — stdio and HTTP mode)",
        config_resource="dune.cfg",
        post_init_hint=textwrap.dedent("""\
            Next steps:
              export RUCIO_ACCOUNT=<your-dune-account>

            For stdio mode (OIDC polling):
              rucio-mcp serve --site dune

            For HTTP mode (OAuth bridge):
              rucio-mcp serve --transport http \\
                              --resource-url http://localhost:8000 \\
                              --site dune
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
              rucio-mcp serve --transport http \\
                              --resource-url http://localhost:8000 \\
                              --site escape
        """).rstrip(),
    ),
}
