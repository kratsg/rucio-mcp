# OAuth Setup Guide

rucio-mcp supports two server modes:

- **stdio** (default): single-user, env-driven auth, all rucio auth types
  supported
- **http**: multi-user, OAuth 2.1 bridge, one hosted server for many users

---

## Stdio mode (local development)

Start without any prior setup step — `--site` resolves directly to a bundled
preset:

```bash
export RUCIO_ACCOUNT=<your-escape-account>
rucio-mcp serve --site escape       # escape is the default
```

To use ATLAS OIDC or x509 proxy:

```bash
rucio-mcp serve --site atlas        # OIDC polling
# or
export RUCIO_ACCOUNT=<your-atlas-account>
voms-proxy-init -voms atlas
rucio-mcp serve --site atlas-x509   # x509 proxy
```

To point at a custom rucio.cfg instead of the bundled preset:

```bash
rucio-mcp serve --rucio-cfg /path/to/rucio.cfg
```

The `--auth-type` flag overrides whatever `auth_type` is in the cfg:

```bash
rucio-mcp serve --rucio-cfg /path/to/rucio.cfg --auth-type oidc
```

The Claude Desktop / VS Code MCP config uses `"type": "stdio"`. All rucio auth
types (`x509_proxy`, `userpass`, `oidc`, `gss`, …) are supported.

---

## HTTP mode (multi-user, OAuth 2.1 bridge)

HTTP mode exposes one URL per site that multiple users can connect to. rucio-mcp
acts as an **OAuth 2.1 Authorization Server proxy**: it speaks standard
auth-code+PKCE+DCR to MCP clients while internally orchestrating Rucio's custom
`/auth/oidc` polling flow. The resulting Rucio session token is returned to the
MCP client as the bearer token.

**Neither operators nor end-users need to register with any IAM system.**
rucio-mcp reads OIDC configuration directly from your `rucio.cfg`.

**HTTP mode requires `auth_type = oidc` in the site's rucio.cfg.** See
`src/rucio_mcp/data/` for the bundled site configurations and which ones support
HTTP mode.

### Prerequisites

1. A site rucio.cfg with OIDC settings (`auth_type = oidc`, `oidc_audience`,
   `oidc_scope`, `oidc_issuer`).
2. DNS and TLS for the public `--resource-url`.

### Start the server (single site)

```bash
rucio-mcp serve \
  --transport http \
  --site escape \
  --resource-url https://rucio-mcp.example.com \
  --host 0.0.0.0 \
  --port 8000
```

To use a custom rucio.cfg for a single site:

```bash
rucio-mcp serve \
  --transport http \
  --site escape \
  --rucio-cfg /path/to/escape-rucio.cfg \
  --resource-url https://rucio-mcp.example.com \
  --host 0.0.0.0 \
  --port 8000
```

### Start the server (multiple sites)

Repeat `--site` to mount several sites under `/site/{name}/`:

```bash
rucio-mcp serve \
  --transport http \
  --site escape \
  --site another-oidc-site \
  --resource-url https://rucio-mcp.example.com \
  --host 0.0.0.0 \
  --port 8000
```

Each site is mounted at `{resource-url}/site/{name}/` (trailing slash is
canonical) and has its own independent OAuth metadata, DCR registry, and bridge
state.

CLI flags:

| Flag             | Env var                  | Default     | Description                                        |
| ---------------- | ------------------------ | ----------- | -------------------------------------------------- |
| `--transport`    | —                        | `stdio`     | `stdio` or `http`                                  |
| `--site`         | —                        | `escape`    | Site preset name (repeatable for HTTP multi-site)  |
| `--resource-url` | `RUCIO_MCP_RESOURCE_URL` | —           | Public URL of this MCP server (required for http)  |
| `--rucio-cfg`    | —                        | preset cfg  | Override rucio.cfg (single site only in http mode) |
| `--auth-type`    | —                        | from cfg    | Override RUCIO_AUTH_TYPE (stdio mode only)         |
| `--host`         | —                        | `127.0.0.1` | Bind address                                       |
| `--port`         | —                        | `8000`      | Bind port                                          |
| `--metrics-port` | —                        | `9001`      | Port for the Prometheus `/metrics` endpoint (http) |
| `--poll-timeout` | —                        | `180`       | Seconds to wait for OIDC login to complete (http)  |
| `--read-only`    | —                        | false       | Disable write tools (add/delete/update rules)      |

### MCP client configuration

Add the server to Claude Desktop
(`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "rucio-escape": {
      "type": "http",
      "url": "https://rucio-mcp.example.com/site/escape/"
    }
  }
}
```

Note the `/site/{name}/` suffix — each site has its own OAuth metadata endpoint
at `{url}.well-known/oauth-authorization-server`.

On first use, the MCP client initiates the OAuth flow automatically. A browser
tab opens with a link to your experiment's IdP. After you log in, the Rucio
tools become available in the MCP session. No credentials are ever handled by
rucio-mcp itself — the login happens directly between your browser and the IdP.

### Verify the server is running

```bash
# Authorization Server metadata for the escape site (RFC 8414)
curl https://rucio-mcp.example.com/site/escape/.well-known/oauth-authorization-server \
  | python -m json.tool

# Unauthenticated request → 401 + WWW-Authenticate header (trailing slash is canonical)
curl -X POST https://rucio-mcp.example.com/site/escape/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

### How the bridge flow works

See [rucio-oauth-bridge.md](rucio-oauth-bridge.md) for the full sequence diagram
and architecture description.

### Monitoring

Prometheus metrics are served on a **dedicated port** (default `:9001`) that is
separate from the MCP endpoint — scrapers never mix with MCP client traffic:

```bash
curl http://localhost:9001/metrics
```

To use a different port, pass `--metrics-port` when starting the server:

```bash
rucio-mcp serve \
  --transport http \
  --site escape \
  --resource-url https://rucio-mcp.example.com \
  --port 8000 \
  --metrics-port 9001
```

Standard Starlette HTTP counters are exported for every matched route:

| Metric                                       | Type      | Description                                      |
| -------------------------------------------- | --------- | ------------------------------------------------ |
| `starlette_requests_total`                   | counter   | Total requests by method and path template       |
| `starlette_responses_total`                  | counter   | Total responses by method, path, and status code |
| `starlette_requests_processing_time_seconds` | histogram | Request latency by method and path               |
| `starlette_exceptions_total`                 | counter   | Unhandled exceptions by type                     |
| `starlette_requests_in_progress`             | gauge     | Requests currently being processed               |

rucio-mcp adds per-tool call metrics and live bridge/cache gauges:

| Metric                                 | Labels           | Description                                                |
| -------------------------------------- | ---------------- | ---------------------------------------------------------- |
| `rucio_mcp_tool_calls_total`           | `site`, `tool`   | Total MCP tool invocations                                 |
| `rucio_mcp_tool_call_duration_seconds` | `site`, `tool`   | Tool execution time histogram                              |
| `rucio_mcp_bridge_sessions`            | `site`, `status` | In-flight OAuth bridge sessions (`pending`/`done`/`error`) |
| `rucio_mcp_cached_clients`             | `site`           | Cached Rucio client instances (one per active MCP session) |

Requests to paths that do not match any registered route are not tracked, so
probe traffic from scanners does not cause unbounded label cardinality.

### What the server does NOT do

- Does **not** require operator or end-user IAM registration
- Does **not** store long-lived refresh tokens (session TTL ≈ Rucio token
  lifetime)
- Does **not** grant Rucio access — Rucio enforces its own authorization
- Does **not** silently re-authenticate on 401 — MCP clients re-run the OAuth
  flow when the session token expires
