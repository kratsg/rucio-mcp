"""Command-line interface for rucio-mcp."""

from __future__ import annotations

import argparse

from rucio_mcp.server import serve


def main() -> None:
    """Entry point for the rucio-mcp command."""
    parser = argparse.ArgumentParser(
        prog="rucio-mcp",
        description="MCP Server for Rucio data management",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    subparsers.add_parser(
        "serve",
        help="Start the MCP server (stdio transport)",
    )

    args = parser.parse_args()

    if args.command == "serve":
        serve()
    else:
        parser.print_help()
