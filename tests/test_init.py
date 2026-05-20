"""Tests for rucio-mcp init command and config path helpers."""

from __future__ import annotations

from importlib.resources import files

from rucio_mcp.config_paths import managed_rucio_config
from rucio_mcp.init import init


class TestManagedRucioConfig:
    def test_default_uses_home_config(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        assert (
            managed_rucio_config() == tmp_path / ".config" / "rucio-mcp" / "rucio.cfg"
        )

    def test_respects_xdg_config_home(self, tmp_path, monkeypatch) -> None:
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
        assert managed_rucio_config() == xdg / "rucio-mcp" / "rucio.cfg"


class TestInitCommand:
    def test_writes_atlas_cfg_to_managed_location(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        result = init("atlas", force=False, prefix=None, list_presets=False)
        assert result == 0
        written = tmp_path / ".config" / "rucio-mcp" / "rucio.cfg"
        assert written.exists()
        expected = files("rucio_mcp.data").joinpath("atlas.cfg").read_bytes()
        assert written.read_bytes() == expected

    def test_respects_xdg_config_home(self, tmp_path, monkeypatch) -> None:
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
        result = init("atlas", force=False, prefix=None, list_presets=False)
        assert result == 0
        assert (xdg / "rucio-mcp" / "rucio.cfg").exists()

    def test_refuses_to_overwrite_without_force(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        init("atlas", force=False, prefix=None, list_presets=False)
        capsys.readouterr()
        result = init("atlas", force=False, prefix=None, list_presets=False)
        assert result != 0
        assert "--force" in capsys.readouterr().out

    def test_force_overwrites_existing(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        init("atlas", force=False, prefix=None, list_presets=False)
        result = init("atlas", force=True, prefix=None, list_presets=False)
        assert result == 0

    def test_unknown_preset_exits_nonzero_and_lists_available(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        result = init(
            "not_a_real_experiment", force=False, prefix=None, list_presets=False
        )
        assert result != 0
        assert "atlas" in capsys.readouterr().out

    def test_list_prints_presets_and_exits_zero(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        result = init(None, force=False, prefix=None, list_presets=True)
        assert result == 0
        out = capsys.readouterr().out
        assert "atlas" in out

    def test_prefix_overrides_managed_location(self, tmp_path, monkeypatch) -> None:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        custom = tmp_path / "custom"
        result = init("atlas", force=False, prefix=custom, list_presets=False)
        assert result == 0
        assert (custom / "rucio.cfg").exists()
        assert not (home / ".config").exists()

    def test_prints_written_path_on_success(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        init("atlas", force=False, prefix=None, list_presets=False)
        out = capsys.readouterr().out
        expected_path = str(tmp_path / ".config" / "rucio-mcp" / "rucio.cfg")
        assert expected_path in out

    def test_prints_post_init_hint(self, tmp_path, monkeypatch, capsys) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        init("atlas", force=False, prefix=None, list_presets=False)
        out = capsys.readouterr().out
        assert "RUCIO_ACCOUNT" in out

    def test_list_requires_no_preset(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        result = init(None, force=False, prefix=None, list_presets=True)
        assert result == 0

    def test_config_dir_mode_is_private(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        init("atlas", force=False, prefix=None, list_presets=False)
        rucio_mcp_dir = tmp_path / ".config" / "rucio-mcp"
        mode = oct(rucio_mcp_dir.stat().st_mode)[-3:]
        assert mode == "700"

    def test_writes_atlas_auth_toml_alongside_cfg(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        result = init("atlas", force=False, prefix=None, list_presets=False)
        assert result == 0
        auth_path = tmp_path / ".config" / "rucio-mcp" / "atlas-auth.toml"
        assert auth_path.exists()
        expected = files("rucio_mcp.data").joinpath("atlas-auth.toml").read_bytes()
        assert auth_path.read_bytes() == expected

    def test_missing_preset_without_list_exits_nonzero(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        result = init(None, force=False, prefix=None, list_presets=False)
        assert result != 0
