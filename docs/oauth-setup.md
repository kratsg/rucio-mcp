# OAuth Setup Guide

rucio-mcp supports two server modes:

- **stdio** (default): single-user, env-driven auth, all rucio auth types supported
- **http**: multi-user, OAuth 2.1 bridge, one hosted server for many users

---

## Stdio mode (local development)

Start exactly as before — no OAuth involved:

```bash
export RUCIO_ACCOUNT=<your-atlas-account>
voms-proxy-init -voms atlas
rucio-mcp init atlas        # one-time setup
rucio-mcp serve             # start the server
```

The Claude Desktop / VS Code MCP config uses `"type": "stdio"`. All rucio auth
types (`x509_proxy`, `userpass`, `oidc`, `gss`, …) are supported.

---

## HTTP mode (multi-user, OAuth 2.1 bridge)

HTTP mode exposes a single URL that multiple users can connect to. rucio-mcp
acts as an **OAuth 2.1 Authorization Server proxy**: it speaks standard
auth-code+PKCE+DCR to MCP clients while internally orchestrating Rucio's custom
`/auth/oidc` polling flow. The resulting Rucio session token is returned to the
MCP client as the bearer token.

**Neither operators nor end-users need to register with any IAM system.**
rucio-mcp reads OIDC configuration directly from your `rucio.cfg`.

### Prerequisites

1. A site rucio.cfg with OIDC settings (`auth_type = oidc`, `oidc_audience`,
   `oidc_scope`, `oidc_issuer`). The managed config installed by
   `rucio-mcp init` already has these for supported sites.
2. DNS and TLS for the public `--resource-url`.

### Start the server

```bash
rucio-mcp init atlas          # install managed rucio.cfg (one-time)

rucio-mcp serve \
  --transport http \
  --resource-url https://rucio-mcp.example.com \
  --host 0.0.0.0 \
  --port 8000
```

To use a different rucio.cfg (e.g. on the ESCAPE Rucio instance):

```bash
rucio-mcp serve \
  --transport http \
  --resource-url https://rucio-mcp.example.com \
  --rucio-cfg /path/to/escape-rucio.cfg \
  --host 0.0.0.0 \
  --port 8000
```

CLI flags for HTTP mode:

| Flag             | Env var                  | Default           | Description                                       |
| ---------------- | ------------------------ | ----------------- | ------------------------------------------------- |
| `--transport`    | —                        | `stdio`           | `stdio` or `http`                                 |
| `--resource-url` | `RUCIO_MCP_RESOURCE_URL` | —                 | Public URL of this MCP server (required for http) |
| `--rucio-cfg`    | —                        | managed rucio.cfg | Path to rucio.cfg with OIDC settings              |
| `--host`         | —                        | `127.0.0.1`       | Bind address                                      |
| `--port`         | —                        | `8000`            | Bind port                                         |
| `--read-only`    | —                        | false             | Disable write tools (add/delete/update rules)     |

### MCP client configuration

Add the server to Claude Desktop
(`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "rucio-atlas": {
      "type": "http",
      "url": "https://rucio-mcp.example.com"
    }
  }
}
```

On first use, the MCP client initiates the OAuth flow automatically. A browser
tab opens with a link to your experiment's IdP. After you log in, the Rucio
tools become available in the MCP session. No credentials are ever handled by
rucio-mcp itself — the login happens directly between your browser and the IdP.

### Verify the server is running

```bash
# Authorization Server metadata (RFC 8414)
curl https://rucio-mcp.example.com/.well-known/oauth-authorization-server \
  | python -m json.tool

# Protected Resource metadata (RFC 9728)
curl https://rucio-mcp.example.com/.well-known/oauth-protected-resource \
  | python -m json.tool

# Unauthenticated request → 401 + WWW-Authenticate header
curl -X POST https://rucio-mcp.example.com/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

### Account selection

The server determines your Rucio account using this priority:

1. `X-Rucio-Account` request header (explicit override)
2. `account` from the server's `rucio.cfg` `[client]` section

### How the bridge flow works

See [rucio-oauth-bridge.md](rucio-oauth-bridge.md) for the full sequence
diagram and architecture description.

### What the server does NOT do

- Does **not** require operator or end-user IAM registration
- Does **not** store long-lived refresh tokens (session TTL ≈ Rucio token lifetime)
- Does **not** grant Rucio access — Rucio enforces its own authorization
- Does **not** silently re-authenticate on 401 — MCP clients re-run the OAuth
  flow when the session token expires
