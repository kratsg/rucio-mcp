"""Tests for RucioCfg — reads [client] section from rucio.cfg."""

from __future__ import annotations

import textwrap
from importlib.resources import files as _pkg_files
from pathlib import Path

import pytest

from rucio_mcp.auth.rucio_cfg import RucioCfg


class TestRucioCfgFromPath:
    def test_load_escape_cfg(self, tmp_path: Path) -> None:
        p = tmp_path / "rucio.cfg"
        p.write_text(
            textwrap.dedent("""\
                [client]
                rucio_host = https://vre-rucio.cern.ch
                auth_host = https://vre-rucio-auth.cern.ch
                account = gstark
                auth_type = oidc
                oidc_audience = rucio
                oidc_polling = true
                oidc_issuer = escape
                oidc_scope = openid profile offline_access
            """)
        )
        cfg = RucioCfg.from_path(p)
        assert cfg.rucio_host == "https://vre-rucio.cern.ch"
        assert cfg.auth_host == "https://vre-rucio-auth.cern.ch"
        assert cfg.account == "gstark"
        assert cfg.oidc_audience == "rucio"
        assert cfg.oidc_scope == "openid profile offline_access"
        assert cfg.oidc_issuer == "escape"

    def test_defaults_when_optional_keys_absent(self, tmp_path: Path) -> None:
        p = tmp_path / "rucio.cfg"
        p.write_text(
            textwrap.dedent("""\
                [client]
                rucio_host = https://rucio.example.com
                auth_host = https://rucio-auth.example.com
            """)
        )
        cfg = RucioCfg.from_path(p)
        assert cfg.account == ""
        assert cfg.oidc_audience == "rucio"
        assert cfg.oidc_scope == "openid profile offline_access"
        assert cfg.oidc_issuer == ""

    def test_missing_rucio_host_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "rucio.cfg"
        p.write_text(
            textwrap.dedent("""\
                [client]
                auth_host = https://rucio-auth.example.com
            """)
        )
        with pytest.raises(KeyError):
            RucioCfg.from_path(p)

    def test_missing_auth_host_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "rucio.cfg"
        p.write_text(
            textwrap.dedent("""\
                [client]
                rucio_host = https://rucio.example.com
            """)
        )
        with pytest.raises(KeyError):
            RucioCfg.from_path(p)

    def test_auth_type_read_from_cfg(self, tmp_path: Path) -> None:
        p = tmp_path / "rucio.cfg"
        p.write_text(
            textwrap.dedent("""\
                [client]
                rucio_host = https://rucio.example.com
                auth_host = https://rucio-auth.example.com
                auth_type = oidc
            """)
        )
        cfg = RucioCfg.from_path(p)
        assert cfg.auth_type == "oidc"

    def test_auth_type_defaults_to_oidc(self, tmp_path: Path) -> None:
        p = tmp_path / "rucio.cfg"
        p.write_text(
            textwrap.dedent("""\
                [client]
                rucio_host = https://rucio.example.com
                auth_host = https://rucio-auth.example.com
            """)
        )
        cfg = RucioCfg.from_path(p)
        assert cfg.auth_type == "oidc"

    def test_frozen_dataclass(self, tmp_path: Path) -> None:
        p = tmp_path / "rucio.cfg"
        p.write_text(
            textwrap.dedent("""\
                [client]
                rucio_host = https://rucio.example.com
                auth_host = https://rucio-auth.example.com
            """)
        )
        cfg = RucioCfg.from_path(p)
        with pytest.raises(AttributeError):
            cfg.account = "changed"  # type: ignore[misc]

    def test_load_bundled_atlas_cfg(self) -> None:
        """Bundled atlas.cfg has no auth_type key; RucioCfg defaults to oidc."""
        p = Path(str(_pkg_files("rucio_mcp.data").joinpath("atlas.cfg")))
        cfg = RucioCfg.from_path(p)
        assert cfg.auth_type == "oidc"
        assert cfg.rucio_host == "https://voatlasrucio-server-prod.cern.ch:443"

    def test_load_bundled_cms_cfg(self) -> None:
        """Bundled cms.cfg has no auth_type key; RucioCfg defaults to oidc."""
        p = Path(str(_pkg_files("rucio_mcp.data").joinpath("cms.cfg")))
        cfg = RucioCfg.from_path(p)
        assert cfg.auth_type == "oidc"
        assert cfg.rucio_host == "https://cms-rucio.cern.ch"

    def test_load_bundled_dune_cfg(self) -> None:
        """Bundled dune.cfg has no auth_type key; RucioCfg defaults to oidc."""
        p = Path(str(_pkg_files("rucio_mcp.data").joinpath("dune.cfg")))
        cfg = RucioCfg.from_path(p)
        assert cfg.auth_type == "oidc"
        assert cfg.rucio_host == "https://dune-rucio.fnal.gov"
