# Registering rucio-mcp as an ATLAS IAM Client

A **single registration** with ATLAS IAM is done by the deployment administrator
(e.g., UChicago SysAdmins for `rucio-mcp.af.uchicago.edu`). End users and their
MCP clients (Claude Code, Claude Desktop, VS Code, …) need no ATLAS IAM
registration at all.

---

## How the auth flow works

```
User's MCP client          rucio-mcp server             ATLAS IAM
(Claude Desktop, etc.)     (af.uchicago.edu)         (atlas-auth.cern.ch)

1. Connect to MCP server
   ─────────────────────►
2. MCP client gets redirected
   to server /authorize
   ─────────────────────►
3. Server redirects user's browser to ATLAS IAM
                           ─────────────────────────────►
4. User logs in (CERN SSO / ATLAS credentials)
                                                     ◄────────────────
5. ATLAS IAM sends code to server /oauth/callback
                           ◄─────────────────────────────
6. Server exchanges code for ATLAS IAM token
   (using its registered client_id + client_secret)
                           ─────────────────────────────►
                           ◄─────────────────────────────
7. Server returns ATLAS IAM token to MCP client
   ◄─────────────────────
8. All subsequent MCP calls include the token
   ─────────────────────►
9. Server validates token (JWKS) and forwards to Rucio
                           ──────────────────────────────► Rucio
```

The ATLAS IAM token (with `aud: rucio`) is used both as the MCP bearer token and
as the Rucio authentication token. No additional token exchange is needed.

---

## What to register

Submit a client registration request to ATLAS IAM. The same path was used for
`atlas-rucio-webui` — contact `atlas-auth-support@cern.ch` or open a ticket in
[ATLAS JIRA](https://its.cern.ch/jira/projects/ATPHYSIT).

| Field                        | Value                                                                 |
| ---------------------------- | --------------------------------------------------------------------- |
| `client_name`                | `Rucio MCP — <your-deployment-name>` (e.g. `Rucio MCP — UChicago AF`) |
| `client_type`                | `confidential`                                                        |
| `grant_types`                | `authorization_code`, `refresh_token`                                 |
| `response_types`             | `code`                                                                |
| `token_endpoint_auth_method` | `client_secret_basic`                                                 |
| `redirect_uris`              | `https://<your-server>/oauth/callback`                                |
| `scope`                      | `openid profile email`                                                |

Replace `<your-server>` with the public hostname (e.g.
`rucio-mcp.af.uchicago.edu`). For a local test deployment on port 8000 you would
use `http://localhost:8000/oauth/callback`.

The `audience=rucio` parameter is added by the server at authorization time as a
separate query parameter (INDIGO IAM RFC 8707 style); it does not appear in the
registered `scope`.

---

## What you receive from ATLAS IAM

After registration you receive:

- `client_id` — a UUID or string identifying the rucio-mcp deployment
- `client_secret` — the confidential secret; store it securely (env var, vault,
  k8s secret), never in source code or config files

Configure the server at startup:

```bash
rucio-mcp serve \
  --transport http \
  --site atlas \
  --resource-url https://rucio-mcp.af.uchicago.edu \
  --client-id <client_id> \
  --client-secret <client_secret>
```

Or via environment variables:

```bash
export RUCIO_MCP_CLIENT_ID=<client_id>
export RUCIO_MCP_CLIENT_SECRET=<client_secret>
rucio-mcp serve --transport http --site atlas \
  --resource-url https://rucio-mcp.af.uchicago.edu
```

---

## Verifying the registration

Once the server is running you can confirm the OAuth metadata is discoverable:

```bash
curl https://rucio-mcp.af.uchicago.edu/.well-known/oauth-authorization-server \
  | python -m json.tool
```

The MCP client will use this document to find the authorization endpoint
automatically — no manual configuration of ATLAS IAM URLs in Claude Desktop or
VS Code is needed.
