"""Tests for server startup preflight checks and ping."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.mcpserver import MCPServer
from prometheus_client import REGISTRY
from starlette.testclient import TestClient

from rucio_mcp.auth.rucio_cfg import RucioCfg
from rucio_mcp.presets import PRESETS
from rucio_mcp.server import (
    _build_instructions,
    _InstrumentedFastMCP,
    _make_site_mcp,
    _make_stdio_mcp,
    _preflight_check,
    _resolve_cfg_path,
    ping_server,
    serve,
)


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

    def test_auth_type_defaults_to_oidc(self, valid_cfg: Path) -> None:
        with patch.dict("os.environ", {}, clear=True):
            _preflight_check(valid_cfg)
            assert os.environ["RUCIO_AUTH_TYPE"] == "oidc"

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

    def test_auth_type_read_from_oidc_cfg(self, tmp_path: Path) -> None:
        """auth_type=oidc in the cfg is propagated to RUCIO_AUTH_TYPE when no override/env."""
        cfg = tmp_path / "rucio.cfg"
        cfg.write_text(
            textwrap.dedent("""\
                [client]
                rucio_host = https://rucio.example.com
                auth_host = https://rucio-auth.example.com
                auth_type = oidc
            """)
        )
        with patch.dict("os.environ", {}, clear=True):
            _preflight_check(cfg)
            assert os.environ["RUCIO_AUTH_TYPE"] == "oidc"

    def test_oidc_cfg_does_not_set_x509_proxy_env(self, tmp_path: Path) -> None:
        """An OIDC cfg must not set X509_USER_PROXY."""
        cfg = tmp_path / "rucio.cfg"
        cfg.write_text(
            textwrap.dedent("""\
                [client]
                rucio_host = https://rucio.example.com
                auth_host = https://rucio-auth.example.com
                auth_type = oidc
            """)
        )
        with patch.dict("os.environ", {}, clear=True):
            _preflight_check(cfg)
            assert "X509_USER_PROXY" not in os.environ

    def test_oidc_cfg_does_not_emit_x509_warnings(self, tmp_path: Path, capsys) -> None:
        """An OIDC cfg must not produce x509 proxy warnings."""
        cfg = tmp_path / "rucio.cfg"
        cfg.write_text(
            textwrap.dedent("""\
                [client]
                rucio_host = https://rucio.example.com
                auth_host = https://rucio-auth.example.com
                auth_type = oidc
            """)
        )
        with patch.dict("os.environ", {}, clear=True):
            _preflight_check(cfg)
        err = capsys.readouterr().err
        assert "X509" not in err
        assert "voms-proxy-init" not in err

    def test_x509_alias_normalizes_to_x509_proxy(self, valid_cfg: Path) -> None:
        """--auth-type x509 (friendly alias) must resolve to x509_proxy in RUCIO_AUTH_TYPE."""
        with patch.dict("os.environ", {}, clear=True):
            _preflight_check(valid_cfg, auth_type_override="x509")
            assert os.environ["RUCIO_AUTH_TYPE"] == "x509_proxy"

    def test_x509_cert_default_set_when_auth_type_is_bare_x509(
        self, valid_cfg: Path
    ) -> None:
        """When auth_type=x509 (bare cert), RUCIO_CLIENT_CERT must default to ~/.globus/usercert.pem."""
        env = {"RUCIO_AUTH_TYPE": "x509"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)
            assert os.environ.get("RUCIO_CLIENT_CERT") == str(
                Path("~/.globus/usercert.pem").expanduser()
            )

    def test_x509_key_default_set_when_auth_type_is_bare_x509(
        self, valid_cfg: Path
    ) -> None:
        """When auth_type=x509 (bare cert), RUCIO_CLIENT_KEY must default to ~/.globus/userkey.pem."""
        env = {"RUCIO_AUTH_TYPE": "x509"}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)
            assert os.environ.get("RUCIO_CLIENT_KEY") == str(
                Path("~/.globus/userkey.pem").expanduser()
            )

    def test_x509_explicit_cert_not_overridden(
        self, valid_cfg: Path, tmp_path: Path
    ) -> None:
        """Explicitly set RUCIO_CLIENT_CERT must not be overwritten by the default."""
        cert = tmp_path / "mycert.pem"
        cert.touch()
        env = {"RUCIO_AUTH_TYPE": "x509", "RUCIO_CLIENT_CERT": str(cert)}
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)
            assert os.environ["RUCIO_CLIENT_CERT"] == str(cert)

    def test_x509_warns_when_cert_file_missing(self, valid_cfg: Path, capsys) -> None:
        """Missing cert file must produce a warning."""
        env = {
            "RUCIO_AUTH_TYPE": "x509",
            "RUCIO_CLIENT_CERT": "/nonexistent/cert.pem",
            "RUCIO_CLIENT_KEY": "/nonexistent/key.pem",
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)
        assert "RUCIO_CLIENT_CERT" in capsys.readouterr().err

    def test_x509_warns_when_key_file_missing(self, valid_cfg: Path, capsys) -> None:
        """Missing key file must produce a warning."""
        cert = valid_cfg  # reuse an existing file as the cert
        env = {
            "RUCIO_AUTH_TYPE": "x509",
            "RUCIO_CLIENT_CERT": str(cert),
            "RUCIO_CLIENT_KEY": "/nonexistent/key.pem",
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)
        assert "RUCIO_CLIENT_KEY" in capsys.readouterr().err

    def test_x509_no_warnings_when_cert_and_key_exist(
        self, valid_cfg: Path, tmp_path: Path, capsys
    ) -> None:
        """No warnings when cert and key files both exist."""
        cert = tmp_path / "usercert.pem"
        key = tmp_path / "userkey.pem"
        cert.touch()
        key.touch()
        env = {
            "RUCIO_AUTH_TYPE": "x509",
            "RUCIO_CLIENT_CERT": str(cert),
            "RUCIO_CLIENT_KEY": str(key),
        }
        with patch.dict("os.environ", env, clear=True):
            _preflight_check(valid_cfg)
        err = capsys.readouterr().err
        assert "RUCIO_CLIENT_CERT" not in err
        assert "RUCIO_CLIENT_KEY" not in err


class TestServeHTTP:
    def test_http_missing_resource_url_exits_nonzero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            serve(transport="http", resource_url=None)
        assert exc_info.value.code != 0

    def test_http_error_mentions_resource_url(self, capsys) -> None:
        with pytest.raises(SystemExit):
            serve(transport="http", resource_url=None)
        assert "resource-url" in capsys.readouterr().err

    def test_serve_warns_when_auth_type_passed_with_http(self, capsys) -> None:
        """Passing --auth-type with --transport http must emit a warning (it is ignored in HTTP mode)."""
        with (
            patch("rucio_mcp.server._make_http_app") as mock_make,
            patch("rucio_mcp.server.start_metrics_server"),
            patch("uvicorn.run"),
        ):
            mock_make.return_value = MagicMock()
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                sites=["escape"],
                auth_type="oidc",
            )
        err = capsys.readouterr().err
        assert "--auth-type" in err

    def test_serve_no_auth_type_warning_when_flag_omitted_http(self, capsys) -> None:
        """No --auth-type warning when the flag is omitted (auth_type=None) in HTTP mode."""
        with (
            patch("rucio_mcp.server._make_http_app") as mock_make,
            patch("rucio_mcp.server.start_metrics_server"),
            patch("uvicorn.run"),
        ):
            mock_make.return_value = MagicMock()
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                sites=["escape"],
                auth_type=None,
            )
        assert "--auth-type" not in capsys.readouterr().err

    def test_stdio_calls_preflight_http_does_not(self) -> None:
        """stdio path calls _preflight_check; http path does not."""
        with (
            patch("rucio_mcp.server._preflight_check") as mock_check,
            patch("rucio_mcp.server._make_http_app") as mock_make,
            patch("rucio_mcp.server.start_metrics_server"),
            patch("uvicorn.run"),
        ):
            mock_make.return_value = MagicMock()
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                sites=["escape"],
            )
        mock_check.assert_not_called()

    def test_uvicorn_proxy_headers_enabled_for_http(self) -> None:
        """HTTP transport must pass proxy_headers=True to uvicorn so X-Forwarded-For is logged."""
        with (
            patch("rucio_mcp.server._make_http_app") as mock_make,
            patch("rucio_mcp.server.start_metrics_server"),
            patch("uvicorn.run") as mock_run,
        ):
            mock_make.return_value = MagicMock()
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                sites=["escape"],
            )
        _, kwargs = mock_run.call_args
        assert kwargs.get("proxy_headers") is True

    def test_uvicorn_forwarded_allow_ips_default(self) -> None:
        """forwarded_allow_ips must default to '127.0.0.1' (trust only localhost proxy)."""
        with (
            patch("rucio_mcp.server._make_http_app") as mock_make,
            patch("rucio_mcp.server.start_metrics_server"),
            patch("uvicorn.run") as mock_run,
        ):
            mock_make.return_value = MagicMock()
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                sites=["escape"],
            )
        _, kwargs = mock_run.call_args
        assert kwargs.get("forwarded_allow_ips") == "127.0.0.1"

    def test_uvicorn_forwarded_allow_ips_custom(self) -> None:
        """A custom forwarded_allow_ips value must be forwarded to uvicorn."""
        with (
            patch("rucio_mcp.server._make_http_app") as mock_make,
            patch("rucio_mcp.server.start_metrics_server"),
            patch("uvicorn.run") as mock_run,
        ):
            mock_make.return_value = MagicMock()
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                sites=["escape"],
                forwarded_allow_ips="172.16.140.142",
            )
        _, kwargs = mock_run.call_args
        assert kwargs.get("forwarded_allow_ips") == "172.16.140.142"


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


@pytest.fixture
def oidc_rucio_cfg_server(tmp_path):
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


class TestInstrumentedFastMCP:
    def test_make_stdio_mcp_default_site_name_is_escape(self) -> None:
        mcp = _make_stdio_mcp()
        assert mcp._site_name == "escape"

    def test_make_stdio_mcp_returns_instrumented_instance(self) -> None:
        mcp = _make_stdio_mcp(site_name="atlas")
        assert isinstance(mcp, _InstrumentedFastMCP)
        assert mcp._site_name == "atlas"

    def test_make_site_mcp_returns_instrumented_instance(
        self, oidc_rucio_cfg_server
    ) -> None:
        cfg = RucioCfg.from_path(oidc_rucio_cfg_server)
        mcp, _, _ = _make_site_mcp(
            site_name="escape",
            cfg=cfg,
            resource_url="http://localhost:8000/site/escape",
            read_only=False,
        )
        assert isinstance(mcp, _InstrumentedFastMCP)
        assert mcp._site_name == "escape"

    async def test_tool_call_increments_tool_calls_counter(self) -> None:
        mcp = _InstrumentedFastMCP("test-mcp", site_name="testsite")

        before = (
            REGISTRY.get_sample_value(
                "rucio_mcp_tool_calls_total",
                {"site": "testsite", "tool": "rucio_ping"},
            )
            or 0.0
        )

        with patch.object(MCPServer, "call_tool", new=AsyncMock(return_value=[])):
            await mcp.call_tool("rucio_ping", {})

        after = (
            REGISTRY.get_sample_value(
                "rucio_mcp_tool_calls_total",
                {"site": "testsite", "tool": "rucio_ping"},
            )
            or 0.0
        )
        assert after - before == 1.0

    async def test_tool_call_records_duration(self) -> None:
        mcp = _InstrumentedFastMCP("test-mcp-dur", site_name="testsite_dur")

        before_count = (
            REGISTRY.get_sample_value(
                "rucio_mcp_tool_call_duration_seconds_count",
                {"site": "testsite_dur", "tool": "rucio_ping"},
            )
            or 0.0
        )

        with patch.object(MCPServer, "call_tool", new=AsyncMock(return_value=[])):
            await mcp.call_tool("rucio_ping", {})

        after_count = (
            REGISTRY.get_sample_value(
                "rucio_mcp_tool_call_duration_seconds_count",
                {"site": "testsite_dur", "tool": "rucio_ping"},
            )
            or 0.0
        )
        assert after_count - before_count == 1.0


_JSON_RPC_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _initialize_session(client: TestClient) -> dict[str, str]:
    """Do the MCP initialize handshake over *client* and return headers carrying the session id."""
    init_resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
        headers=_JSON_RPC_HEADERS,
    )
    session_id = init_resp.headers["mcp-session-id"]
    headers = {**_JSON_RPC_HEADERS, "mcp-session-id": session_id}
    client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=headers,
    )
    return headers


class TestStdioAppOverTheWire:
    """Wire-level assertions that bypass every unit test\'s tool.fn shortcut.

    Every existing tool test calls the raw callable directly, which never
    goes through the mcp SDK\'s serialization -- none of them would notice
    a missing `annotations`/`outputSchema` on the wire. These do, via a
    real JSON-RPC round trip through the built ASGI app (see A.4/A.1 of
    the interop plan). rucio_mcp.server.Client is patched so the stdio
    lifespan never dials a real Rucio server.
    """

    @pytest.fixture
    def app(self):
        with patch("rucio_mcp.server.Client") as mock_client_cls:
            mock_client_cls.return_value.ping.return_value = {"version": "35.6.0"}
            mcp = _make_stdio_mcp()
            yield mcp.streamable_http_app(
                streamable_http_path="/mcp", json_response=True
            )

    @pytest.fixture
    def client(self, app):
        with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
            yield test_client

    def test_tools_list_carries_annotations_and_output_schema(
        self, client: TestClient
    ) -> None:
        headers = _initialize_session(client)
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers=headers,
        )
        assert resp.status_code == 200
        tools = {tool["name"]: tool for tool in resp.json()["result"]["tools"]}
        assert len(tools) == 44
        for tool in tools.values():
            assert tool["annotations"]["readOnlyHint"] is not None
            assert tool["outputSchema"] is not None
        assert tools["rucio_ping"]["annotations"]["readOnlyHint"] is True
        assert tools["rucio_ping"]["annotations"]["openWorldHint"] is True
        assert tools["rucio_add_rule"]["annotations"]["readOnlyHint"] is False
        assert tools["rucio_delete_rule"]["annotations"]["destructiveHint"] is True

    def test_tools_call_carries_text_and_structured_content(
        self, client: TestClient
    ) -> None:
        headers = _initialize_session(client)
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "rucio_ping", "arguments": {}},
            },
            headers=headers,
        )
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["isError"] is False
        assert result["content"][0]["type"] == "text"
        assert "35.6.0" in result["content"][0]["text"]
        structured = result["structuredContent"]
        assert structured["version"] == "35.6.0"


class TestEveryToolDeclaresAnnotationsAndOutputSchema:
    """Drift guard: every rucio_* tool must publish annotations and an outputSchema.

    This is the one test that would catch a future tool being added (or an
    existing one being refactored) without following the
    Annotated[CallToolResult, Model] + ToolAnnotations pattern all 45 tools
    use today -- see CLAUDE.md's "Tool registration pattern" section.
    """

    def test_every_tool_declares_annotations_and_output_schema(self) -> None:
        mcp = _make_stdio_mcp()
        for tool in mcp._tool_manager.list_tools():
            assert tool.annotations is not None, tool.name
            assert tool.annotations.read_only_hint is not None, tool.name
            assert tool.output_schema is not None, tool.name

    def test_registers_forty_four_tools(self) -> None:
        """44 tools in stdio mode; rucio_token_info (HTTP-transport-only,
        see TestRucioTokenInfo in test_tools_ping.py) brings the fleet-wide
        total documented in the interop plan to 45."""
        mcp = _make_stdio_mcp()
        names = {tool.name for tool in mcp._tool_manager.list_tools()}
        assert len(names) == 44

    def test_mutating_and_destructive_tools_are_not_read_only(self) -> None:
        """Cross-check against check_write_allowed's 7 call sites (tools/rules.py):
        the mutating/destructive tool list must never drift from the
        annotations declared here."""
        mcp = _make_stdio_mcp()
        tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
        mutating = {
            "rucio_add_rule",
            "rucio_update_rule",
            "rucio_reduce_rule",
            "rucio_move_rule",
            "rucio_approve_rule",
            "rucio_deny_rule",
        }
        for name in mutating:
            annotations = tools[name].annotations
            assert annotations is not None, name
            assert annotations.read_only_hint is False, name
            assert annotations.destructive_hint is not True, name
        delete_annotations = tools["rucio_delete_rule"].annotations
        assert delete_annotations is not None
        assert delete_annotations.read_only_hint is False
        assert delete_annotations.destructive_hint is True


class TestResolveCfgPath:
    def test_warns_when_rucio_config_overridden_by_preset(self, capsys) -> None:
        """A set RUCIO_CONFIG that the bundled preset overrides must produce a warning."""
        with patch.dict(
            "os.environ", {"RUCIO_CONFIG": "/cvmfs/my/rucio.cfg"}, clear=True
        ):
            _resolve_cfg_path("atlas", None)
        err = capsys.readouterr().err
        assert "RUCIO_CONFIG" in err
        assert "--rucio-cfg" in err

    def test_no_warning_when_override_passed(self, tmp_path, capsys) -> None:
        """No warning when the user explicitly passes --rucio-cfg."""
        with patch.dict(
            "os.environ", {"RUCIO_CONFIG": "/cvmfs/my/rucio.cfg"}, clear=True
        ):
            _resolve_cfg_path("atlas", tmp_path / "custom.cfg")
        assert "WARNING" not in capsys.readouterr().err

    def test_no_warning_when_rucio_config_unset(self, capsys) -> None:
        with patch.dict("os.environ", {}, clear=True):
            _resolve_cfg_path("atlas", None)
        assert "RUCIO_CONFIG" not in capsys.readouterr().err


class TestServeStdioGuards:
    def test_stdio_multiple_sites_errors(self) -> None:
        """stdio transport must reject more than one --site rather than silently use sites[0]."""
        with pytest.raises(SystemExit) as exc:
            serve(transport="stdio", sites=["escape", "atlas"])
        assert exc.value.code != 0

    def test_stdio_multiple_sites_error_message(self, capsys) -> None:
        with pytest.raises(SystemExit):
            serve(transport="stdio", sites=["escape", "atlas"])
        assert "single site" in capsys.readouterr().err

    def test_shared_secret_with_stdio_errors(self) -> None:
        """--shared-secret with stdio must error out (help says it requires --transport http)."""
        with pytest.raises(SystemExit) as exc:
            serve(transport="stdio", sites=["escape"], shared_secret="s3cr3t")
        assert exc.value.code != 0

    def test_shared_secret_with_stdio_error_message(self, capsys) -> None:
        with pytest.raises(SystemExit):
            serve(transport="stdio", sites=["escape"], shared_secret="s3cr3t")
        assert "--transport http" in capsys.readouterr().err


class TestServeSharedSecret:
    def test_shared_secret_http_prints_notice(self, capsys) -> None:
        """Shared-secret HTTP mode must announce itself prominently on stderr."""
        with (
            patch("rucio_mcp.server._resolve_cfg_path"),
            patch("rucio_mcp.server._preflight_check"),
            patch("rucio_mcp.server._make_shared_secret_app") as mock_make,
            patch("rucio_mcp.server.start_metrics_server"),
            patch("uvicorn.run"),
        ):
            mock_make.return_value = MagicMock()
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                sites=["escape"],
                shared_secret="s3cr3t",
            )
        err = capsys.readouterr().err
        assert "shared-secret" in err.lower()


class TestServeHTTPMultiSite:
    def test_multi_site_rucio_cfg_dropped_warns(self, capsys) -> None:
        """--rucio-cfg is silently dropped for multi-site HTTP; must warn instead."""
        with (
            patch("rucio_mcp.server._make_http_app") as mock_make,
            patch("rucio_mcp.server.start_metrics_server"),
            patch("uvicorn.run"),
        ):
            mock_make.return_value = MagicMock()
            serve(
                transport="http",
                resource_url="http://localhost:8000",
                sites=["escape", "atlas"],
                rucio_cfg=Path("/tmp/custom.cfg"),
            )
        assert "--rucio-cfg" in capsys.readouterr().err


class TestBuildInstructions:
    def test_atlas_instructions_reference_nomenclature_resource(self) -> None:
        instructions = _build_instructions(PRESETS["atlas"])
        assert "rucio://nomenclature" in instructions

    def test_atlas_instructions_do_not_inline_nomenclature_content(self) -> None:
        instructions = _build_instructions(PRESETS["atlas"])
        assert "DAOD_PHYSLITE" not in instructions

    def test_escape_instructions_omit_nomenclature_resource(self) -> None:
        instructions = _build_instructions(PRESETS["escape"])
        assert "rucio://nomenclature" not in instructions

    def test_instructions_include_generic_preamble(self) -> None:
        instructions = _build_instructions(PRESETS["escape"])
        assert "Rucio" in instructions
