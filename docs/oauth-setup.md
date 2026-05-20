# OAuth Setup Guide

rucio-mcp supports two server modes:

- **stdio** (default): single-user, env-driven auth, all rucio auth types
  supported
- **http**: multi-user, OAuth 2.1 bearer token auth, one hosted server for many
  users

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

## HTTP mode (multi-user, Bearer token)

HTTP mode exposes a single URL that multiple users can connect to. The MCP
server acts as an **OAuth 2.1 Authorization Server proxy**: it is registered
once with the experiment's IdP (ATLAS IAM for ATLAS), handles the auth-code flow
on behalf of users, and forwards the resulting ATLAS IAM tokens to Rucio.

**End users need no registration.** Only the server deployment itself has a
`client_id` with ATLAS IAM.

### Prerequisites

1. The rucio-mcp deployment registered with ATLAS IAM — see
   [ATLAS IAM client registration](atlas-iam-client-registration.md). You
   receive a `client_id` and `client_secret` for the server.
2. DNS/TLS for the public URL (`--resource-url`).

### Start the server

```bash
rucio-mcp serve \
  --transport http \
  --site atlas \
  --resource-url https://rucio-mcp.example.com \
  --client-id <client_id> \
  --client-secret <client_secret> \
  --host 0.0.0.0 \
  --port 8000
```

CLI flags and their `RUCIO_MCP_*` env-var equivalents:

| Flag               | Env var                   | Default          | Description                                       |
| ------------------ | ------------------------- | ---------------- | ------------------------------------------------- |
| `--transport`      | —                         | `stdio`          | `stdio` or `http`                                 |
| `--site`           | `RUCIO_MCP_SITE`          | `atlas`          | Preset selecting the OAuth config                 |
| `--resource-url`   | `RUCIO_MCP_RESOURCE_URL`  | —                | Public URL of this MCP server (required for http) |
| `--client-id`      | `RUCIO_MCP_CLIENT_ID`     | —                | ATLAS IAM client_id for this server               |
| `--client-secret`  | `RUCIO_MCP_CLIENT_SECRET` | —                | ATLAS IAM client_secret for this server           |
| `--host`           | —                         | `127.0.0.1`      | Bind address                                      |
| `--port`           | —                         | `8000`           | Bind port                                         |
| `--issuer-url`     | —                         | from site config | Override the OAuth issuer URL                     |
| `--audience`       | —                         | from site config | Override accepted audience(s) (repeatable)        |
| `--required-scope` | —                         | from site config | Override required scopes (repeatable)             |

### MCP client configuration

Add the server to Claude Desktop
(`~/Library/Application\ Support/Claude/claude_desktop_config.json`):

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

On first use, your MCP client will open a browser tab. You will be redirected to
`atlas-auth.cern.ch` to log in with your ATLAS credentials. After consent, the
Rucio tools become available. No ATLAS IAM registration is needed on the user
side.

### Per-site OAuth metadata

The server publishes RFC 8414 Authorization Server Metadata at
`https://rucio-mcp.example.com/.well-known/oauth-authorization-server`. MCP
clients use this to discover the authorization endpoints automatically.

```bash
curl https://rucio-mcp.example.com/.well-known/oauth-authorization-server \
  | python -m json.tool
```

### Manual token testing

You can test with a pre-obtained ATLAS IAM token (e.g., via `oidc-token` or
`htgettoken`). The token must have `audience=rucio`:

```bash
TOKEN=$(oidc-token atlas --audience rucio)

curl -X POST https://rucio-mcp.example.com/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

Or with `htgettoken`:

```bash
htgettoken -a atlas --audience rucio -o /tmp/token.txt
TOKEN=$(cat /tmp/token.txt)
```

### Account selection

The server determines your Rucio account from the JWT using this priority:

1. `X-Rucio-Account` request header (explicit override)
2. JWT `preferred_username` claim
3. JWT `sub` claim

Set a custom account:

```bash
curl -X POST https://rucio-mcp.example.com/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Rucio-Account: my-atlas-account" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"rucio_whoami","arguments":{}},"id":2}'
```

### What the server does NOT do

- Does **not** require end-users or MCP clients to register with ATLAS IAM
- Does **not** store refresh tokens beyond the current session
- Does **not** grant access — Rucio enforces its own authorization
- Does **not** re-authenticate on 401 — clients must re-acquire tokens when they
  expire
