"""Tests for the HTTP transport: OAuth metadata endpoints and bridge wiring."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from rucio_mcp.server import _make_http_mcp


@pytest.fixture
def rucio_cfg(tmp_path: Path) -> Path:
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
def http_mcp(rucio_cfg: Path):
    return _make_http_mcp(
        read_only=False,
        host="127.0.0.1",
        port=8000,
        resource_url="http://localhost:8000",
        rucio_cfg_path=rucio_cfg,
    )


@pytest.fixture
def http_client(http_mcp):
    return TestClient(http_mcp.streamable_http_app(), raise_server_exceptions=True)


class TestOAuthMetadataEndpoints:
    def test_authorization_server_metadata_reachable(
        self, http_client: TestClient
    ) -> None:
        resp = http_client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200

    def test_authorization_server_metadata_has_required_fields(
        self, http_client: TestClient
    ) -> None:
        data = http_client.get("/.well-known/oauth-authorization-server").json()
        assert "issuer" in data
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "registration_endpoint" in data

    def test_authorization_server_issuer_matches_resource_url(
        self, http_client: TestClient
    ) -> None:
        data = http_client.get("/.well-known/oauth-authorization-server").json()
        # pydantic AnyHttpUrl normalizes by appending a trailing slash
        assert data["issuer"].rstrip("/") == "http://localhost:8000"

    def test_protected_resource_metadata_reachable(
        self, http_client: TestClient
    ) -> None:
        resp = http_client.get("/.well-known/oauth-protected-resource")
        assert resp.status_code == 200

    def test_protected_resource_metadata_has_authorization_servers(
        self, http_client: TestClient
    ) -> None:
        data = http_client.get("/.well-known/oauth-protected-resource").json()
        assert "authorization_servers" in data
        # pydantic AnyHttpUrl normalizes by appending a trailing slash
        assert any(
            s.rstrip("/") == "http://localhost:8000"
            for s in data["authorization_servers"]
        )


class TestUnauthenticatedAccess:
    def test_mcp_post_without_auth_returns_401(self, http_client: TestClient) -> None:
        resp = http_client.post(
            "/",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )
        assert resp.status_code == 401

    def test_401_response_has_www_authenticate_header(
        self, http_client: TestClient
    ) -> None:
        resp = http_client.post(
            "/",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )
        assert "WWW-Authenticate" in resp.headers


class TestBridgeRoutesRegistered:
    def test_bridge_page_route_exists(self, http_client: TestClient) -> None:
        # Without a session param it should return 400 (not 404)
        resp = http_client.get("/bridge")
        assert resp.status_code == 400

    def test_bridge_status_route_exists(self, http_client: TestClient) -> None:
        resp = http_client.get("/bridge/status")
        assert resp.status_code == 400


class TestServeHTTPWithCfg:
    def test_missing_rucio_cfg_exits_nonzero(self, tmp_path: Path) -> None:
        from rucio_mcp.server import serve

        with pytest.raises(SystemExit) as exc_info:
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                rucio_cfg=tmp_path / "nonexistent.cfg",
            )
        assert exc_info.value.code != 0

    def test_rucio_cfg_error_message_mentions_init(
        self, tmp_path: Path, capsys
    ) -> None:
        from rucio_mcp.server import serve

        with pytest.raises(SystemExit):
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                rucio_cfg=tmp_path / "nonexistent.cfg",
            )
        assert "init" in capsys.readouterr().err
