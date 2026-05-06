"""Tests for server startup preflight checks and ping."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from rucio_mcp.server import _preflight_check, ping_server


@pytest.fixture
def valid_rucio_config(tmp_path):
    """A real tmp_path/rucio.cfg file for use as RUCIO_CONFIG."""
    cfg = tmp_path / "rucio.cfg"
    cfg.touch()
    return cfg


@pytest.fixture
def valid_rucio_home(tmp_path):
    """A tmp_path with etc/rucio.cfg — for RUCIO_HOME backward-compat tests."""
    cfg = tmp_path / "etc" / "rucio.cfg"
    cfg.parent.mkdir()
    cfg.touch()
    return tmp_path


class TestPreflightCheck:
    def test_fails_without_any_config(self, tmp_path) -> None:
        env = {"HOME": str(tmp_path), "RUCIO_AUTH_TYPE": "x509_proxy"}
        with (
            patch.dict("os.environ", env, clear=True),
            pytest.raises(SystemExit) as exc,
        ):
            _preflight_check()
        assert exc.value.code != 0

    def test_error_mentions_rucio_mcp_init(self, tmp_path, capsys) -> None:
        env = {"HOME": str(tmp_path), "RUCIO_AUTH_TYPE": "x509_proxy"}
        with (
            patch.dict("os.environ", env, clear=True),
            pytest.raises(SystemExit),
        ):
            _preflight_check()
        assert "rucio-mcp init" in capsys.readouterr().err

    def test_fails_when_rucio_config_file_missing(self, tmp_path) -> None:
        env = {
            "RUCIO_CONFIG": str(tmp_path / "nonexistent.cfg"),
            "RUCIO_AUTH_TYPE": "x509_proxy",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            pytest.raises(SystemExit),
        ):
            _preflight_check()

    def test_passes_with_rucio_config_set(self, valid_rucio_config) -> None:
        env = {
            "RUCIO_CONFIG": str(valid_rucio_config),
            "RUCIO_AUTH_TYPE": "x509_proxy",
            "X509_CERT_DIR": str(valid_rucio_config.parent),
            "X509_USER_PROXY": str(valid_rucio_config),
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()  # must not raise

    def test_auth_type_defaults_to_x509_proxy(self, valid_rucio_config) -> None:
        env = {"RUCIO_CONFIG": str(valid_rucio_config)}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
            assert os.environ["RUCIO_AUTH_TYPE"] == "x509_proxy"

    def test_explicit_auth_type_is_not_overridden(self, valid_rucio_config) -> None:
        env = {"RUCIO_CONFIG": str(valid_rucio_config), "RUCIO_AUTH_TYPE": "userpass"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
            assert os.environ["RUCIO_AUTH_TYPE"] == "userpass"

    def test_x509_user_proxy_defaults_when_not_set(self, valid_rucio_config) -> None:
        expected = f"/tmp/x509up_u{os.getuid()}"
        env = {"RUCIO_CONFIG": str(valid_rucio_config), "RUCIO_AUTH_TYPE": "x509_proxy"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
            assert os.environ.get("X509_USER_PROXY") == expected

    def test_explicit_x509_proxy_is_not_overridden(
        self, valid_rucio_config, tmp_path
    ) -> None:
        proxy = tmp_path / "proxy.pem"
        proxy.touch()
        env = {
            "RUCIO_CONFIG": str(valid_rucio_config),
            "RUCIO_AUTH_TYPE": "x509_proxy",
            "X509_USER_PROXY": str(proxy),
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
            assert os.environ["X509_USER_PROXY"] == str(proxy)

    def test_passes_with_non_x509_auth(self, valid_rucio_config) -> None:
        env = {"RUCIO_CONFIG": str(valid_rucio_config), "RUCIO_AUTH_TYPE": "userpass"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()  # must not raise

    def test_warns_when_x509_cert_dir_missing(self, valid_rucio_config, capsys) -> None:
        env = {"RUCIO_CONFIG": str(valid_rucio_config), "RUCIO_AUTH_TYPE": "x509_proxy"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
        assert "X509_CERT_DIR" in capsys.readouterr().err

    def test_warns_when_x509_cert_dir_nonexistent(
        self, valid_rucio_config, capsys
    ) -> None:
        env = {
            "RUCIO_CONFIG": str(valid_rucio_config),
            "RUCIO_AUTH_TYPE": "x509_proxy",
            "X509_CERT_DIR": "/nonexistent/cert/dir",
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
        assert "X509_CERT_DIR" in capsys.readouterr().err

    def test_no_x509_warning_for_userpass(self, valid_rucio_config, capsys) -> None:
        env = {"RUCIO_CONFIG": str(valid_rucio_config), "RUCIO_AUTH_TYPE": "userpass"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
        assert "X509_CERT_DIR" not in capsys.readouterr().err

    def test_warns_when_proxy_file_missing(self, valid_rucio_config, capsys) -> None:
        env = {
            "RUCIO_CONFIG": str(valid_rucio_config),
            "RUCIO_AUTH_TYPE": "x509_proxy",
            "X509_CERT_DIR": str(valid_rucio_config.parent),
            "X509_USER_PROXY": "/nonexistent/proxy.pem",
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
        assert "X509_USER_PROXY" in capsys.readouterr().err

    def test_no_proxy_warning_when_proxy_exists(
        self, valid_rucio_config, tmp_path, capsys
    ) -> None:
        proxy = tmp_path / "proxy.pem"
        proxy.touch()
        env = {
            "RUCIO_CONFIG": str(valid_rucio_config),
            "RUCIO_AUTH_TYPE": "x509_proxy",
            "X509_CERT_DIR": str(valid_rucio_config.parent),
            "X509_USER_PROXY": str(proxy),
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
        assert "X509_USER_PROXY" not in capsys.readouterr().err

    def test_uses_managed_config_when_nothing_set(self, tmp_path) -> None:
        managed_cfg = tmp_path / ".config" / "rucio-mcp" / "rucio.cfg"
        managed_cfg.parent.mkdir(parents=True)
        managed_cfg.touch()
        env = {"HOME": str(tmp_path), "RUCIO_AUTH_TYPE": "x509_proxy"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()  # must not raise

    def test_managed_config_sets_rucio_config_env(self, tmp_path) -> None:
        managed_cfg = tmp_path / ".config" / "rucio-mcp" / "rucio.cfg"
        managed_cfg.parent.mkdir(parents=True)
        managed_cfg.touch()
        env = {"HOME": str(tmp_path), "RUCIO_AUTH_TYPE": "x509_proxy"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
            assert os.environ["RUCIO_CONFIG"] == str(managed_cfg)

    def test_rucio_config_takes_priority_over_managed(
        self, valid_rucio_config, tmp_path
    ) -> None:
        managed_cfg = tmp_path / ".config" / "rucio-mcp" / "rucio.cfg"
        managed_cfg.parent.mkdir(parents=True)
        managed_cfg.touch()
        env = {
            "HOME": str(tmp_path),
            "RUCIO_CONFIG": str(valid_rucio_config),
            "RUCIO_AUTH_TYPE": "x509_proxy",
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
            assert os.environ["RUCIO_CONFIG"] == str(valid_rucio_config)

    def test_rucio_home_backward_compat(self, valid_rucio_home, tmp_path) -> None:
        env = {
            "HOME": str(tmp_path),
            "RUCIO_HOME": str(valid_rucio_home),
            "RUCIO_AUTH_TYPE": "x509_proxy",
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()  # must not raise

    def test_rucio_home_backward_compat_missing_cfg(self, tmp_path) -> None:
        env = {
            "HOME": str(tmp_path),
            "RUCIO_HOME": str(tmp_path / "missing"),
            "RUCIO_AUTH_TYPE": "x509_proxy",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            pytest.raises(SystemExit),
        ):
            _preflight_check()

    def test_error_mentions_init_when_no_config_found(self, tmp_path, capsys) -> None:
        env = {"HOME": str(tmp_path), "RUCIO_AUTH_TYPE": "x509_proxy"}
        with (
            patch.dict("os.environ", env, clear=True),
            pytest.raises(SystemExit),
        ):
            _preflight_check()
        assert "rucio-mcp init" in capsys.readouterr().err


class TestPingServer:
    def test_ping_prints_server_version(self, capsys) -> None:
        with (
            patch("rucio_mcp.server._preflight_check"),
            patch("rucio_mcp.server.Client") as mock_client,
        ):
            mock_client.return_value.ping.return_value = {"version": "35.6.0"}
            mock_client.return_value.whoami.return_value = {"account": "gstark"}
            ping_server()
        out = capsys.readouterr().out
        assert "35.6.0" in out
        assert "gstark" in out

    def test_ping_calls_preflight(self) -> None:
        with (
            patch("rucio_mcp.server._preflight_check") as mock_check,
            patch("rucio_mcp.server.Client") as mock_client,
        ):
            mock_client.return_value.ping.return_value = {}
            mock_client.return_value.whoami.return_value = {}
            ping_server()
        mock_check.assert_called_once()
