"""Tools for server connectivity and account identity."""

from __future__ import annotations

import base64
import datetime
import json as _json
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer  # noqa: TC002
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel

from rucio_mcp.tools._helpers import (
    build_hints,
    classify_error,
    error_result,
    format_dict,
    get_rucio_client,
)


class RucioPingResult(BaseModel):
    """Structured result of ``rucio_ping``."""

    version: str | None = None


class RucioWhoamiResult(BaseModel):
    """Structured result of ``rucio_whoami``."""

    account: str | None = None
    type: str | None = None
    email: str | None = None
    status: str | None = None
    created_at: str | None = None


class RucioTokenInfoResult(BaseModel):
    """Structured result of ``rucio_token_info``."""

    is_jwt: bool
    expires_at: str | None = None
    expired: bool | None = None
    issued_at: str | None = None
    subject: str | None = None
    issuer: str | None = None
    audience: Any | None = None


def register(mcp: MCPServer, *, transport: str = "stdio") -> None:
    """Register ping and whoami tools with the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Ping Rucio server", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_ping(
        *, ctx: Context[Any, Any]
    ) -> Annotated[CallToolResult, RucioPingResult]:
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
        version = result.get("version") if isinstance(result, dict) else None
        payload = RucioPingResult(version=version)
        return CallToolResult(
            content=[TextContent(type="text", text=body + hints)],
            structured_content=payload.model_dump(mode="json"),
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Show authenticated account", read_only_hint=True, open_world_hint=True
        )
    )
    async def rucio_whoami(
        *, ctx: Context[Any, Any]
    ) -> Annotated[CallToolResult, RucioWhoamiResult]:
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
        payload = RucioWhoamiResult(
            account=result.get("account"),
            type=result.get("type"),
            email=result.get("email"),
            status=result.get("status"),
            created_at=result.get("created_at"),
        )
        return CallToolResult(
            content=[TextContent(type="text", text=format_dict(result) + hints)],
            structured_content=payload.model_dump(mode="json"),
        )

    if transport == "http":

        @mcp.tool(
            annotations=ToolAnnotations(
                title="Show session token info", read_only_hint=True, open_world_hint=True
            )
        )
        async def rucio_token_info(
            *, ctx: Context[Any, Any]
        ) -> Annotated[CallToolResult, RucioTokenInfoResult]:
            """Show expiry and claims of the current OIDC session token.

            Decodes the Bearer token carried in this request to show when the
            session expires, who it was issued to, and by which issuer.
            Use this to check how long your session remains valid before the
            MCP client needs to re-authenticate.

            Only available in HTTP transport mode.
            """
            req = ctx.request_context.request
            if req is None:
                return error_result("Error: no request context available.")
            auth: str = req.headers.get("authorization", "")
            if not auth.lower().startswith("bearer "):
                return error_result(
                    "Error: no Bearer token found in the request headers."
                )
            token = auth[7:].strip()

            parts = token.split(".")
            if len(parts) != 3:
                text = (
                    "Token is opaque (not a JWT) — expiry cannot be decoded locally.\n"
                    "Use `rucio_whoami` to confirm the session is still active."
                )
                payload = RucioTokenInfoResult(is_jwt=False)
                return CallToolResult(
                    content=[TextContent(type="text", text=text)],
                    structured_content=payload.model_dump(mode="json"),
                )

            try:
                padded = parts[1] + "=" * (-len(parts[1]) % 4)
                jwt_payload = _json.loads(base64.urlsafe_b64decode(padded))
            except Exception as exc:  # noqa: BLE001
                return error_result(f"Error: could not decode JWT payload: {exc}")

            now = datetime.datetime.now(tz=datetime.timezone.utc)
            lines: list[str] = []
            expires_at: str | None = None
            expired: bool | None = None
            issued_at: str | None = None
            if "exp" in jwt_payload:
                exp_dt = datetime.datetime.fromtimestamp(
                    jwt_payload["exp"], tz=datetime.timezone.utc
                )
                expires_at = exp_dt.isoformat()
                remaining = exp_dt - now
                secs = int(remaining.total_seconds())
                if secs > 0:
                    mins, s = divmod(secs, 60)
                    expired = False
                    lines.append(f"- **expires_at:** {expires_at} (in {mins}m {s:02d}s)")
                else:
                    expired = True
                    lines.append(f"- **expires_at:** {expires_at} **(EXPIRED)**")
            if "iat" in jwt_payload:
                iat_dt = datetime.datetime.fromtimestamp(
                    jwt_payload["iat"], tz=datetime.timezone.utc
                )
                issued_at = iat_dt.isoformat()
                lines.append(f"- **issued_at:** {issued_at}")
            if "sub" in jwt_payload:
                lines.append(f"- **subject:** {jwt_payload['sub']}")
            if "iss" in jwt_payload:
                lines.append(f"- **issuer:** {jwt_payload['iss']}")
            if "aud" in jwt_payload:
                lines.append(f"- **audience:** {jwt_payload['aud']}")

            if not lines:
                text = (
                    "Token is a JWT but contains no standard claims (exp/iat/sub/iss).\n"
                    "Use `rucio_whoami` to confirm the session is still active."
                )
                payload = RucioTokenInfoResult(is_jwt=True)
                return CallToolResult(
                    content=[TextContent(type="text", text=text)],
                    structured_content=payload.model_dump(mode="json"),
                )

            hints = build_hints(["Use `rucio_whoami` to confirm account identity"])
            payload = RucioTokenInfoResult(
                is_jwt=True,
                expires_at=expires_at,
                expired=expired,
                issued_at=issued_at,
                subject=jwt_payload.get("sub"),
                issuer=jwt_payload.get("iss"),
                audience=jwt_payload.get("aud"),
            )
            return CallToolResult(
                content=[TextContent(type="text", text="\n".join(lines) + hints)],
                structured_content=payload.model_dump(mode="json"),
            )
