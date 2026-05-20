# ATLAS IAM Client Registration

When an MCP client (Claude Desktop, VS Code, etc.) connects to an HTTP-mode
rucio-mcp server, it needs a `client_id` registered with ATLAS IAM
(`https://atlas-auth.cern.ch/`) so it can perform the PKCE authorization-code flow.

The MCP **server** itself does not hold a client_id — the `client_id` belongs to
the MCP **client** and is configured there.

---

## Option A: Admin-managed registration (recommended)

Submit a client registration request to the ATLAS IAM administrators. This is
the same path used for `atlas-rucio-webui`
(`client_id=63b7d8a4-87ef-4aa3-938b-222223c2dd9b`).

### What to provide

| Field | Value |
|---|---|
| `client_name` | `Rucio MCP — <your-deployment-name>` |
| `grant_types` | `authorization_code`, `refresh_token` |
| `response_types` | `code` |
| `token_endpoint_auth_method` | `none` (public client, PKCE only) |
| `redirect_uris` | See below |
| `scope` | `openid profile email` |

### Redirect URIs by MCP client

| MCP client | Redirect URI |
|---|---|
| Claude Desktop | `http://localhost:*/` (loopback, any port) |
| VS Code | `vscode://anthropic.claude/oauth/callback` |
| Custom / CLI | `http://localhost:<port>/callback` |

Contact: email `atlas-auth-support@cern.ch` or open a ticket in
[ATLAS JIRA](https://its.cern.ch/jira/projects/ATPHYSIT).

Reference example: the `atlas-rucio-webui` client uses
`redirect_uri=https://atlas-rucio-webui.cern.ch/api/auth/callback/atlas`.

---

## Option B: Dynamic Client Registration (DCR)

ATLAS IAM exposes a DCR endpoint at:

```
https://atlas-auth.cern.ch/iam/api/client-registration
```

You can attempt automatic registration, but note that ATLAS IAM typically
requires admin approval for new clients.

Example DCR request:

```bash
curl -X POST https://atlas-auth.cern.ch/iam/api/client-registration \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "My Rucio MCP client",
    "grant_types": ["authorization_code"],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
    "redirect_uris": ["http://localhost:8080/callback"],
    "scope": "openid profile email"
  }'
```

If the response is `201 Created`, use the returned `client_id` in your MCP
client configuration. If it is pending approval, follow up with the admins.

---

## Authorization request parameters

When requesting a token for use with rucio-mcp, the MCP client must include:

```
GET https://atlas-auth.cern.ch/authorize?
    client_id=<registered-client-id>
    &response_type=code
    &scope=openid profile email
    &audience=rucio
    &redirect_uri=<registered-redirect-uri>
    &code_challenge=<S256-challenge>
    &code_challenge_method=S256
```

The `audience=rucio` parameter (RFC 8707) is separate from `scope`.
The resulting JWT will have `"aud": "rucio"` which the rucio-mcp server validates.
