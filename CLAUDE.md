# rucio-mcp — Contributor Guide

MCP server that exposes ATLAS Rucio data management operations as tools for
LLMs.

## Architecture

Two transport modes:

```
# stdio (local, single-user)
LLM <--MCP/stdio--> rucio-mcp serve <--HTTPS (rucio.client)--> Rucio server
                              |
                              +--subprocess--> voms-proxy-info

# http (hosted, multi-user)
MCP client  <--auth-code+PKCE-->  rucio-mcp (OAuth AS proxy)  <--polling-->  Rucio auth server  <--IdP-->
                                         |                                          |
                                  BridgeProvider mints                   /auth/oidc + /auth/oidc_redirect
                                  auth codes; bearer = rucio token       (Rucio session token)
```

**Stdio mode:** one `rucio.client.Client` built at server startup from env vars;
reused for all tool calls. All rucio auth types supported.

**HTTP mode:** rucio-mcp acts as an **OAuth 2.1 Authorization Server proxy**
(RFC 8414 + RFC 7591 DCR + auth-code+PKCE). It bridges MCP client auth to
Rucio's custom OIDC polling flow (`/auth/oidc` → `/auth/oidc_redirect`). The
resulting Rucio session token is returned verbatim as the MCP `access_token`. No
IAM registration is required by operators or end-users.

### HTTP mode auth flow

1. MCP client does DCR (`POST /register`) → gets a `client_id`
2. MCP client hits `/authorize` → `RucioBridgeProvider.authorize()` calls Rucio
   `/auth/oidc`, stores a `BridgeSession`, starts a background async polling
   task, and returns `302 /bridge?session=<id>`
3. User opens the rucio polling URL in their browser and logs in via their IdP
4. Background task polls `/auth/oidc_redirect`; when the Rucio session token
   arrives, the session is marked done and an MCP auth code is minted
5. JS in `/bridge` polls `/bridge/status`; when done, redirects to
   `redirect_uri?code=…&state=…`
6. MCP client exchanges the code at `/token` → gets
   `{access_token: <rucio token>}`
7. All subsequent MCP requests carry `Authorization: Bearer <rucio token>`;
   `BearerTokenClientFactory` injects it via `TokenInjectedClient`

### Client factory pattern

All tools obtain the rucio client via `get_rucio_client(ctx)` from
`tools/_helpers.py`, which reads
`ctx.request_context.lifespan_context["client_factory"]` and calls
`factory.get_client(ctx)`. This is the **canonical** way to get a client in a
tool — never access `lifespan_context["rucio_client"]` directly.

- **`EnvBasedClientFactory`** (stdio): wraps a single pre-built `Client`
- **`BearerTokenClientFactory`** (http): extracts bearer from `Authorization`
  header, builds `TokenInjectedClient`, caches by `mcp-session-id` with a fixed
  300 s TTL (rucio rejects stale tokens with 401)

### `TokenInjectedClient`

Subclass of `rucio.client.Client` that overrides the two name-mangled auth
hooks:

- `_BaseClient__authenticate`: injects the bearer into `self.auth_token` and
  `self.headers["X-Rucio-Auth-Token"]` without any auth-server round-trip
- `_BaseClient__get_token`: raises `CannotAuthenticate` on 401 (no silent
  re-auth)

### HTTP mode key components

- **`auth/rucio_cfg.py`** — reads `[client]` section from rucio.cfg; provides
  auth_type + OIDC config (auth_host, oidc_audience, oidc_scope, oidc_issuer,
  account); `auth_type` used by server to validate site supports HTTP mode
- **`auth/rucio_oidc_poller.py`** — async httpx wrapper for Rucio's two-step
  OIDC flow: `request_auth_url()` → polling URL; `poll_for_token()` → rucio
  session token (or asyncio.TimeoutError)
- **`auth/bridge_state.py`** — thread-safe `BridgeStateStore` with 5-min TTL;
  indexed by session_id and auth_code
- **`auth/bridge_provider.py`** — `BridgePoller` Protocol +
  `RucioBridgeProvider` implementing `OAuthAuthorizationServerProvider`;
  in-memory DCR client registry; delegates polling to any `BridgePoller` (today:
  `RucioOidcPoller`); passthrough `load_access_token` (no JWT validation — rucio
  rejects bad tokens with 401); state exposed via `provider.store` (public)
