"""Tests for the HTTP transport: multi-site path-prefix routing, OAuth metadata, bridge wiring."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.shared.auth import OAuthClientInformationFull
from prometheus_client import REGISTRY, Counter, generate_latest
from prometheus_client.registry import CollectorRegistry
from pydantic import AnyUrl

if TYPE_CHECKING:
    from pathlib import Path
from starlette.testclient import TestClient

from rucio_mcp.metrics import BridgeStatsCollector
from rucio_mcp.server import _make_http_app, _make_shared_secret_app, serve


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

    def test_authorization_server_metadata_advertises_cimd(
        self, http_client: TestClient
    ) -> None:
        # Assert on the RFC 8414 §3 canonical location — the URL clients actually
        # construct during discovery (well-known segment inserted between host and
        # the issuer's path).  Claude selects CIMD when the AS metadata advertises
        # both client_id_metadata_document_supported and "none" in
        # token_endpoint_auth_methods_supported (public client, PKCE-only).
        # The directly-mounted artifact path is proven identical by
        # test_rfc8414_metadata_content_matches_site_metadata.
        data = http_client.get(
            "/.well-known/oauth-authorization-server/site/escape"
        ).json()
        assert data.get("client_id_metadata_document_supported") is True
        assert "none" in data.get("token_endpoint_auth_methods_supported", [])

    def test_authorization_server_metadata_has_no_registration_endpoint(
        self, http_client: TestClient
    ) -> None:
        # DCR is disabled — no /register endpoint is advertised.
        data = http_client.get(
            "/.well-known/oauth-authorization-server/site/escape"
        ).json()
        assert "registration_endpoint" not in data

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
    """Per-site discovery + CIMD-only client identity across multiple sites.

    RFC 8414 §3.1: all issuers have path components (e.g. http://host/site/escape),
    so there is no host-level issuer — the bare-root AS metadata and OAuth
    endpoints MUST NOT be served (regression guard for PR #29).  DCR is disabled
    entirely; clients are identified by CIMD (an https client_id URL), which is
    validated independently per site.
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

    def test_site_register_is_404(self, multi_site_client: TestClient) -> None:
        # DCR is disabled — no per-site /register endpoint exists either.
        resp = multi_site_client.post("/site/atlas/register", json={})
        assert resp.status_code == 404

    def test_cimd_client_id_accepted_by_authorize(
        self, multi_site_client: TestClient
    ) -> None:
        # A CIMD client_id (https URL) is resolved at /authorize; the document
        # fetch is patched.  302 (bridge or error redirect) — not a 400 — proves
        # the client_id was accepted rather than rejected as unknown.
        cimd_id = "https://claude.ai/.well-known/oauth-client"
        redirect = "http://localhost:9999/cb"
        resolved = OAuthClientInformationFull(
            client_id=cimd_id,
            redirect_uris=[AnyUrl(redirect)],
            token_endpoint_auth_method="none",
        )
        with patch(
            "rucio_mcp.auth.bridge_provider.resolve_cimd_client",
            AsyncMock(return_value=resolved),
        ):
            resp = multi_site_client.get(
                "/site/atlas/authorize",
                params={
                    "client_id": cimd_id,
                    "response_type": "code",
                    "redirect_uri": redirect,
                    "code_challenge": "x" * 43,
                    "code_challenge_method": "S256",
                    "resource": "http://localhost:8000/site/atlas",
                },
                follow_redirects=False,
            )
        assert resp.status_code == 302

    def test_cimd_reauth_with_new_ephemeral_port_accepted(
        self, multi_site_client: TestClient
    ) -> None:
        # Claude Code binds a fresh loopback port on every auth attempt; the
        # second /authorize must not be validated against the port from the
        # first attempt via the cached CIMD client (regression for
        # "Redirect URI ... not registered for client" on re-auth).
        cimd_id = "https://claude.ai/.well-known/oauth-client"
        resolved = OAuthClientInformationFull(
            client_id=cimd_id,
            redirect_uris=[AnyUrl("http://localhost/callback")],
            token_endpoint_auth_method="none",
        )
        with (
            patch(
                "rucio_mcp.auth.bridge_provider.resolve_cimd_client",
                AsyncMock(return_value=resolved),
            ),
            patch(
                "rucio_mcp.auth.rucio_oidc_poller.RucioOidcPoller.request_auth_url",
                AsyncMock(return_value="https://idp.example.com/login"),
            ),
        ):
            for port in (54321, 55985):
                resp = multi_site_client.get(
                    "/site/atlas/authorize",
                    params={
                        "client_id": cimd_id,
                        "response_type": "code",
                        "redirect_uri": f"http://localhost:{port}/callback",
                        "code_challenge": "x" * 43,
                        "code_challenge_method": "S256",
                        "resource": "http://localhost:8000/site/atlas",
                    },
                    follow_redirects=False,
                )
                assert resp.status_code == 302
                assert "/bridge?session=" in resp.headers["location"]


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


class TestPrometheusMiddlewareASGI:
    """The pure-ASGI PrometheusMiddleware records duration and clears in-progress."""

    def test_processing_time_histogram_records_request(
        self, http_client: TestClient
    ) -> None:
        labels = {"method": "GET", "path_template": "/", "site": ""}
        before = (
            REGISTRY.get_sample_value(
                "starlette_requests_processing_time_seconds_count", labels
            )
            or 0.0
        )
        http_client.get("/")
        after = (
            REGISTRY.get_sample_value(
                "starlette_requests_processing_time_seconds_count", labels
            )
            or 0.0
        )
        assert after - before == 1.0

    def test_in_progress_gauge_returns_to_baseline(
        self, http_client: TestClient
    ) -> None:
        labels = {"method": "GET", "path_template": "/", "site": ""}
        before = (
            REGISTRY.get_sample_value("starlette_requests_in_progress", labels) or 0.0
        )
        http_client.get("/")
        # Gauge is incremented on entry and decremented in the finally block, so a
        # completed request must leave it unchanged.
        after = (
            REGISTRY.get_sample_value("starlette_requests_in_progress", labels) or 0.0
        )
        assert after == before


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


class TestSharedSecretMode:
    """HTTP transport gated by a server-wide static bearer secret.

    Serves a single pre-built env client (patched here) behind a TokenVerifier;
    no OAuth bridge, no OIDC, single site.
    """

    @pytest.fixture
    def shared_secret_client(self):
        with patch("rucio_mcp.server.Client", MagicMock()):
            app = _make_shared_secret_app(
                site_name="escape",
                resource_url="http://localhost:8000",
                read_only=False,
                secret="s3cr3t",
            )
            with TestClient(app, raise_server_exceptions=True) as client:
                yield client

    def test_no_auth_returns_401(self, shared_secret_client: TestClient) -> None:
        resp = shared_secret_client.post(
            "/site/escape/",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )
        assert resp.status_code == 401

    def test_401_has_www_authenticate_header(
        self, shared_secret_client: TestClient
    ) -> None:
        resp = shared_secret_client.post(
            "/site/escape/",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )
        assert "WWW-Authenticate" in resp.headers

    def test_wrong_secret_returns_401(self, shared_secret_client: TestClient) -> None:
        resp = shared_secret_client.post(
            "/site/escape/",
            headers={"Authorization": "Bearer wrong"},
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )
        assert resp.status_code == 401

    def test_correct_secret_passes_auth(self, shared_secret_client: TestClient) -> None:
        # A valid bearer clears the auth gate; the streamable layer may still
        # reject the (handshake-less) request, but it must NOT be a 401.
        resp = shared_secret_client.post(
            "/site/escape/",
            headers={
                "Authorization": "Bearer s3cr3t",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )
        assert resp.status_code != 401

    def test_no_authorization_server_metadata(
        self, shared_secret_client: TestClient
    ) -> None:
        # No OAuth AS in shared-secret mode → AS metadata must not exist.
        resp = shared_secret_client.get(
            "/site/escape/.well-known/oauth-authorization-server"
        )
        assert resp.status_code == 404

    def test_no_authorize_endpoint(self, shared_secret_client: TestClient) -> None:
        resp = shared_secret_client.get("/site/escape/authorize")
        assert resp.status_code == 404

    def test_no_register_endpoint(self, shared_secret_client: TestClient) -> None:
        resp = shared_secret_client.post("/site/escape/register", json={})
        assert resp.status_code == 404

    def test_no_bridge_route(self, shared_secret_client: TestClient) -> None:
        resp = shared_secret_client.get("/site/escape/bridge")
        assert resp.status_code == 404

    def test_healthz_returns_200(self, shared_secret_client: TestClient) -> None:
        assert shared_secret_client.get("/healthz").status_code == 200

    def test_root_landing_returns_200(self, shared_secret_client: TestClient) -> None:
        resp = shared_secret_client.get("/")
        assert resp.status_code == 200
        assert "escape" in resp.text


class TestServeSharedSecretValidation:
    def test_multiple_sites_with_shared_secret_exits_nonzero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                sites=["escape", "atlas"],
                shared_secret="s3cr3t",
            )
        assert exc_info.value.code != 0

    def test_x509_cfg_accepted_in_shared_secret_mode(self, tmp_path: Path) -> None:
        # Unlike OIDC HTTP mode, shared-secret mode honors --auth-type and serves
        # a pre-authenticated (e.g. x509) client, so an x509 cfg must NOT exit.
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
        with (
            patch("rucio_mcp.server._make_shared_secret_app") as mock_app,
            patch("rucio_mcp.server.start_metrics_server"),
            patch("rucio_mcp.server.uvicorn.run") as mock_run,
        ):
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                sites=["atlas"],
                shared_secret="s3cr3t",
                rucio_cfg=cfg,
                auth_type="x509",
            )
        assert mock_app.called
        assert mock_run.called
