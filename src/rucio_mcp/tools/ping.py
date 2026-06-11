"""Tools for server connectivity and account identity."""

from __future__ import annotations

import base64
import datetime
import json as _json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import (
    build_hints,
    classify_error,
    format_dict,
    get_rucio_client,
)


def register(mcp: FastMCP, *, transport: str = "stdio") -> None:
    """Register ping and whoami tools with the MCP server."""

    @mcp.tool()
    async def rucio_ping(*, ctx: Context[Any, Any]) -> str:
        """Ping the Rucio server and return its version.

        Use this tool to verify that the Rucio server is reachable and to
        check which server version is running.
        """
        client = get_rucio_client(ctx)
        try:
            result = client.ping()
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        body = format_dict(result) if isinstance(result, dict) else str(result)
        hints = build_hints(["Use `rucio_whoami` to check your authenticated account"])
        return body + hints

    @mcp.tool()
    async def rucio_whoami(*, ctx: Context[Any, Any]) -> str:
        """Return information about the currently authenticated Rucio account.

        Shows account name, type, email, status, and creation date.
        Use this to confirm that authentication is working correctly.
        """
        client = get_rucio_client(ctx)
        try:
            result = client.whoami()
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [
                "Use `rucio_get_local_account_usage` to check your storage consumption",
                "Use `rucio_get_local_account_limits` to see your storage quotas",
            ]
        )
        return format_dict(result) + hints

    if transport == "http":

        @mcp.tool()
        async def rucio_token_info(*, ctx: Context[Any, Any]) -> str:
            """Show expiry and claims of the current OIDC session token.

            Decodes the Bearer token carried in this request to show when the
            session expires, who it was issued to, and by which issuer.
            Use this to check how long your session remains valid before the
            MCP client needs to re-authenticate.

            Only available in HTTP transport mode.
            """
            req = ctx.request_context.request
            auth: str = req.headers.get("authorization", "")
            if not auth.lower().startswith("bearer "):
                return "Error: no Bearer token found in the request headers."
            token = auth[7:].strip()

            parts = token.split(".")
            if len(parts) != 3:
                return (
                    "Token is opaque (not a JWT) — expiry cannot be decoded locally.\n"
                    "Use `rucio_whoami` to confirm the session is still active."
                )

            try:
                padded = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = _json.loads(base64.urlsafe_b64decode(padded))
            except Exception as exc:  # noqa: BLE001
                return f"Error: could not decode JWT payload: {exc}"

            now = datetime.datetime.now(tz=datetime.timezone.utc)
            lines: list[str] = []
            if "exp" in payload:
                exp_dt = datetime.datetime.fromtimestamp(
                    payload["exp"], tz=datetime.timezone.utc
                )
                remaining = exp_dt - now
                secs = int(remaining.total_seconds())
                if secs > 0:
                    mins, s = divmod(secs, 60)
                    lines.append(
                        f"- **expires_at:** {exp_dt.isoformat()} "
                        f"(in {mins}m {s:02d}s)"
                    )
                else:
                    lines.append(
                        f"- **expires_at:** {exp_dt.isoformat()} **(EXPIRED)**"
                    )
            if "iat" in payload:
                iat_dt = datetime.datetime.fromtimestamp(
                    payload["iat"], tz=datetime.timezone.utc
                )
                lines.append(f"- **issued_at:** {iat_dt.isoformat()}")
            if "sub" in payload:
                lines.append(f"- **subject:** {payload['sub']}")
            if "iss" in payload:
                lines.append(f"- **issuer:** {payload['iss']}")
            if "aud" in payload:
                lines.append(f"- **audience:** {payload['aud']}")

            if not lines:
                return (
                    "Token is a JWT but contains no standard claims (exp/iat/sub/iss).\n"
                    "Use `rucio_whoami` to confirm the session is still active."
                )

            hints = build_hints(["Use `rucio_whoami` to confirm account identity"])
            return "\n".join(lines) + hints