- **`auth/bridge_routes.py`** — `GET /bridge` (HTML interstitial + JS poller)
  and `GET /bridge/status` (JSON pending/done/error); registered via
  `mcp.custom_route()`; JS fetch uses a relative URL (`bridge/status`) so the
  page works correctly under any `/site/{name}/` mount prefix

### Preset extension

Available presets: `atlas` (x509 proxy, stdio only) and `escape` (OIDC, stdio
and HTTP). To add a new site: create `src/rucio_mcp/data/<site>.cfg` and add a
`Preset` entry to `src/rucio_mcp/presets.py`.

## Project layout

```
src/rucio_mcp/
├── cli.py          # argparse: `rucio-mcp serve [--transport {stdio,http}] [--site SITE] ...`
├── server.py       # FastMCP setup; _make_stdio_mcp / _make_site_mcp / _make_http_app; serve()
├── nomenclature.py # ATLAS dataset naming constants embedded in server instructions
├── resources.py    # MCP resources (static docs); register(mcp) wired in server.py
├── presets.py      # Preset dataclass; PRESETS dict (atlas, escape → *.cfg)
├── auth/
│   ├── factory.py            # RucioClientFactory ABC, EnvBasedClientFactory,
│   │                         # BearerTokenClientFactory, _extract_request_auth
│   ├── token_client.py       # TokenInjectedClient (bearer injection, no auth-server)
│   ├── session_cache.py      # SessionCache (thread-safe, fixed-TTL)
│   ├── rucio_cfg.py          # RucioCfg dataclass — reads [client] from rucio.cfg (incl. auth_type)
│   ├── rucio_oidc_poller.py  # RucioOidcPoller — async /auth/oidc + /auth/oidc_redirect
│   ├── bridge_state.py       # BridgeSession + BridgeStateStore (in-memory, 5-min TTL)
│   ├── bridge_provider.py    # BridgePoller Protocol + RucioBridgeProvider
│   └── bridge_routes.py      # GET /bridge (HTML) + GET /bridge/status (JSON)
├── data/
│   ├── atlas.cfg             # ATLAS rucio.cfg preset (x509_proxy, stdio only)
│   └── escape.cfg            # ESCAPE VRE rucio.cfg preset (oidc, stdio + HTTP)
└── tools/
    ├── _helpers.py  # parse_did(), format_dict(), format_list(), check_write_allowed(),
    │                # human_bytes(), paginate_iter(), build_hints(), classify_error(),
    │                # get_rucio_client()  ← use this in all tools
    ├── ping.py             # rucio_ping, rucio_whoami
    ├── dids.py             # rucio_list_dids, rucio_get_did, rucio_list_content,
    │                       # rucio_list_files, rucio_get_metadata, rucio_list_parent_dids
    ├── replicas.py         # rucio_list_replicas, rucio_list_dataset_replicas,
    │                       # rucio_list_container_replicas
    ├── scopes.py           # rucio_list_scopes, rucio_list_scopes_for_account
    ├── rses.py             # rucio_list_rses, rucio_list_rse_attributes, rucio_get_rse_usage,
    │                       # rucio_get_rse, rucio_get_rse_limits, rucio_get_rse_protocols,
    │                       # rucio_get_distance, rucio_list_transfer_limits
    ├── rules.py            # rucio_list_did_rules, rucio_list_replication_rules,
    │                       # rucio_get_replication_rule, rucio_list_rule_history,
    │                       # rucio_add_rule, rucio_delete_rule, rucio_update_rule,
    │                       # rucio_reduce_rule, rucio_move_rule, rucio_approve_rule,
    │                       # rucio_deny_rule
    ├── account.py          # rucio_get_local_account_usage, rucio_get_local_account_limits,
    │                       # rucio_list_accounts, rucio_get_account, rucio_list_account_rules
    ├── rucio_requests.py   # rucio_list_requests, rucio_list_requests_history
    ├── subscriptions.py    # rucio_list_subscriptions, rucio_list_subscription_rules
    ├── locks.py            # rucio_get_dataset_locks, rucio_get_dataset_locks_by_rse
    └── proxy.py            # rucio_voms_proxy_info (shells out to voms-proxy-info)
tests/
├── conftest.py               # mock_rucio_client, mock_ctx (EnvBasedClientFactory), mock_ctx_readonly
├── test_cli.py
├── test_server.py
├── test_helpers.py
├── test_http_transport.py    # HTTP mode: AS metadata, 401, bridge routes, serve() cfg check
├── test_resources.py
├── test_tools_ping.py
├── test_tools_dids.py
├── test_tools_replicas.py
├── test_tools_rules.py
├── test_tools_account.py
├── test_tools_requests.py
├── test_tools_subscriptions.py
├── test_tools_locks.py
├── test_tools_proxy.py
├── auth/
│   ├── test_factory.py          # EnvBasedClientFactory, BearerTokenClientFactory, _extract_request_auth
│   ├── test_rucio_cfg.py        # RucioCfg.from_path()
│   ├── test_rucio_oidc_poller.py # RucioOidcPoller (httpx mocks, no network)
│   ├── test_bridge_state.py     # BridgeStateStore TTL + state transitions
│   ├── test_bridge_provider.py  # RucioBridgeProvider (mocked poller)
│   ├── test_bridge_routes.py    # /bridge + /bridge/status (Starlette TestClient)
│   ├── test_session_cache.py    # SessionCache (TTL eviction, thread safety)
│   └── test_token_client.py     # TokenInjectedClient method overrides
└── integration/test_live.py  # requires live rucio access, run with --runslow
```

