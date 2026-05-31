"""Tests for server startup preflight checks and ping."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from rucio_mcp.server import _preflight_check, ping_server, serve


@pytest.fixture
def valid_cfg(tmp_path: Path) -> Path:
    """A real tmp_path/rucio.cfg file to use as a config path."""
    cfg = tmp_path / "rucio.cfg"
    cfg.touch()
    return cfg


class TestPreflightCheck:
    def test_fails_when_cfg_path_does_not_exist(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            _preflight_check(tmp_path / "nonexistent.cfg")
        assert exc.value.code != 0

    def test_passes_with_existing_cfg_path(self, valid_cfg: Path) -> None:
        env = {
            "RUCIO_AUTH_TYPE": "x509_proxy",
            "X509_CERT_DIR": str(valid_cfg.parent),
            "X509_USER_PROXY": str(valid_cfg),
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)  # must not raise

    def test_sets_rucio_config_env_to_cfg_path(self, valid_cfg: Path) -> None:
        with patch.dict("os.environ", {}, clear=True):
            _preflight_check(valid_cfg)
            assert os.environ["RUCIO_CONFIG"] == str(valid_cfg)

    def test_auth_type_defaults_to_x509_proxy(self, valid_cfg: Path) -> None:
        with patch.dict("os.environ", {}, clear=True):
            _preflight_check(valid_cfg)
            assert os.environ["RUCIO_AUTH_TYPE"] == "x509_proxy"

    def test_auth_type_override_sets_env(self, valid_cfg: Path) -> None:
        with patch.dict("os.environ", {}, clear=True):
            _preflight_check(valid_cfg, auth_type_override="oidc")
            assert os.environ["RUCIO_AUTH_TYPE"] == "oidc"

    def test_explicit_auth_type_is_not_overridden(self, valid_cfg: Path) -> None:
        env = {"RUCIO_AUTH_TYPE": "userpass"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)
            assert os.environ["RUCIO_AUTH_TYPE"] == "userpass"

    def test_x509_user_proxy_defaults_when_not_set(self, valid_cfg: Path) -> None:
        expected = f"/tmp/x509up_u{os.getuid()}"
        env = {"RUCIO_AUTH_TYPE": "x509_proxy"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)
            assert os.environ.get("X509_USER_PROXY") == expected

    def test_explicit_x509_proxy_is_not_overridden(
        self, valid_cfg: Path, tmp_path: Path
    ) -> None:
        proxy = tmp_path / "proxy.pem"
        proxy.touch()
        env = {
            "RUCIO_AUTH_TYPE": "x509_proxy",
            "X509_USER_PROXY": str(proxy),
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)
            assert os.environ["X509_USER_PROXY"] == str(proxy)

    def test_passes_with_non_x509_auth(self, valid_cfg: Path) -> None:
        env = {"RUCIO_AUTH_TYPE": "userpass"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)  # must not raise

    def test_warns_when_x509_cert_dir_missing(self, valid_cfg: Path, capsys) -> None:
        env = {"RUCIO_AUTH_TYPE": "x509_proxy"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)
        assert "X509_CERT_DIR" in capsys.readouterr().err

    def test_warns_when_x509_cert_dir_nonexistent(
        self, valid_cfg: Path, capsys
    ) -> None:
        env = {
            "RUCIO_AUTH_TYPE": "x509_proxy",
            "X509_CERT_DIR": "/nonexistent/cert/dir",
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)
        assert "X509_CERT_DIR" in capsys.readouterr().err

    def test_no_x509_warning_for_userpass(self, valid_cfg: Path, capsys) -> None:
        env = {"RUCIO_AUTH_TYPE": "userpass"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)
        assert "X509_CERT_DIR" not in capsys.readouterr().err

    def test_warns_when_proxy_file_missing(self, valid_cfg: Path, capsys) -> None:
        env = {
            "RUCIO_AUTH_TYPE": "x509_proxy",
            "X509_CERT_DIR": str(valid_cfg.parent),
            "X509_USER_PROXY": "/nonexistent/proxy.pem",
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)
        assert "X509_USER_PROXY" in capsys.readouterr().err

    def test_no_proxy_warning_when_proxy_exists(
        self, valid_cfg: Path, tmp_path: Path, capsys
    ) -> None:
        proxy = tmp_path / "proxy.pem"
        proxy.touch()
        env = {
            "RUCIO_AUTH_TYPE": "x509_proxy",
            "X509_CERT_DIR": str(tmp_path),
            "X509_USER_PROXY": str(proxy),
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)
        assert "X509_USER_PROXY" not in capsys.readouterr().err


class TestServeHTTP:
    def test_http_missing_resource_url_exits_nonzero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            serve(transport="http", resource_url=None)
        assert exc_info.value.code != 0

    def test_http_error_mentions_resource_url(self, capsys) -> None:
        with pytest.raises(SystemExit):
            serve(transport="http", resource_url=None)
        assert "resource-url" in capsys.readouterr().err

    def test_stdio_calls_preflight_http_does_not(self) -> None:
        """stdio path calls _preflight_check; http path does not."""
        with (
            patch("rucio_mcp.server._preflight_check") as mock_check,
            patch("rucio_mcp.server._make_http_app") as mock_make,
            patch("uvicorn.run"),
        ):
            mock_make.return_value = MagicMock()
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                sites=["escape"],
            )
        mock_check.assert_not_called()


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
