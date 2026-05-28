"""Tests for RucioCfg — reads [client] section from rucio.cfg."""

from __future__ import annotations

import textwrap
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
        with pytest.raises(Exception):
            cfg.account = "changed"  # type: ignore[misc]