## Tool registration pattern

Each tool module exports a `register(mcp: FastMCP) -> None` function.
`server.py` imports the modules and calls `module.register(mcp)` for each. Tools
are defined as closures inside `register()` using the `@mcp.tool()` decorator.

```python
# tools/mymodule.py
from mcp.server.fastmcp import Context, FastMCP
from typing import Any

from rucio_mcp.tools._helpers import build_hints, classify_error, get_rucio_client


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def rucio_my_tool(
        param: str, limit: int = 50, offset: int = 0, *, ctx: Context[Any, Any]
    ) -> str:
        """Tool description — shown to the LLM as the tool's purpose."""
        client = get_rucio_client(ctx)  # works in both stdio and http transport
        try:
            result = client.some_method(param)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        hints = build_hints(["Use `rucio_other_tool` to do the next thing"])
        return str(result) + hints
```

Key conventions:

- Tool names are prefixed with `rucio_` to avoid collisions
- `ctx` is keyword-only (after `*`) so optional parameters can have defaults
  before it
- Errors are returned via `classify_error(exc)` from `_helpers.py` — never
  raised as exceptions, never bare `f"Error: {exc}"`
- `except Exception as exc:` lines carry `# noqa: BLE001` inline;
  `broad-exception-caught` is disabled globally in pylint (`pyproject.toml`)
- List tools accept `limit: int` and `offset: int` for pagination; use
  `paginate_iter(iterator, limit, offset)` from `_helpers.py`
- All tools append `build_hints([...])` from `_helpers.py` to guide the LLM on
  what to do next
- Byte values in output are humanized via `human_bytes()` from `_helpers.py`;
  pass `byte_keys=frozenset({...})` to `format_dict`/`format_list` to enable
- Write tools call `check_write_allowed(ctx.request_context.lifespan_context)`
  from `_helpers.py` and return its error string if non-None

Then wire it in `server.py`:

```python
from rucio_mcp.tools import mymodule

for _module in [..., mymodule]:
    _module.register(mcp)
```

## Build and test commands

```bash
pixi run test          # quick tests (no live rucio needed)
pixi run test-slow     # all tests including live integration (requires rucio auth)
pixi run lint          # pre-commit + pylint
pixi run build         # build sdist + wheel
pixi run build-check   # verify the built distributions with twine
```

## Development setup

```bash
pixi install           # install all dependencies
pixi run pre-commit-install  # install git hooks
```

## Adding a new tool

1. Decide which module it belongs to (or create a new one).
2. Add a new `@mcp.tool()` function inside the module's `register()`.
3. If creating a new module, add it to the loop in `server.py`.
4. Write unit tests using `mock_rucio_client` and `mock_ctx` from conftest.
5. Run `pixi run test` to verify.

## Rucio Python client reference

The unified `Client` class (`from rucio.client import Client`) inherits all
sub-clients. Key methods by category (source in `rucio/lib/rucio/client/`):

**DID discovery** (`didclient.py`):

