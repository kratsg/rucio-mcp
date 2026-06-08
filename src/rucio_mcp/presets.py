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
    nomenclature_resource: str | None = None  # path inside rucio_mcp.data, or None


PRESETS: dict[str, Preset] = {
    "cms": Preset(
        name="cms",
        description="CMS at CERN (OIDC — stdio and HTTP mode)",
        config_resource="cms.cfg",
        post_init_hint=textwrap.dedent("""\
            Next steps:
              export RUCIO_ACCOUNT=<your-cms-account>

            For stdio mode (OIDC polling):
              rucio-mcp serve --site cms

            For stdio mode (x509 proxy):
              voms-proxy-init -voms cms
              rucio-mcp serve --site cms --auth-type x509

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
        nomenclature_resource="nomenclature/atlas.md",
        post_init_hint=textwrap.dedent("""\
            Next steps:
              export RUCIO_ACCOUNT=<your-atlas-account>

            For stdio mode (OIDC polling):
              rucio-mcp serve --site atlas

            For stdio mode (x509 proxy):
              voms-proxy-init -voms atlas
              rucio-mcp serve --site atlas --auth-type x509

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
