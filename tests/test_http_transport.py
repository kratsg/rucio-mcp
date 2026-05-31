"""Tests for the HTTP transport: multi-site path-prefix routing, OAuth metadata, bridge wiring."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
from starlette.testclient import TestClient

from rucio_mcp.server import _make_http_app, serve


@pytest.fixture
def oidc_rucio_cfg(tmp_path: Path) -> Path:
    p = tmp_path / "rucio.cfg"
    p.write_text(
        textwrap.dedent("""\
            [client]
            rucio_host = https://vre-rucio.cern.ch
            auth_host = https://vre-rucio-auth.cern.ch
            account = gstark
            auth_type = oidc
            oidc_audience = rucio
            oidc_issuer = escape
            oidc_scope = openid profile offline_access
        """)
    )
    return p


@pytest.fixture
def http_app(oidc_rucio_cfg: Path):
    return _make_http_app(
        sites=["escape"],
        resource_url="http://localhost:8000",
        read_only=False,
        host="127.0.0.1",
        port=8000,
        rucio_cfg_overrides={"escape": oidc_rucio_cfg},
    )


@pytest.fixture
def http_client(http_app):
    return TestClient(http_app, raise_server_exceptions=True)


class TestOAuthMetadataEndpoints:
    def test_authorization_server_metadata_reachable(
        self, http_client: TestClient
    ) -> None:
        resp = http_client.get("/site/escape/.well-known/oauth-authorization-server")
        assert resp.status_code == 200

    def test_authorization_server_metadata_has_required_fields(
        self, http_client: TestClient
    ) -> None:
        data = http_client.get(
            "/site/escape/.well-known/oauth-authorization-server"
        ).json()
        assert "issuer" in data
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "registration_endpoint" in data

    def test_authorization_server_issuer_matches_site_url(
        self, http_client: TestClient
    ) -> None:
        data = http_client.get(
            "/site/escape/.well-known/oauth-authorization-server"
        ).json()
        assert data["issuer"].rstrip("/") == "http://localhost:8000/site/escape"

    def test_root_metadata_path_is_404(self, http_client: TestClient) -> None:
        resp = http_client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 404


class TestUnauthenticatedAccess:
    def test_mcp_post_without_auth_returns_401(self, http_client: TestClient) -> None:
        resp = http_client.post(
            "/site/escape/",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )
        assert resp.status_code == 401

    def test_401_response_has_www_authenticate_header(
        self, http_client: TestClient
    ) -> None:
        resp = http_client.post(
            "/site/escape/",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )
        assert "WWW-Authenticate" in resp.headers


class TestBridgeRoutesRegistered:
    def test_bridge_page_route_exists(self, http_client: TestClient) -> None:
        # Without a session param it should return 400 (not 404)
        resp = http_client.get("/site/escape/bridge")
        assert resp.status_code == 400

    def test_bridge_status_route_exists(self, http_client: TestClient) -> None:
        resp = http_client.get("/site/escape/bridge/status")
        assert resp.status_code == 400


class TestServeHTTPValidation:
    def test_missing_rucio_cfg_exits_nonzero(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                sites=["escape"],
                rucio_cfg=tmp_path / "nonexistent.cfg",
            )
        assert exc_info.value.code != 0

    def test_x509_site_in_http_mode_exits_nonzero(self, tmp_path: Path) -> None:
        cfg = tmp_path / "rucio.cfg"
        cfg.write_text(
            textwrap.dedent("""\
                [client]
                rucio_host = https://rucio.atlas.cern.ch
                auth_host = https://atlas-auth.cern.ch
                account = gstark
                auth_type = x509_proxy
            """)
        )
        with pytest.raises(SystemExit) as exc_info:
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                sites=["escape"],
                rucio_cfg=cfg,
            )
        assert exc_info.value.code != 0

    def test_x509_site_error_mentions_stdio_mode(self, tmp_path: Path, capsys) -> None:
        cfg = tmp_path / "rucio.cfg"
        cfg.write_text(
            textwrap.dedent("""\
                [client]
                rucio_host = https://rucio.atlas.cern.ch
                auth_host = https://atlas-auth.cern.ch
                account = gstark
                auth_type = x509_proxy
            """)
        )
        with pytest.raises(SystemExit):
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                sites=["escape"],
                rucio_cfg=cfg,
            )
        assert "stdio" in capsys.readouterr().err