- `client.list_dids(scope, filters, did_type, recursive)` → iterator of dicts
- `client.get_did(scope, name, dynamic)` → dict (stat)
- `client.list_content(scope, name)` → iterator of dicts
- `client.list_files(scope, name, long)` → iterator of dicts
- `client.get_metadata(scope, name, plugin)` → dict
- `client.list_parent_dids(scope, name)` → iterator of dicts
- `client.list_did_rules(scope, name)` → iterator of dicts (note: on didclient,
  not ruleclient)

**Replicas** (`replicaclient.py`):

- `client.list_replicas(dids, schemes, rse_expression, sort)` → iterator of
  dicts
  - `dids`: list of `{"scope": ..., "name": ...}` dicts
  - Each result has `pfns: {pfn_url: {"rse": ..., "type": ...}}`
- `client.list_dataset_replicas(scope, name, deep)` → iterator of dicts

**Rules** (`ruleclient.py`):

- `client.list_replication_rules(filters)` → iterator of dicts (global, filter
  by scope/account)
- `client.get_replication_rule(rule_id)` → dict
- `client.list_replication_rule_full_history(scope, name)` → iterator of dicts
- `client.add_replication_rule(dids, copies, rse_expression, ...)` → list of
  rule IDs
- `client.delete_replication_rule(rule_id, purge_replicas)` → bool
- `client.update_replication_rule(rule_id, options)` → bool
- `client.reduce_replication_rule(rule_id, copies, activity)` → str (new rule
  ID)
- `client.move_replication_rule(rule_id, rse_expression, activity)` → str (new
  rule ID)
- `client.approve_replication_rule(rule_id)` → bool
- `client.deny_replication_rule(rule_id)` → bool

**RSEs** (`rseclient.py`):

- `client.list_rses(rse_expression)` → iterator of `{"rse": name}` dicts
- `client.list_rse_attributes(rse)` → dict
- `client.get_rse_usage(rse)` → iterator of dicts
- `client.get_rse(rse)` → dict
- `client.get_rse_limits(rse)` → iterator of dicts
- `client.get_protocols(rse, protocol_domain, operation, default, scheme)` →
  dict/Any
- `client.get_distance(source, destination)` → list of dicts

**Requests / transfers** (`requestclient.py`):

- `client.list_requests(src_rse, dst_rse, request_states)` → iterator of dicts
- `client.list_requests_history(src_rse, dst_rse, request_states, offset, limit)`
  → iterator of dicts
- `client.list_transfer_limits()` → iterator of dicts

**Account** (`accountclient.py`):

- `client.whoami()` → dict
- `client.list_accounts(account_type, identity, filters)` → iterator of dicts
- `client.get_account(account)` → dict
- `client.get_local_account_usage(account, rse)` → iterator of dicts
- `client.get_account_limits(account, rse_expression, locality)` → dict
- `client.get_local_account_limits(account)` → dict

**Subscriptions** (`subscriptionclient.py`):

- `client.list_subscriptions(name, account)` → iterator of dicts
- `client.list_subscription_rules(account, name)` → iterator of dicts

**Locks** (`lockclient.py`):

- `client.get_dataset_locks(scope, name)` → iterator of dicts
- `client.get_dataset_locks_by_rse(rse)` → iterator of dicts

**Scopes** (`scopeclient.py`):

- `client.list_scopes()` → list of scope strings
- `client.list_scopes_for_account(account)` → list of scope strings

**Other**:

- `client.ping()` → dict (e.g. `{"version": "35.6.0"}`)

Authentication is configured via environment variables:

- `RUCIO_AUTH_TYPE`: `x509_proxy`, `userpass`, `oidc`, `x509`, `gss` (defaults
  to `x509_proxy`)
- `RUCIO_ACCOUNT`: your Rucio account name
- `RUCIO_CONFIG`: direct path to `rucio.cfg` (set automatically by
  `rucio-mcp init`)
- `X509_USER_PROXY`: path to proxy cert (defaults to `/tmp/x509up_u<uid>`)

## ATLAS dataset nomenclature

Full reference: ATL-COM-GEN-2007-003 "ATLAS Dataset Nomenclature" (2024
edition), available at https://cds.cern.ch/record/1070318

DIDs use the format `scope:name`. For centrally produced data, scope = project.

**Monte Carlo:**

```
project.datasetNumber.physicsShort.prodStep.dataType.AMITags
mc20_13TeV:mc20_13TeV.700320.Sh_2211_Zee_maxHTpTV2_BFilter.deriv.DAOD_PHYS.e8351_s3681_r13144_r13146_p5855
```

