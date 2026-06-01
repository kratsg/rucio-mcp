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

    def test_root_metadata_proxies_to_first_site(self, http_client: TestClient) -> None:
        # TypeScript MCP SDK constructs well-known URL from AS URL origin (not path),
        # so root-level AS metadata must work for single-site setups.
        resp = http_client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200

    def test_root_metadata_content_has_required_fields(
        self, http_client: TestClient
    ) -> None:
        data = http_client.get("/.well-known/oauth-authorization-server").json()
        assert "issuer" in data
        assert "registration_endpoint" in data

    def test_rfc8414_well_known_path_returns_metadata(
        self, http_client: TestClient
    ) -> None:
        # RFC 8414 §3: for issuer http://host/path, well-known URL is
        # http://host/.well-known/oauth-authorization-server/path
        resp = http_client.get("/.well-known/oauth-authorization-server/site/escape")
        assert resp.status_code == 200

    def test_rfc8414_metadata_content_matches_site_metadata(
        self, http_client: TestClient
    ) -> None:
        site = http_client.get(
            "/site/escape/.well-known/oauth-authorization-server"
        ).json()
        rfc8414 = http_client.get(
            "/.well-known/oauth-authorization-server/site/escape"
        ).json()
        assert rfc8414 == site

    def test_rfc9728_protected_resource_path_returns_metadata(
        self, http_client: TestClient
    ) -> None:
        # RFC 9728: for resource http://host/path, well-known URL is
        # http://host/.well-known/oauth-protected-resource/path
        resp = http_client.get("/.well-known/oauth-protected-resource/site/escape")
        assert resp.status_code == 200

    def test_rfc9728_protected_resource_has_authorization_servers(
        self, http_client: TestClient
    ) -> None:
        data = http_client.get(
            "/.well-known/oauth-protected-resource/site/escape"
        ).json()
        assert "authorization_servers" in data or "resource" in data


class TestRootOAuthEndpointFallback:
    """Root-level OAuth endpoint proxies for TypeScript MCP SDK compatibility.

    The TypeScript MCP SDK constructs OAuth endpoints using
    ``new URL('/endpoint', asUrl)`` with a leading slash, which makes the
    path origin-relative (strips the /site/name path from asUrl). These tests
    verify that root-level endpoints proxy to the first site's sub-app.
    """

    def test_root_register_proxies_not_404(self, http_client: TestClient) -> None:
        resp = http_client.post("/register", json={})
        assert resp.status_code != 404

    def test_root_token_proxies_not_404(self, http_client: TestClient) -> None:
        resp = http_client.post("/token", json={})
        assert resp.status_code != 404

    def test_root_authorize_proxies_not_404(self, http_client: TestClient) -> None:
        resp = http_client.get("/authorize")
        assert resp.status_code != 404


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

    def test_mcp_post_without_trailing_slash_does_not_redirect(
        self, http_client: TestClient
    ) -> None:
        # Nginx ingresses commonly strip trailing slashes before forwarding to the
        # pod. If Starlette issues a 307 for /site/escape → /site/escape/, and the
        # ingress strips the slash again, the client loops forever. Verify that
        # /site/escape (no trailing slash) is handled directly — not redirected.
        resp = http_client.post(
            "/site/escape",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            follow_redirects=False,
        )
        assert resp.status_code != 307


class TestBridgeRoutesRegistered:
    def test_bridge_page_route_exists(self, http_client: TestClient) -> None:
        # Without a session param it should return 400 (not 404)
        resp = http_client.get("/site/escape/bridge")
        assert resp.status_code == 400

    def test_bridge_status_route_exists(self, http_client: TestClient) -> None:
        resp = http_client.get("/site/escape/bridge/status")
        assert resp.status_code == 400


class TestMetricsEndpoint:
    def test_metrics_returns_200(self, http_client: TestClient) -> None:
        resp = http_client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type_is_prometheus(self, http_client: TestClient) -> None:
        resp = http_client.get("/metrics")
        assert "text/plain" in resp.headers["content-type"]

    def test_metrics_contains_bridge_sessions_gauge(
        self, http_client: TestClient
    ) -> None:
        resp = http_client.get("/metrics")
        assert "rucio_mcp_bridge_sessions" in resp.text

    def test_metrics_contains_cached_clients_gauge(
        self, http_client: TestClient
    ) -> None:
        resp = http_client.get("/metrics")
        assert "rucio_mcp_cached_clients" in resp.text

    def test_metrics_contains_starlette_http_counters(
        self, http_client: TestClient
    ) -> None:
        http_client.get("/metrics")  # generate at least one request first
        resp = http_client.get("/metrics")
        assert "starlette_requests_total" in resp.text


class TestRootLandingPage:
    def test_root_returns_200(self, http_client: TestClient) -> None:
        resp = http_client.get("/")
        assert resp.status_code == 200

    def test_root_content_type_is_html(self, http_client: TestClient) -> None:
        resp = http_client.get("/")
        assert "text/html" in resp.headers["content-type"]

    def test_root_contains_site_name(self, http_client: TestClient) -> None:
        resp = http_client.get("/")
        assert "escape" in resp.text

    def test_root_contains_site_mcp_url(self, http_client: TestClient) -> None:
        resp = http_client.get("/")
        assert "/site/escape" in resp.text

    def test_root_contains_github_link(self, http_client: TestClient) -> None:
        resp = http_client.get("/")
        assert "github.com/kratsg/rucio-mcp" in resp.text

    def test_root_contains_docs_link(self, http_client: TestClient) -> None:
        resp = http_client.get("/")
        assert "rucio-mcp.readthedocs.io" in resp.text

    def test_root_contains_copyright(self, http_client: TestClient) -> None:
        resp = http_client.get("/")
        assert "Giordon Stark" in resp.text

    def test_root_contains_version(self, http_client: TestClient) -> None:
        resp = http_client.get("/")
        assert "rucio-mcp" in resp.text

    def test_root_does_not_mention_atlas(self, http_client: TestClient) -> None:
        # The server is generic Rucio, not ATLAS-specific
        resp = http_client.get("/")
        assert "ATLAS" not in resp.text

    def test_root_shows_read_write_mode_by_default(
        self, http_client: TestClient
    ) -> None:
        resp = http_client.get("/")
        assert "read-write" in resp.text.lower() or "read/write" in resp.text.lower()

    def test_root_shows_read_only_when_configured(self, oidc_rucio_cfg: Path) -> None:
        app = _make_http_app(
            sites=["escape"],
            resource_url="http://localhost:8000",
            read_only=True,
            host="127.0.0.1",
            port=8000,
            rucio_cfg_overrides={"escape": oidc_rucio_cfg},
        )
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/")
        assert "read-only" in resp.text.lower() or "read only" in resp.text.lower()

    def test_root_quick_start_shows_claude_command(
        self, http_client: TestClient
    ) -> None:
        resp = http_client.get("/")
        assert "claude mcp add" in resp.text

    def test_root_quick_start_shows_codex_command(
        self, http_client: TestClient
    ) -> None:
        resp = http_client.get("/")
        assert "codex mcp add" in resp.text

    def test_root_quick_start_shows_gemini_command(
        self, http_client: TestClient
    ) -> None:
        resp = http_client.get("/")
        assert "gemini mcp add" in resp.text

    def test_root_quick_start_shows_opencode_command(
        self, http_client: TestClient
    ) -> None:
        resp = http_client.get("/")
        assert "opencode mcp add" in resp.text

    def test_root_quick_start_contains_site_url(self, http_client: TestClient) -> None:
        resp = http_client.get("/")
        assert "localhost:8000/site/escape" in resp.text


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
