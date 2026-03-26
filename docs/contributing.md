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
`register(mcp: FastMCP) -> None` function. Tools are defined as closures
inside `register()` using the `@mcp.tool()` decorator.

```python
# tools/mymodule.py
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002


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
        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            result = client.some_method(param)
            return str(result)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"
```

Key conventions:

- Tool names are prefixed with `rucio_` to avoid collisions
- `ctx` is keyword-only (after `*`)
- Errors are returned as strings (`"Error: ..."`) — never raised as exceptions
- Write tools must check `check_write_allowed()` from `_helpers.py`

To wire a new module into the server, add it to the import and loop in
`server.py`:

```python
from rucio_mcp.tools import mymodule

for _module in [..., mymodule]:
    _module.register(mcp)
```

## Write-protected tools

Tools that modify Rucio state must check the `--read-only` flag before
executing:

```python
from rucio_mcp.tools._helpers import check_write_allowed

@mcp.tool()
async def rucio_my_write_tool(..., ctx: Context[Any, Any]) -> str:
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
    env RUCIO_AUTH_TYPE=x509_proxy \
        X509_CERT_DIR=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/etc/grid-security-emi/certificates \
        RUCIO_HOME=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0 \
        rucio-mcp serve
    ```

3. Run integration tests:

    ```bash
    pytest tests/integration/ --runslow -v
    ```
