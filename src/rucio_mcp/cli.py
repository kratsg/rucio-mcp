"""Command-line interface for rucio-mcp."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rucio_mcp.init import init as init_command
from rucio_mcp.server import ping_server, serve


def main() -> None:
    """Entry point for the rucio-mcp command."""
    parser = argparse.ArgumentParser(
        prog="rucio-mcp",
        description="MCP Server for Rucio data management",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    serve_parser = subparsers.add_parser(
        "serve",
        help="Start the MCP server (stdio transport)",
    )
    serve_parser.add_argument(
        "--read-only",
        action="store_true",
        default=False,
        help="Disable all write operations (add/delete/update rules, etc.)",
    )

    init_parser = subparsers.add_parser(
        "init",
        help="Write a preset rucio.cfg to ~/.config/rucio-mcp/etc/rucio.cfg",
    )
    init_parser.add_argument(
        "preset",
        nargs="?",
        default=None,
        metavar="PRESET",
        help="Experiment preset to install (e.g. atlas). Use --list to see options.",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing rucio.cfg without prompting.",
    )
    init_parser.add_argument(
        "--prefix",
        type=Path,
        default=None,
        metavar="DIR",
        help="Write to DIR/etc/rucio.cfg instead of the default managed location.",
    )
    init_parser.add_argument(
        "--list",
        dest="list_presets",
        action="store_true",
        default=False,
        help="List available presets and exit.",
    )

    subparsers.add_parser(
        "ping",
        help="Check connectivity to the Rucio server.",
    )

    args = parser.parse_args()

    if args.command == "serve":
        serve(read_only=args.read_only)
    elif args.command == "init":
        rc = init_command(
            args.preset,
            force=args.force,
            prefix=args.prefix,
            list_presets=args.list_presets,
        )
        if rc != 0:
            sys.exit(rc)
    elif args.command == "ping":
        ping_server()
    else:
        parser.print_help()
