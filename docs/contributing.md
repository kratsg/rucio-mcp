---
icon: lucide/code
---

# Contributing

## Architecture

```
LLM <--MCP/stdio--> rucio-mcp serve <--HTTPS (rucio.client)--> Rucio server
                              |
                              +--subprocess--> voms-proxy-info
```

The server uses the **rucio Python client library directly**
(`rucio.client.Client`). Each MCP tool calls client methods and returns
formatted text. Authentication is handled by the Rucio client reading
environment variables and `rucio.cfg` automatically.

## Development setup

```bash
git clone https://github.com/kratsg/rucio-mcp
cd rucio-mcp
pixi install
pixi run pre-commit-install
```

## Build and test commands

```bash
pixi run test          # quick tests (no live Rucio needed)
pixi run test-slow     # all tests including live integration
pixi run lint          # pre-commit + pylint
pixi run build         # build sdist + wheel
pixi run docs-serve    # build and serve docs locally
```

## Tool registration pattern

Each tool module lives in `src/rucio_mcp/tools/` and exports a single
`register(mcp: FastMCP) -> None` function. Tools are defined as closures inside
`register()` using the `@mcp.tool()` decorator.

```python
# tools/mymodule.py
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import build_hints, classify_error, get_rucio_client


def register(mcp: FastMCP) -> None:
    """Register my tools with the MCP server."""

    @mcp.tool()
    async def rucio_my_tool(param: str, *, ctx: Context[Any, Any]) -> str:
        """One-line summary shown to the LLM as the tool purpose.

        Longer description. Explain what Rucio operation this wraps and
        what the output looks like.

        Args:
            param: Description of the parameter.
        """
        client = get_rucio_client(ctx)
        try:
            result = client.some_method(param)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)
        hints = build_hints(["Use `rucio_other_tool` to do the next thing"])
        return str(result) + hints
```

Key conventions:

- Tool names are prefixed with `rucio_` to avoid collisions
- `ctx` is keyword-only (after `*`)
- Get the client via `get_rucio_client(ctx)` — never access `lifespan_context`
  directly
- Errors are returned via `classify_error(exc)` — never raised, never bare
  `f"Error: {exc}"`
- Append `build_hints([...])` to guide the LLM on next steps
- Use `format_dict` / `format_list` / `paginate_iter` from `_helpers.py` for
  output formatting
- Write tools must check `check_write_allowed()` from `_helpers.py`

To wire a new module into the server, add it to the import and loop in
`server.py`:

```python
from rucio_mcp.tools import mymodule

for _module in [..., mymodule]:
    _module.register(mcp)
```

## Contributing a new site

A "site" is a bundled `rucio.cfg` preset plus a `Preset` entry that the CLI
knows about. Adding one requires a cfg file, a preset entry, a bundled-cfg test,
and docs updates.

### 1. Add `src/rucio_mcp/data/<site>.cfg`

The file must have a `[client]` section. Required keys:

```ini
[client]
rucio_host = https://<site>-rucio.example.org
auth_host  = https://<site>-rucio-auth.example.org
auth_type  = oidc
```

Use `auth_type = oidc` so the site works in both stdio and HTTP mode. x509 proxy
auth is selected at runtime with `--auth-type x509` — no separate cfg is needed.

Common optional OIDC keys (include only what the site requires):

```ini
oidc_polling  = true
oidc_issuer   = <issuer-label>
oidc_audience = rucio
oidc_scope    = openid profile offline_access
```

### 2. Add a `Preset` entry in `src/rucio_mcp/presets.py`

```python
PRESETS["mysite"] = Preset(
    name="mysite",
    description="My Site (OIDC — stdio and HTTP mode)",
    config_resource="mysite.cfg",
    post_init_hint=textwrap.dedent("""\
        Next steps:
          export RUCIO_ACCOUNT=<your-mysite-account>

        For stdio mode (OIDC polling):
          rucio-mcp serve --site mysite

        For stdio mode (x509 proxy):
          voms-proxy-init -voms mysite
          rucio-mcp serve --site mysite --auth-type x509

        For HTTP mode (OAuth bridge):
          rucio-mcp serve --transport http \\
                          --resource-url http://localhost:8000 \\
                          --site mysite
    """).rstrip(),
)
```

Leave `nomenclature_resource=None` (the default) unless you add a nomenclature
file (see step 3).

### 3. (Optional) Add site nomenclature

If the site has dataset naming conventions worth documenting, add a markdown
file at `src/rucio_mcp/data/nomenclature/<site>.md` and set
`nomenclature_resource="nomenclature/mysite.md"` in the `Preset` entry.

The file is automatically exposed as the `rucio://nomenclature` MCP resource and
referenced in the server instructions. To also publish it as a docs page, create
`docs/<site>-nomenclature.md` with a snippet include:

```markdown
---
icon: lucide/book-open
---

--8<-- "src/rucio_mcp/data/nomenclature/mysite.md"
```

### 4. Add a bundled-cfg test

In `tests/auth/test_rucio_cfg.py`, add a test inside `TestRucioCfg`:

```python
def test_load_bundled_mysite_cfg(self) -> None:
    p = Path(str(_pkg_files("rucio_mcp.data").joinpath("mysite.cfg")))
    cfg = RucioCfg.from_path(p)
    assert cfg.auth_type == "oidc"
    assert cfg.rucio_host == "https://<site>-rucio.example.org"
```

### 5. Update docs

Add the new site to:

- `docs/configuration.md` — auth-method tabs and preset snippet tabs
- `README.md` — quick-start usage block
- `docs/oauth-setup.md` — HTTP mode section (if the site supports it)

Then verify everything passes:

```bash
pixi run test
pixi run lint
pixi run build && pixi run build-check   # confirms the .cfg ships in the wheel
```

## Write-protected tools

Tools that modify Rucio state must check the `--read-only` flag before
executing:

```python
from rucio_mcp.tools._helpers import check_write_allowed


@mcp.tool()
async def rucio_my_write_tool(*args, ctx: Context[Any, Any]) -> str:
    """..."""
    if err := check_write_allowed(ctx.request_context.lifespan_context):
        return err
    # ... proceed with write operation
```

## Tests

All tools have unit tests using mocked fixtures from `tests/conftest.py`:

- `mock_rucio_client` — a `MagicMock` pre-configured with typical return values
- `mock_ctx` — an async context with `rucio_client` and `read_only=False`
- `mock_ctx_readonly` — same but with `read_only=True`

```python
# tests/test_tools_mymodule.py
import pytest
from rucio_mcp.tools.mymodule import register


@pytest.fixture
def registered_tools(mock_ctx):
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test")
    register(mcp)
    return {t.name: t.fn for t in mcp._tool_manager.list_tools()}


class TestRucioMyTool:
    async def test_basic(self, registered_tools, mock_ctx, mock_rucio_client):
        mock_rucio_client.some_method.return_value = "result"
        result = await registered_tools["rucio_my_tool"]("param", ctx=mock_ctx)
        assert result == "result"
```

## Testing on the UChicago Analysis Facility

1. SSH to the facility and initialise your proxy:

   ```bash
   export RUCIO_ACCOUNT=<your_atlas_account>
   voms-proxy-init -voms atlas
   ```

2. Start the server with the standard ATLAS environment:

   ```bash
   X509_CERT_DIR=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/etc/grid-security-emi/certificates \
       RUCIO_CONFIG=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0/etc/rucio.cfg \
       rucio-mcp serve --site atlas --auth-type x509
   ```

3. Run integration tests:

   ```bash
   pytest tests/integration/ --runslow -v
   ```
