"""Tests for the CLI argument parsing."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch


def _parse(args: list[str]) -> argparse.Namespace:
    """Run main() with sys.argv patched, capture the parsed args."""
    # We test the parser in isolation by importing and re-running parse_args.
    import sys

    from rucio_mcp.cli import main

    with patch("sys.argv", ["rucio-mcp", *args]), patch(
        "rucio_mcp.server.FastMCP"
    ) as mock_mcp_cls:
        mock_mcp = MagicMock()
        mock_mcp_cls.return_value = mock_mcp
        try:
            main()
        except SystemExit:
            pass
    return mock_mcp


class TestCLIServe:
    def test_serve_calls_run(self) -> None:
        with (
            patch("rucio_mcp.server.Client"),
            patch("rucio_mcp.server.FastMCP") as mock_mcp_cls,
        ):
            mock_mcp = MagicMock()
            mock_mcp_cls.return_value = mock_mcp
            import sys

            with patch("sys.argv", ["rucio-mcp", "serve"]):
                from rucio_mcp.cli import main

                # serve() calls mcp.run() — we just check it doesn't raise
                # and that FastMCP was constructed
                main()
            mock_mcp_cls.assert_called_once()

    def test_read_only_flag_passed_to_lifespan(self) -> None:
        """--read-only must end up as read_only=True in the lifespan context."""
        captured: dict = {}

        def fake_serve(read_only: bool = False) -> None:
            captured["read_only"] = read_only

        import sys

        with (
            patch("sys.argv", ["rucio-mcp", "serve", "--read-only"]),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            from rucio_mcp.cli import main

            main()

        assert captured["read_only"] is True

    def test_default_is_not_read_only(self) -> None:
        captured: dict = {}

        def fake_serve(read_only: bool = False) -> None:
            captured["read_only"] = read_only

        import sys

        with (
            patch("sys.argv", ["rucio-mcp", "serve"]),
            patch("rucio_mcp.cli.serve", fake_serve),
        ):
            from rucio_mcp.cli import main

            main()

        assert captured["read_only"] is False
