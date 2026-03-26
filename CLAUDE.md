# rucio-mcp — Contributor Guide

MCP server that exposes ATLAS Rucio data management operations as tools for
LLMs.

## Architecture

```
LLM <--MCP/stdio--> rucio-mcp serve <--HTTPS (rucio.client)--> Rucio server
                              |
                              +--subprocess--> voms-proxy-info
```

The server uses the **rucio Python client library directly**
(`rucio.client.Client`), not the `rucio` CLI. Authentication (x509_proxy, OIDC,
userpass) is handled by the rucio client reading environment variables and
`rucio.cfg` automatically.

## Project layout

```
src/rucio_mcp/
├── cli.py          # argparse entry point: `rucio-mcp serve`
├── server.py       # FastMCP setup, lifespan (Client init), tool registration
├── nomenclature.py # ATLAS dataset naming constants embedded in tool descriptions
└── tools/
    ├── _helpers.py  # parse_did(), format_dict(), format_list()
    ├── ping.py      # rucio_ping, rucio_whoami
    ├── dids.py      # rucio_list_dids, rucio_stat, rucio_list_content,
    │                # rucio_list_files, rucio_get_metadata, rucio_list_parent_dids
    ├── replicas.py  # rucio_list_file_replicas, rucio_list_dataset_replicas
    ├── scopes.py    # rucio_list_scopes
    ├── rses.py      # rucio_list_rses, rucio_list_rse_attributes, rucio_list_rse_usage
    └── proxy.py     # rucio_voms_proxy_info (shells out to voms-proxy-info)
tests/
├── conftest.py               # mock_rucio_client, mock_ctx fixtures
├── test_tools_ping.py
├── test_tools_dids.py
├── test_tools_replicas.py
├── test_tools_proxy.py
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


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def rucio_my_tool(param: str, *, ctx: Context[Any, Any]) -> str:
        """Tool description — shown to the LLM as the tool's purpose."""
        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            result = client.some_method(param)
            return str(result)
        except Exception as exc:
            return f"Error: {exc}"
```

Key conventions:

- Tool names are prefixed with `rucio_` to avoid collisions
- `ctx` is keyword-only (after `*`) so optional parameters can have defaults
  before it
- Errors are returned as text strings (`"Error: ..."`) — never raised as
  exceptions
- `BLE001` (broad exception catch) is suppressed per-directory in
  `pyproject.toml`

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

**Replicas** (`replicaclient.py`):

- `client.list_replicas(dids, schemes, rse_expression, sort)` → iterator of
  dicts
  - `dids`: list of `{"scope": ..., "name": ...}` dicts
  - Each result has `pfns: {pfn_url: {"rse": ..., "type": ...}}`
- `client.list_dataset_replicas(scope, name, deep)` → iterator of dicts

**Rules** (`ruleclient.py`):

- `client.list_did_rules(scope, name)` → iterator of dicts
- `client.get_replication_rule(rule_id)` → dict

**RSEs** (`rseclient.py`):

- `client.list_rses(rse_expression)` → iterator of `{"rse": name}` dicts
- `client.list_rse_attributes(rse)` → dict
- `client.get_rse_usage(rse)` → iterator of dicts

**Account** (`accountclient.py`):

- `client.whoami()` → dict
- `client.get_local_account_usage(account, rse)` → iterator of dicts
- `client.get_account_limits(account, rse_expression, locality)` → dict

**Other**:

- `client.ping()` → dict (e.g. `{"version": "35.6.0"}`)
- `client.list_scopes()` → list of scope strings

Authentication is configured via environment variables:

- `RUCIO_AUTH_TYPE`: `x509_proxy`, `userpass`, `oidc`, `x509`, `gss`
- `RUCIO_ACCOUNT`: your Rucio account name
- `RUCIO_HOME`: directory containing `etc/rucio.cfg`
- `X509_USER_PROXY`: path to proxy cert (when `RUCIO_AUTH_TYPE=x509_proxy`)

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

   ```bash
   env RUCIO_AUTH_TYPE=x509_proxy \
       X509_CERT_DIR=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/etc/grid-security-emi/certificates \
       RUCIO_HOME=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/<version> \
       rucio-mcp serve
   ```

   - `RUCIO_AUTH_TYPE=x509_proxy` — standard for ATLAS x509 auth
   - `X509_CERT_DIR` — grid CA bundle from CVMFS; this path is stable across
     ATLAS sites
   - `RUCIO_HOME` — points to a versioned rucio-clients installation; set to
     whichever version is available (e.g. `35.6.0`). The rucio client reads
     `$RUCIO_HOME/etc/rucio.cfg` which contains `rucio_host`, `auth_host`, and
     proxy path settings.

4. Example Claude Code MCP config (`~/.claude.json` or project `.mcp.json`):

   ```json
   {
     "mcpServers": {
       "rucio-mcp": {
         "command": "rucio-mcp",
         "args": ["serve"],
         "env": {
           "RUCIO_AUTH_TYPE": "x509_proxy",
           "RUCIO_ACCOUNT": "gstark",
           "X509_CERT_DIR": "/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/etc/grid-security-emi/certificates",
           "RUCIO_HOME": "/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0"
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
