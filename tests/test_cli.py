"""Tests for the CLI argument parsing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from rucio_mcp.cli import main
from rucio_mcp.presets import PRESETS


class TestCLIServe:
    def test_serve_calls_run(self) -> None:
        with (
            patch("rucio_mcp.server.Client"),
            patch("rucio_mcp.server._InstrumentedFastMCP") as mock_mcp_cls,
            patch("rucio_mcp.server._preflight_check"),
            patch("sys.argv", ["rucio-mcp", "serve"]),
        ):
            mock_mcp_cls.return_value = MagicMock()
            main()
        mock_mcp_cls.assert_called_once()

    def test_read_only_flag_passed_to_lifespan(self) -> None:
        """--read-only must end up as read_only=True in the lifespan context."""
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch("sys.argv", ["rucio-mcp", "serve", "--read-only"]),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["read_only"] is True

    def test_default_is_not_read_only(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch("sys.argv", ["rucio-mcp", "serve"]),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["read_only"] is False

    def test_transport_defaults_to_stdio(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch("sys.argv", ["rucio-mcp", "serve"]),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["transport"] == "stdio"

    def test_site_defaults_to_escape(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch("sys.argv", ["rucio-mcp", "serve"]),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["sites"] == ["escape"]

    def test_http_transport_args_forwarded_to_serve(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch(
                "sys.argv",
                [
                    "rucio-mcp",
                    "serve",
                    "--transport",
                    "http",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "8001",
                    "--site",
                    "escape",
                    "--resource-url",
                    "http://localhost:8001",
                ],
            ),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["transport"] == "http"
        assert captured["host"] == "0.0.0.0"
        assert captured["port"] == 8001
        assert captured["sites"] == ["escape"]
        assert captured["resource_url"] == "http://localhost:8001"

    def test_auth_type_flag_forwarded_to_serve(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch("sys.argv", ["rucio-mcp", "serve", "--auth-type", "oidc"]),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["auth_type"] == "oidc"

    def test_auth_type_defaults_to_oidc(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch("sys.argv", ["rucio-mcp", "serve"]),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["auth_type"] == "oidc"

    def test_metrics_port_defaults_to_9001(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch("sys.argv", ["rucio-mcp", "serve"]),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["metrics_port"] == 9001

    def test_metrics_port_flag_forwarded_to_serve(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch(
                "sys.argv",
                ["rucio-mcp", "serve", "--metrics-port", "9090"],
            ),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["metrics_port"] == 9090

    def test_multiple_sites_for_http_mode(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch(
                "sys.argv",
                [
                    "rucio-mcp",
                    "serve",
                    "--transport",
                    "http",
                    "--site",
                    "escape",
                    "--site",
                    "atlas",
                    "--resource-url",
                    "http://localhost:8000",
                ],
            ),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["sites"] == ["escape", "atlas"]

    def test_forwarded_allow_ips_defaults_to_loopback(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch("sys.argv", ["rucio-mcp", "serve"]),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["forwarded_allow_ips"] == "127.0.0.1"

    def test_forwarded_allow_ips_flag_forwarded_to_serve(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch(
                "sys.argv",
                ["rucio-mcp", "serve", "--forwarded-allow-ips", "172.16.140.142"],
            ),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["forwarded_allow_ips"] == "172.16.140.142"

    def test_forwarded_allow_ips_wildcard_forwarded_to_serve(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch("sys.argv", ["rucio-mcp", "serve", "--forwarded-allow-ips", "*"]),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["forwarded_allow_ips"] == "*"

    def test_auth_type_rejects_invalid_value(self) -> None:
        """--auth-type must reject values not in the allowed choices."""
        with (
            patch("sys.argv", ["rucio-mcp", "serve", "--auth-type", "bad_value"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code != 0

    def test_atlas_x509_preset_removed(self) -> None:
        """atlas-x509 must not exist as a preset after the auth-type refactor."""
        assert "atlas-x509" not in PRESETS

    def test_cms_x509_preset_removed(self) -> None:
        """cms-x509 must not exist as a preset after the auth-type refactor."""
        assert "cms-x509" not in PRESETS


class TestCLIPing:
    def test_ping_dispatches(self) -> None:
        captured: dict[str, bool] = {}

        def fake_ping() -> None:
            captured["called"] = True

        with (
            patch("sys.argv", ["rucio-mcp", "ping"]),
            patch("rucio_mcp.cli.ping_server", fake_ping),
        ):
            main()

        assert captured.get("called") is True
