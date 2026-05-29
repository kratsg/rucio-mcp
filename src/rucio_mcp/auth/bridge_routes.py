"""Starlette route handlers for the OAuth bridge interstitial pages.

Two routes are registered on the FastMCP server:

GET /bridge?session=<sid>
    HTML page that shows a "Click here to log in" link pointing at the rucio
    IdP URL and runs a JS poller that redirects to redirect_uri once the
    background poll completes.

GET /bridge/status?session=<sid>
    JSON status endpoint polled by the JS above:
      {"status": "pending"}
      {"status": "done", "code": "...", "state": "...", "redirect_uri": "..."}
      {"status": "error", "message": "..."}
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from rucio_mcp.auth.bridge_provider import RucioBridgeProvider
    from rucio_mcp.auth.bridge_state import BridgeStateStore


def make_bridge_handlers(
    store: BridgeStateStore,
) -> tuple[Callable[..., object], Callable[..., object]]:
    """Return (bridge_page_handler, bridge_status_handler) closures over *store*."""

    async def bridge_page(request: Request) -> Response:
        session_id = request.query_params.get("session")
        if not session_id:
            return JSONResponse({"error": "missing session parameter"}, status_code=400)
        session = store.get_by_session_id(session_id)
        if session is None:
            return Response("Session not found or expired", status_code=404)
        html = _build_bridge_html(
            session_id=session_id, polling_url=session.polling_url
        )
        return HTMLResponse(html)

    async def bridge_status(request: Request) -> Response:
        session_id = request.query_params.get("session")
        if not session_id:
            return JSONResponse({"error": "missing session parameter"}, status_code=400)
        session = store.get_by_session_id(session_id)
        if session is None:
            return JSONResponse(
                {"status": "error", "message": "Session not found or expired"}
            )
        if session.status == "done":
            return JSONResponse(
                {
                    "status": "done",
                    "code": session.auth_code,
                    "state": session.state,
                    "redirect_uri": session.redirect_uri,
                }
            )
        if session.status == "error":
            return JSONResponse(
                {
                    "status": "error",
                    "message": session.error_message or "Authentication failed",
                }
            )
        return JSONResponse({"status": "pending"})

    return bridge_page, bridge_status


def register_bridge_routes(mcp: FastMCP, provider: RucioBridgeProvider) -> None:
    """Register /bridge and /bridge/status on *mcp* using the provider's session store."""
    bridge_page, bridge_status = make_bridge_handlers(provider._store)
    mcp.custom_route("/bridge", methods=["GET"])(bridge_page)
    mcp.custom_route("/bridge/status", methods=["GET"])(bridge_status)


def _build_bridge_html(*, session_id: str, polling_url: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Log in to Rucio</title>
  <style>
    body {{ font-family: sans-serif; max-width: 600px; margin: 4rem auto; padding: 0 1rem; }}
    a.btn {{ display: inline-block; padding: .6rem 1.2rem; background: #0070f3;
             color: #fff; border-radius: 4px; text-decoration: none; }}
    #status {{ margin-top: 2rem; color: #555; }}
  </style>
</head>
<body>
  <h1>Log in to Rucio</h1>
  <p>Click the button below to authenticate with your experiment credentials.</p>
  <a class="btn" href="{polling_url}" target="_blank">Open login page</a>
  <p id="status">Waiting for authentication&hellip;</p>
  <script>
    const SESSION = "{session_id}";
    async function poll() {{
      try {{
        const r = await fetch("/bridge/status?session=" + SESSION);
        const d = await r.json();
        if (d.status === "done") {{
          const url = new URL(d.redirect_uri);
          url.searchParams.set("code", d.code);
          if (d.state) url.searchParams.set("state", d.state);
          window.location.href = url.toString();
          return;
        }}
        if (d.status === "error") {{
          document.getElementById("status").textContent =
            "Authentication failed: " + (d.message || "unknown error") +
            ". You may close this tab.";
          return;
        }}
      }} catch (_) {{}}
      setTimeout(poll, 2000);
    }}
    poll();
  </script>
</body>
</html>"""
