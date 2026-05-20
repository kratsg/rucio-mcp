"""Tests for server startup preflight checks and ping."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from rucio_mcp.auth.jwks_verifier import JWKSTokenVerifier
from rucio_mcp.auth.site_config import SiteAuthConfig
from rucio_mcp.server import _make_http_mcp, _preflight_check, ping_server, serve


@pytest.fixture
def valid_rucio_config(tmp_path):
    """A real tmp_path/rucio.cfg file for use as RUCIO_CONFIG."""
    cfg = tmp_path / "rucio.cfg"
    cfg.touch()
    return cfg


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

    def test_error_mentions_init_when_no_config_found(self, tmp_path, capsys) -> None:
        env = {"HOME": str(tmp_path), "RUCIO_AUTH_TYPE": "x509_proxy"}
        with (
            patch.dict("os.environ", env, clear=True),
            pytest.raises(SystemExit),
        ):
            _preflight_check()
        assert "rucio-mcp init" in capsys.readouterr().err


class TestMakeHttpMcp:
    def test_http_mcp_has_token_verifier(self) -> None:
        site_cfg = SiteAuthConfig.from_preset("atlas")
        mcp = _make_http_mcp(
            read_only=False,
            host="127.0.0.1",
            port=8000,
            site_cfg=site_cfg,
            resource_url="http://localhost:8000",
            issuer_override=site_cfg.issuer,
            audiences=[site_cfg.audience],
            required_scopes=site_cfg.required_scopes,
        )
        assert mcp._token_verifier is not None

    def test_http_mcp_verifier_uses_site_jwks_uri(self) -> None:
        site_cfg = SiteAuthConfig.from_preset("atlas")
        mcp = _make_http_mcp(
            read_only=False,
            host="127.0.0.1",
            port=8000,
            site_cfg=site_cfg,
            resource_url="http://localhost:8000",
            issuer_override=site_cfg.issuer,
            audiences=[site_cfg.audience],
            required_scopes=site_cfg.required_scopes,
        )
        assert isinstance(mcp._token_verifier, JWKSTokenVerifier)
        assert "atlas-auth.cern.ch" in mcp._token_verifier._issuer


class TestServeHTTP:
    def test_http_missing_resource_url_exits_nonzero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            serve(transport="http", resource_url=None)
        assert exc_info.value.code != 0

    def test_http_unknown_site_exits_nonzero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                site="nonexistent_xyz",
            )
        assert exc_info.value.code != 0

    def test_http_error_mentions_resource_url(self, capsys) -> None:
        with pytest.raises(SystemExit):
            serve(transport="http", resource_url=None)
        assert "resource-url" in capsys.readouterr().err

    def test_stdio_calls_preflight_http_does_not(self) -> None:
        """stdio path calls _preflight_check; http path does not (no rucio.cfg needed)."""
        with (
            patch("rucio_mcp.server._preflight_check") as mock_check,
            patch("rucio_mcp.server._make_http_mcp") as mock_make,
        ):
            mock_make.return_value.run = lambda **_: None
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                site="atlas",
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
