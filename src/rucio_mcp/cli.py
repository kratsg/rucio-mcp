"""Command-line interface for rucio-mcp."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

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
        "--metrics-port",
        type=int,
        default=9001,
        help="Port for the Prometheus /metrics endpoint (HTTP transport, default: 9001).",
    )
    serve_parser.add_argument(
        "--site",
        action="append",
        dest="sites",
        metavar="SITE",
        default=None,
        help=(
            "Site preset to use (e.g. atlas, cms, dune, escape). "
            "May be repeated for HTTP transport to mount multiple sites. "
            "Defaults to escape. Use --auth-type x509 for x509 proxy auth."
        ),
    )
    serve_parser.add_argument(
        "--auth-type",
        default="oidc",
        choices=("oidc", "x509", "x509_proxy", "userpass", "gss"),
        help=(
            "Override authentication method for stdio transport. "
            "Use 'x509' as a friendly alias for 'x509_proxy'. "
            "Ignored in HTTP mode (HTTP mode always uses OIDC via the OAuth bridge). "
            "Note: 'x509' is the rucio cert-based method; "
            "use 'x509_proxy' or the 'x509' alias for VOMS proxy auth."
        ),
    )
    serve_parser.add_argument(
        "--resource-url",
        default=os.environ.get("RUCIO_MCP_RESOURCE_URL"),
        help="Public URL of this MCP server. Required for HTTP transport.",
    )
    serve_parser.add_argument(
        "--shared-secret",
        default=os.environ.get("RUCIO_MCP_SHARED_SECRET"),
        help=(
            "Enable shared-secret HTTP mode: serve a single pre-authenticated "
            "rucio client (built from env, e.g. x509) behind a server-wide static "
            "bearer. HTTP requests must carry 'Authorization: Bearer <secret>'. "
            "Bypasses the OIDC OAuth bridge. Requires --transport http. "
            "Can also be set via RUCIO_MCP_SHARED_SECRET."
        ),
    )
    serve_parser.add_argument(
        "--rucio-cfg",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Path to a custom rucio.cfg. "
            "For HTTP transport with a single --site, applies to that site only."
        ),
    )
    serve_parser.add_argument(
        "--poll-timeout",
        type=float,
        default=180.0,
        metavar="SECONDS",
        help=(
            "Maximum seconds to wait for the user to complete OIDC login "
            "(HTTP transport only, default: 180)."
        ),
    )
    serve_parser.add_argument(
        "--forwarded-allow-ips",
        default="127.0.0.1",
        metavar="IPS",
        help=(
            "Comma-separated list of IP addresses (or '*' for all) whose "
            "X-Forwarded-For headers are trusted when running behind a reverse proxy "
            "(HTTP transport only, default: 127.0.0.1)."
        ),
    )
    serve_parser.add_argument(
        "--log-level",
        default="info",
        choices=("debug", "info", "warning", "error"),
        metavar="LEVEL",
        help="Logging verbosity (default: info). Use 'debug' to trace auth flow.",
    )

    subparsers.add_parser(
        "ping",
        help="Check connectivity to the Rucio server.",
    )

    args = parser.parse_args()

    if args.command == "serve":
        logging.basicConfig(
            level=getattr(logging, args.log_level.upper()),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        sites = args.sites or ["escape"]
        serve(
            read_only=args.read_only,
            transport=args.transport,
            host=args.host,
            port=args.port,
            metrics_port=args.metrics_port,
            sites=sites,
            resource_url=args.resource_url,
            shared_secret=args.shared_secret,
            rucio_cfg=args.rucio_cfg,
            auth_type=args.auth_type,
            poll_timeout=args.poll_timeout,
            forwarded_allow_ips=args.forwarded_allow_ips,
            log_level=args.log_level,
        )
    elif args.command == "ping":
        ping_server()
    else:
        parser.print_help()
        sys.exit(0)
