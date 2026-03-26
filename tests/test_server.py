"""Tests for server startup preflight checks."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from rucio_mcp.server import _preflight_check


@pytest.fixture
def valid_rucio_home(tmp_path):
    """A tmp_path with etc/rucio.cfg present."""
    cfg = tmp_path / "etc" / "rucio.cfg"
    cfg.parent.mkdir()
    cfg.touch()
    return tmp_path


class TestPreflightCheck:
    def test_fails_without_rucio_home(self) -> None:
        with (
            patch.dict("os.environ", {"RUCIO_AUTH_TYPE": "x509_proxy"}, clear=True),
            pytest.raises(SystemExit) as exc,
        ):
            _preflight_check()
        assert exc.value.code != 0

    def test_error_message_mentions_rucio_home(self, capsys) -> None:
        with (
            patch.dict("os.environ", {"RUCIO_AUTH_TYPE": "x509_proxy"}, clear=True),
            pytest.raises(SystemExit),
        ):
            _preflight_check()
        assert "RUCIO_HOME" in capsys.readouterr().err

    def test_fails_when_rucio_cfg_missing(self, tmp_path) -> None:
        env = {"RUCIO_HOME": str(tmp_path), "RUCIO_AUTH_TYPE": "x509_proxy"}
        with (
            patch.dict("os.environ", env, clear=True),
            pytest.raises(SystemExit),
        ):
            _preflight_check()

    def test_fails_without_auth_type(self, valid_rucio_home) -> None:
        env = {"RUCIO_HOME": str(valid_rucio_home)}
        with (
            patch.dict("os.environ", env, clear=True),
            pytest.raises(SystemExit) as exc,
        ):
            _preflight_check()
        assert exc.value.code != 0

    def test_error_message_mentions_auth_type(self, valid_rucio_home, capsys) -> None:
        env = {"RUCIO_HOME": str(valid_rucio_home)}
        with (
            patch.dict("os.environ", env, clear=True),
            pytest.raises(SystemExit),
        ):
            _preflight_check()
        assert "RUCIO_AUTH_TYPE" in capsys.readouterr().err

    def test_passes_with_x509_and_cert_dir(self, valid_rucio_home) -> None:
        env = {
            "RUCIO_HOME": str(valid_rucio_home),
            "RUCIO_AUTH_TYPE": "x509_proxy",
            "X509_CERT_DIR": str(valid_rucio_home),
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()  # must not raise

    def test_passes_with_non_x509_auth(self, valid_rucio_home) -> None:
        env = {"RUCIO_HOME": str(valid_rucio_home), "RUCIO_AUTH_TYPE": "userpass"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()  # must not raise

    def test_warns_when_x509_cert_dir_missing(self, valid_rucio_home, capsys) -> None:
        env = {"RUCIO_HOME": str(valid_rucio_home), "RUCIO_AUTH_TYPE": "x509_proxy"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
        assert "X509_CERT_DIR" in capsys.readouterr().err

    def test_warns_when_x509_cert_dir_nonexistent(
        self, valid_rucio_home, capsys
    ) -> None:
        env = {
            "RUCIO_HOME": str(valid_rucio_home),
            "RUCIO_AUTH_TYPE": "x509_proxy",
            "X509_CERT_DIR": "/nonexistent/cert/dir",
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
        assert "X509_CERT_DIR" in capsys.readouterr().err

    def test_no_x509_warning_for_userpass(self, valid_rucio_home, capsys) -> None:
        env = {"RUCIO_HOME": str(valid_rucio_home), "RUCIO_AUTH_TYPE": "userpass"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
        assert "X509_CERT_DIR" not in capsys.readouterr().err

    def test_warns_when_proxy_file_missing(self, valid_rucio_home, capsys) -> None:
        env = {
            "RUCIO_HOME": str(valid_rucio_home),
            "RUCIO_AUTH_TYPE": "x509_proxy",
            "X509_CERT_DIR": str(valid_rucio_home),
            "X509_USER_PROXY": "/nonexistent/proxy.pem",
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
        assert "X509_USER_PROXY" in capsys.readouterr().err

    def test_no_proxy_warning_when_proxy_exists(self, valid_rucio_home, capsys) -> None:
        proxy = valid_rucio_home / "proxy.pem"
        proxy.touch()
        env = {
            "RUCIO_HOME": str(valid_rucio_home),
            "RUCIO_AUTH_TYPE": "x509_proxy",
            "X509_CERT_DIR": str(valid_rucio_home),
            "X509_USER_PROXY": str(proxy),
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check()
        assert "X509_USER_PROXY" not in capsys.readouterr().err
