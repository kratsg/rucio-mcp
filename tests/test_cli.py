"""Tests for the CLI argument parsing."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

from rucio_mcp.cli import main


class TestCLIServe:
    def test_serve_calls_run(self) -> None:
        with (
            patch("rucio_mcp.server.Client"),
            patch("rucio_mcp.server.FastMCP") as mock_mcp_cls,
            patch("rucio_mcp.server._preflight_check"),
            patch("sys.argv", ["rucio-mcp", "serve"]),
        ):
            mock_mcp = MagicMock()
            mock_mcp_cls.return_value = mock_mcp
            # serve() calls mcp.run() — we just check it doesn't raise
            # and that FastMCP was constructed
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
                    "atlas",
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
        assert captured["site"] == "atlas"
        assert captured["resource_url"] == "http://localhost:8001"

    def test_audience_flag_repeatable(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch(
                "sys.argv",
                ["rucio-mcp", "serve", "--audience", "rucio", "--audience", "other"],
            ),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["audience"] == ["rucio", "other"]

    def test_required_scope_flag_repeatable(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch(
                "sys.argv",
                [
                    "rucio-mcp",
                    "serve",
                    "--required-scope",
                    "openid",
                    "--required-scope",
                    "profile",
                ],
            ),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["required_scope"] == ["openid", "profile"]


class TestCLIInit:
    def test_init_dispatches_with_preset(self) -> None:
        captured: dict[str, object] = {}

        def fake_init(
            preset: str | None, *, force: bool, prefix: Path | None, list_presets: bool
        ) -> int:
            captured.update(
                {
                    "preset": preset,
                    "force": force,
                    "prefix": prefix,
                    "list_presets": list_presets,
                }
            )
            return 0

        with (
            patch("sys.argv", ["rucio-mcp", "init", "atlas"]),
            patch("rucio_mcp.cli.init_command", fake_init),
        ):
            main()

        assert captured["preset"] == "atlas"
        assert captured["force"] is False
        assert captured["prefix"] is None
        assert captured["list_presets"] is False

    def test_init_force_flag(self) -> None:
        captured: dict[str, object] = {}

        def fake_init(
            preset: str | None, *, force: bool, prefix: Path | None, list_presets: bool
        ) -> int:
            captured.update(
                {
                    "preset": preset,
                    "force": force,
                    "prefix": prefix,
                    "list_presets": list_presets,
                }
            )
            return 0

        with (
            patch("sys.argv", ["rucio-mcp", "init", "atlas", "--force"]),
            patch("rucio_mcp.cli.init_command", fake_init),
        ):
            main()

        assert captured["force"] is True

    def test_init_list_flag(self) -> None:
        captured: dict[str, object] = {}

        def fake_init(
            preset: str | None, *, force: bool, prefix: Path | None, list_presets: bool
        ) -> int:
            captured.update(
                {
                    "preset": preset,
                    "force": force,
                    "prefix": prefix,
                    "list_presets": list_presets,
                }
            )
            return 0

        with (
            patch("sys.argv", ["rucio-mcp", "init", "--list"]),
            patch("rucio_mcp.cli.init_command", fake_init),
        ):
            main()

        assert captured["list_presets"] is True
        assert captured["preset"] is None

    def test_init_prefix_flag(self, tmp_path: Path) -> None:
        captured: dict[str, object] = {}

        def fake_init(
            preset: str | None, *, force: bool, prefix: Path | None, list_presets: bool
        ) -> int:
            captured.update(
                {
                    "preset": preset,
                    "force": force,
                    "prefix": prefix,
                    "list_presets": list_presets,
                }
            )
            return 0

        with (
            patch(
                "sys.argv", ["rucio-mcp", "init", "atlas", "--prefix", str(tmp_path)]
            ),
            patch("rucio_mcp.cli.init_command", fake_init),
        ):
            main()

        assert captured["prefix"] == tmp_path


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
