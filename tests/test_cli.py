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
        captured: dict[str, bool] = {}

        def fake_serve(read_only: bool = False) -> None:
            captured["read_only"] = read_only

        with (
            patch("sys.argv", ["rucio-mcp", "serve", "--read-only"]),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["read_only"] is True

    def test_default_is_not_read_only(self) -> None:
        captured: dict[str, bool] = {}

        def fake_serve(read_only: bool = False) -> None:
            captured["read_only"] = read_only

        with (
            patch("sys.argv", ["rucio-mcp", "serve"]),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["read_only"] is False


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
