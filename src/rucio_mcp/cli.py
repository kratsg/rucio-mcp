"""Command-line interface for rucio-mcp."""

from __future__ import annotations

import argparse
import os
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
        help="Start the MCP server",
    )
    serve_parser.add_argument(
        "--read-only",
        action="store_true",
        default=False,
        help="Disable all write operations (add/delete/update rules, etc.)",
    )
    serve_parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="Transport to use (default: stdio).",
    )
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to for HTTP transport (default: 127.0.0.1).",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to for HTTP transport (default: 8000).",
    )
    serve_parser.add_argument(
        "--site",
        default=os.environ.get("RUCIO_MCP_SITE", "atlas"),
        help="Site preset selecting the OAuth config (default: atlas).",
    )
    serve_parser.add_argument(
        "--resource-url",
        default=os.environ.get("RUCIO_MCP_RESOURCE_URL"),
        help="Public URL of this MCP server. Required for HTTP transport.",
    )
    serve_parser.add_argument(
        "--issuer-url",
        default=None,
        help="Override the OAuth issuer URL from the site config.",
    )
    serve_parser.add_argument(
        "--audience",
        action="append",
        default=None,
        metavar="AUD",
        help="Override accepted audience(s) (repeatable). Default: from site config.",
    )
    serve_parser.add_argument(
        "--required-scope",
        action="append",
        default=None,
        metavar="SCOPE",
        help="Override required scopes (repeatable). Default: from site config.",
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
        serve(
            read_only=args.read_only,
            transport=args.transport,
            host=args.host,
            port=args.port,
            site=args.site,
            resource_url=args.resource_url,
            issuer_url=args.issuer_url,
            audience=args.audience,
            required_scope=args.required_scope,
        )
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