**Real data (primary):**

```
project.runNumber.streamName.prodStep.dataType.AMITags
data18_13TeV:data18_13TeV.00348885.physics_Main.deriv.DAOD_PHYS.r13286_p4910_p5855
```

**Real data (physics containers — preferred for analysis):**

```
project.periodName.streamName.PhysCont.dataType.contVersion
data15_13TeV:data15_13TeV.periodAllYear.physics_Main.PhysCont.DAOD_PHYSLITE.grp15_v01_p5631
```

AMI tag letters: `e`=evgen, `s`=simul, `d`=digit, `r`=reco(ProdSys),
`f`=reco(Tier0), `p`=group-production/deriv, `m`=merge(Tier0),
`t`=merge(ProdSys)

Common data types: `DAOD_PHYS`, `DAOD_PHYSLITE` (most common for analysis),
`DAOD_EXOT*`, `DAOD_SUSY*`, `AOD`, `ESD`, `EVNT`, `HITS`, `RDO`

DSID (MC dataset number) job options:
`https://gitlab.cern.ch/atlas-physics/pmg/mcjoboptions/-/tree/master/<700xxx>/<700320>`
where the directory is the first three digits + `xxx` and then the full DSID.

## Testing on the UChicago Analysis Facility

1. SSH to the facility and set up your environment:

   ```bash
   export RUCIO_ACCOUNT=<your_atlas_account>
   voms-proxy-init -voms atlas
   ```

2. Install rucio-mcp (once published) or install from source:

   ```bash
   pip install rucio-mcp
   # or from source:
   pip install -e .
   ```

3. Start the server with the required ATLAS environment variables:

   **With pixi** (`ca-policy-lcg` sets `X509_CERT_DIR` automatically):

   ```bash
   env RUCIO_AUTH_TYPE=x509_proxy \
       RUCIO_CONFIG=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/<version>/etc/rucio.cfg \
       rucio-mcp serve
   ```

   **Without pixi** (set `X509_CERT_DIR` to CVMFS CA bundle manually):

   ```bash
   env RUCIO_AUTH_TYPE=x509_proxy \
       X509_CERT_DIR=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/etc/grid-security-emi/certificates \
       RUCIO_CONFIG=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/<version>/etc/rucio.cfg \
       rucio-mcp serve
   ```

   - `RUCIO_CONFIG` — direct path to the site's `rucio.cfg` file inside the
     versioned rucio-clients installation on CVMFS.

4. Example Claude Code MCP config (`~/.claude.json` or project `.mcp.json`):

   **With pixi** (`X509_CERT_DIR` set automatically by `ca-policy-lcg`):

   ```json
   {
     "mcpServers": {
       "atlas": {
         "type": "stdio",
         "command": "pixi",
         "args": [
           "run",
           "--manifest-path",
           "/path/to/rucio-mcp",
           "rucio-mcp",
           "serve"
         ],
         "env": {
           "RUCIO_AUTH_TYPE": "x509_proxy",
           "RUCIO_ACCOUNT": "gstark",
           "RUCIO_CONFIG": "/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0/etc/rucio.cfg"
         }
       }
     }
   }
   ```

   **Without pixi** (set `X509_CERT_DIR` explicitly):

   ```json
   {
     "mcpServers": {
       "atlas": {
         "type": "stdio",
         "command": "rucio-mcp",
         "args": ["serve"],
         "env": {
           "RUCIO_AUTH_TYPE": "x509_proxy",
           "RUCIO_ACCOUNT": "gstark",
           "X509_CERT_DIR": "/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/etc/grid-security-emi/certificates",
           "RUCIO_CONFIG": "/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0/etc/rucio.cfg"
         }
       }
     }
   }
   ```

5. Run integration tests:

   ```bash
   pytest tests/integration/ --runslow -v
   ```

6. Useful `rucio` CLI commands for verifying the same operations manually:
   ```bash
   rucio ping
   rucio whoami
   rucio list-dids mc20_13TeV:mc20_13TeV.700320.*DAOD_PHYS* --short --filter type=container
   rucio stat mc20_13TeV:mc20_13TeV.700320.Sh_2211_Zee.deriv.DAOD_PHYS.e8351_p5855
   rucio list-dataset-replicas mc20_13TeV:mc20_13TeV.700320.Sh_2211_Zee.deriv.DAOD_PHYS.e8351_p5855
   ```
