"""Tests for the HTTP transport: multi-site path-prefix routing, OAuth metadata, bridge wiring."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from prometheus_client import REGISTRY, Counter, generate_latest
from prometheus_client.registry import CollectorRegistry

if TYPE_CHECKING:
    from pathlib import Path
from starlette.testclient import TestClient

from rucio_mcp.metrics import BridgeStatsCollector
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

    def test_root_metadata_returns_404(self, http_client: TestClient) -> None:
        # RFC 8414 §3.1: when all issuers have path components (e.g.
        # http://host/site/escape), there is no host-level issuer and the bare-root
        # AS metadata MUST NOT exist.  Serving it caused a phantom atlas issuer that
        # broke non-path-aware clients authenticating to non-first sites.
        resp = http_client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 404

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


class TestNoRootOAuthFallback:
    """Root-level OAuth endpoints must not exist (RFC 8414 §3.1 compliance).

    All issuers have path components (e.g. http://host/site/escape), so there is
    no host-level issuer.  Serving root /register, /authorize, /token proxied to
    the first site created a phantom issuer that caused non-first sites to register
    at the wrong provider and receive "Client ID not found" on authorize.
    """

    def test_root_register_is_404(self, http_client: TestClient) -> None:
        resp = http_client.post("/register", json={})
        assert resp.status_code == 404

    def test_root_token_is_404(self, http_client: TestClient) -> None:
        resp = http_client.post("/token", json={})
        assert resp.status_code == 404

    def test_root_authorize_is_404(self, http_client: TestClient) -> None:
        resp = http_client.get("/authorize")
        assert resp.status_code == 404


class TestMultiSiteOAuthIsolation:
    """Regression: root AS metadata must not register clients into the wrong site provider.

    Previously the root /.well-known/oauth-authorization-server proxied to sub_apps[0]
    (the first site), so clients authenticating to a non-first site would:
      1. GET /.well-known/oauth-authorization-server → atlas registration_endpoint
      2. POST /site/atlas/register → client_id stored in atlas's provider
      3. GET /site/escape/authorize?client_id=… → 400 "Client ID not found"
    Removing the root fallback forces all clients onto path-aware per-site discovery.
    """

    @pytest.fixture
    def atlas_rucio_cfg(self, tmp_path: Path) -> Path:
        p = tmp_path / "atlas.cfg"
        p.write_text(
            textwrap.dedent("""\
                [client]
                rucio_host = https://rucio.atlas.cern.ch
                auth_host = https://atlas-rucio-auth.cern.ch
                account = gstark
                oidc_audience = rucio
                oidc_issuer = atlas
                oidc_scope = openid profile offline_access
            """)
        )
        return p

    @pytest.fixture
    def multi_site_app(self, atlas_rucio_cfg: Path, oidc_rucio_cfg: Path):
        return _make_http_app(
            sites=["atlas", "escape"],
            resource_url="http://localhost:8000",
            read_only=False,
            host="127.0.0.1",
            port=8000,
            rucio_cfg_overrides={"atlas": atlas_rucio_cfg, "escape": oidc_rucio_cfg},
        )

    @pytest.fixture
    def multi_site_client(self, multi_site_app):
        return TestClient(multi_site_app, raise_server_exceptions=True)

    def test_root_as_metadata_is_404(self, multi_site_client: TestClient) -> None:
        # No phantom host-level issuer must be served.
        resp = multi_site_client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 404

    def test_root_register_is_404(self, multi_site_client: TestClient) -> None:
        resp = multi_site_client.post("/register", json={})
        assert resp.status_code == 404

    def test_atlas_client_id_rejected_by_escape_authorize(
        self, multi_site_client: TestClient
    ) -> None:
        # Register at atlas — client_id lands in atlas's provider.
        reg_resp = multi_site_client.post(
            "/site/atlas/register",
            json={
                "client_name": "test-client",
                "redirect_uris": ["http://localhost:9999/cb"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        assert reg_resp.status_code == 201
        client_id = reg_resp.json()["client_id"]

        # That same client_id must be unknown to escape's provider → 400.
        resp = multi_site_client.get(
            "/site/escape/authorize",
            params={
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": "http://localhost:9999/cb",
                "code_challenge": "x" * 43,
                "code_challenge_method": "S256",
                "resource": "http://localhost:8000/site/escape",
            },
        )
        assert resp.status_code == 400

    def test_atlas_client_id_accepted_by_atlas_authorize(
        self, multi_site_client: TestClient
    ) -> None:
        # Register at atlas — client_id must be found by atlas's own authorize.
        reg_resp = multi_site_client.post(
            "/site/atlas/register",
            json={
                "client_name": "test-client",
                "redirect_uris": ["http://localhost:9999/cb"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        assert reg_resp.status_code == 201
        client_id = reg_resp.json()["client_id"]

        # atlas/authorize must redirect (302), not return 400.
        resp = multi_site_client.get(
            "/site/atlas/authorize",
            params={
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": "http://localhost:9999/cb",
                "code_challenge": "x" * 43,
                "code_challenge_method": "S256",
                "resource": "http://localhost:8000/site/atlas",
            },
            follow_redirects=False,
        )
        # 302 = bridge started; anything but 400 means the client_id was found.
        assert resp.status_code == 302


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

    def test_mcp_post_without_trailing_slash_returns_401(
        self, http_client: TestClient
    ) -> None:
        # Clients following the resource URL from OAuth metadata send requests
        # without a trailing slash; the server must route them, not 404.
        resp = http_client.post(
            "/site/escape",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )
        assert resp.status_code == 401

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
    def test_main_app_metrics_route_removed(self, http_client: TestClient) -> None:
        resp = http_client.get("/metrics")
        assert resp.status_code == 404


class TestBridgeStatsCollector:
    def test_bridge_stats_collector_emits_bridge_sessions_gauge(self) -> None:
        mock_store = MagicMock()
        mock_store.session_counts.return_value = {"pending": 2, "done": 1}
        mock_cache = MagicMock()
        mock_cache.size.return_value = 3

        registry = CollectorRegistry()
        registry.register(BridgeStatsCollector({"escape": (mock_store, mock_cache)}))
        output = generate_latest(registry).decode()

        assert "rucio_mcp_bridge_sessions" in output
        assert 'site="escape"' in output
        assert 'status="pending"' in output
        assert "2.0" in output

    def test_bridge_stats_collector_emits_cached_clients_gauge(self) -> None:
        mock_store = MagicMock()
        mock_store.session_counts.return_value = {}
        mock_cache = MagicMock()
        mock_cache.size.return_value = 5

        registry = CollectorRegistry()
        registry.register(BridgeStatsCollector({"escape": (mock_store, mock_cache)}))
        output = generate_latest(registry).decode()

        assert "rucio_mcp_cached_clients" in output
        assert 'site="escape"' in output
        assert "5.0" in output


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

    def test_root_site_url_has_trailing_slash(self, http_client: TestClient) -> None:
        # Landing page URLs must include a trailing slash so MCP clients
        # that use them verbatim send requests to /site/escape/ which the
        # Mount handles cleanly.
        resp = http_client.get("/")
        assert "/site/escape/" in resp.text

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

    def test_root_contains_rucio_logo_link(self, http_client: TestClient) -> None:
        resp = http_client.get("/")
        assert "rucio.cern.ch" in resp.text


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

    def test_cfg_without_auth_type_accepted_in_http_mode(self, tmp_path: Path) -> None:
        cfg = tmp_path / "rucio.cfg"
        cfg.write_text(
            textwrap.dedent("""\
                [client]
                rucio_host = https://vre-rucio.cern.ch
                auth_host = https://vre-rucio-auth.cern.ch
                oidc_audience = rucio
            """)
        )
        app = _make_http_app(
            sites=["escape"],
            resource_url="http://localhost:8000",
            read_only=False,
            host="127.0.0.1",
            port=8000,
            rucio_cfg_overrides={"escape": cfg},
        )
        assert app is not None

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


class TestSiteLabelOnHTTPMetrics:
    """starlette_* metrics must carry a site label, enabling $site variable filtering."""

    def test_site_mcp_request_records_site_label(self, http_client: TestClient) -> None:
        before = (
            REGISTRY.get_sample_value(
                "starlette_requests_total",
                {"method": "POST", "path_template": "/site/{site}", "site": "escape"},
            )
            or 0.0
        )
        http_client.post("/site/escape", json={})
        after = (
            REGISTRY.get_sample_value(
                "starlette_requests_total",
                {"method": "POST", "path_template": "/site/{site}", "site": "escape"},
            )
            or 0.0
        )
        assert after - before == 1.0

    def test_root_request_records_empty_site(self, http_client: TestClient) -> None:
        before = (
            REGISTRY.get_sample_value(
                "starlette_requests_total",
                {"method": "GET", "path_template": "/", "site": ""},
            )
            or 0.0
        )
        http_client.get("/")
        after = (
            REGISTRY.get_sample_value(
                "starlette_requests_total",
                {"method": "GET", "path_template": "/", "site": ""},
            )
            or 0.0
        )
        assert after - before == 1.0

    def test_well_known_auth_server_per_site_records_site_and_normalized_path(
        self, http_client: TestClient
    ) -> None:
        before = (
            REGISTRY.get_sample_value(
                "starlette_requests_total",
                {
                    "method": "GET",
                    "path_template": "/.well-known/oauth-authorization-server/site/{site}",
                    "site": "escape",
                },
            )
            or 0.0
        )
        http_client.get("/.well-known/oauth-authorization-server/site/escape")
        after = (
            REGISTRY.get_sample_value(
                "starlette_requests_total",
                {
                    "method": "GET",
                    "path_template": "/.well-known/oauth-authorization-server/site/{site}",
                    "site": "escape",
                },
            )
            or 0.0
        )
        assert after - before == 1.0


class TestNoCreatedSeries:
    def test_no_created_series_in_metrics_output(self) -> None:
        """Counters and histograms must not emit _created timestamp series."""
        registry = CollectorRegistry()
        c = Counter("noise_test_counter", "test counter", registry=registry)
        c.inc()
        output = generate_latest(registry).decode()
        assert "_created" not in output


class TestHealthzEndpoint:
    def test_healthz_returns_200(self, http_client: TestClient) -> None:
        resp = http_client.get("/healthz")
        assert resp.status_code == 200

    def test_healthz_response_body_is_ok(self, http_client: TestClient) -> None:
        resp = http_client.get("/healthz")
        assert "ok" in resp.text.lower()

    def test_healthz_not_tracked_in_starlette_metrics(
        self, http_client: TestClient
    ) -> None:
        """Health-check requests must not appear in HTTP metrics."""
        before = REGISTRY.get_sample_value(
            "starlette_requests_total",
            {"method": "GET", "path_template": "/healthz"},
        )
        http_client.get("/healthz")
        after = REGISTRY.get_sample_value(
            "starlette_requests_total",
            {"method": "GET", "path_template": "/healthz"},
        )
        assert before == after  # excluded — counter must not move
