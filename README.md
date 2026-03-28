# rucio-mcp v0.2.0

[![Actions Status][actions-badge]][actions-link]
[![Documentation Status][rtd-badge]][rtd-link]

[![PyPI version][pypi-version]][pypi-link]
[![Conda-Forge][conda-badge]][conda-link]
[![PyPI platforms][pypi-platforms]][pypi-link]

[![GitHub Discussion][github-discussions-badge]][github-discussions-link]

[![Coverage][coverage-badge]][coverage-link]

<!-- --8<-- [start:intro] -->

An MCP server that exposes [Rucio](https://rucio.cern.ch) distributed data
management operations as tools for LLMs. Designed for ATLAS physicists working
with grid data on analysis facilities, but usable with any Rucio instance.

<!-- --8<-- [end:intro] -->

<!-- --8<-- [start:what-it-does] -->

## What it does

`rucio-mcp` lets Claude (or any MCP-compatible LLM) query and manage your Rucio
data directly:

- **Find data**: search for datasets/containers by pattern, list files, browse
  DID hierarchies
- **Check replicas**: see where data is physically stored, which sites have a
  dataset, generate access URLs
- **Manage rules**: list, create, update, move, approve, and delete replication
  rules
- **Monitor**: check RSE storage usage, account quotas, proxy certificate
  validity

All tool descriptions include ATLAS dataset naming conventions so the LLM
understands scope formats, AMI tags, and DID structure without extra prompting.

<!-- --8<-- [end:what-it-does] -->

<!-- --8<-- [start:installation] -->

## Installation

```bash
pip install rucio-mcp
```

Or with pixi (recommended for ATLAS facilities):

```bash
pixi add rucio-mcp
```

<!-- --8<-- [end:installation] -->

<!-- --8<-- [start:requirements] -->

## Requirements

- Python 3.10+
- A configured Rucio environment (`rucio.cfg` and valid authentication)
- For x509 proxy auth: a valid VOMS proxy (`voms-proxy-init -voms atlas`)
<!-- --8<-- [end:requirements] -->

<!-- --8<-- [start:quick-start] -->

## Quick start

### 1. Set up authentication

**x509 proxy (most common at ATLAS sites):**

```bash
voms-proxy-init -voms atlas
export RUCIO_ACCOUNT=<your_atlas_account>
export RUCIO_AUTH_TYPE=x509_proxy
export RUCIO_HOME=/path/to/rucio-clients   # directory containing etc/rucio.cfg
```

**When installed via pixi (recommended):**

`ca-policy-lcg` is included as a dependency and sets `X509_CERT_DIR`
automatically to the certificates bundled in the conda environment. No manual
configuration needed.

**On CVMFS-based facilities without pixi (e.g. UChicago Analysis Facility):**

```bash
voms-proxy-init -voms atlas
export RUCIO_ACCOUNT=<your_atlas_account>
export RUCIO_AUTH_TYPE=x509_proxy
export X509_CERT_DIR=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/etc/grid-security-emi/certificates
export RUCIO_HOME=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0
```

### 2. Test the server

```bash
rucio-mcp serve
```

The server speaks MCP over stdio. Configure your MCP client to launch it.

### 3. Configure Claude Code

Add to your `.mcp.json` (project) or `~/.claude.json` (global).

The name `atlas` lets you tell Claude "use the atlas rucio server" — useful when
you have multiple Rucio instances configured.

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
        "RUCIO_ACCOUNT": "youraccount",
        "RUCIO_HOME": "/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0"
      }
    }
  }
}
```

**Without pixi** (if you have CVMFS + ATLAS, use the path below; otherwise point
`X509_CERT_DIR` at your local CA bundle):

```json
{
  "mcpServers": {
    "atlas": {
      "type": "stdio",
      "command": "rucio-mcp",
      "args": ["serve"],
      "env": {
        "RUCIO_AUTH_TYPE": "x509_proxy",
        "RUCIO_ACCOUNT": "youraccount",
        "X509_CERT_DIR": "/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/etc/grid-security-emi/certificates",
        "RUCIO_HOME": "/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0"
      }
    }
  }
}
```

### 4. Configure Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%APPDATA%\Claude\claude_desktop_config.json` (Windows).

**With pixi:**

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
        "RUCIO_ACCOUNT": "youraccount",
        "RUCIO_HOME": "/path/to/rucio-clients"
      }
    }
  }
}
```

**Without pixi** (if you have CVMFS + ATLAS, use the path below; otherwise point
`X509_CERT_DIR` at your local CA bundle):

```json
{
  "mcpServers": {
    "atlas": {
      "type": "stdio",
      "command": "rucio-mcp",
      "args": ["serve"],
      "env": {
        "RUCIO_AUTH_TYPE": "x509_proxy",
        "RUCIO_ACCOUNT": "youraccount",
        "X509_CERT_DIR": "/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/etc/grid-security-emi/certificates",
        "RUCIO_HOME": "/path/to/rucio-clients"
      }
    }
  }
}
```

<!-- --8<-- [end:quick-start] -->

<!-- --8<-- [start:read-only] -->

## Read-only mode

Start the server with `--read-only` to block all write operations. Tools that
create, modify, or delete replication rules will return an error instead of
executing.

```bash
rucio-mcp serve --read-only
```

Or in your MCP config:

```json
{
  "mcpServers": {
    "atlas": {
      "command": "rucio-mcp",
      "args": ["serve", "--read-only"],
      "env": { "...": "..." }
    }
  }
}
```

Useful when you want the LLM to help explore data without the ability to
accidentally create rules or modify existing ones.

<!-- --8<-- [end:read-only] -->

<!-- --8<-- [start:tools] -->

## Available tools

### Connectivity

| Tool                    | Description                                   |
| ----------------------- | --------------------------------------------- |
| `rucio_ping`            | Check server connectivity and version         |
| `rucio_whoami`          | Show authenticated account info               |
| `rucio_voms_proxy_info` | Show VOMS proxy certificate status and expiry |

### DID discovery

| Tool                     | Description                                        |
| ------------------------ | -------------------------------------------------- |
| `rucio_list_dids`        | Search for datasets/containers by wildcard pattern |
| `rucio_stat`             | Get type, size, and timestamps for a DID           |
| `rucio_list_content`     | List immediate contents of a container or dataset  |
| `rucio_list_files`       | List all files within a DID                        |
| `rucio_get_metadata`     | Retrieve metadata key-value pairs for a DID        |
| `rucio_list_parent_dids` | Find containers that hold a given DID              |

### Replicas

| Tool                          | Description                                 |
| ----------------------------- | ------------------------------------------- |
| `rucio_list_file_replicas`    | Physical replica locations (PFNs) for files |
| `rucio_list_dataset_replicas` | Dataset availability summary across RSEs    |

### Replication rules

| Tool                           | Write? | Description                                     |
| ------------------------------ | ------ | ----------------------------------------------- |
| `rucio_list_rules`             | —      | List all rules for a DID                        |
| `rucio_list_replication_rules` | —      | List rules globally, filtered by scope/account  |
| `rucio_rule_info`              | —      | Detailed info for a specific rule               |
| `rucio_list_rule_history`      | —      | Full state history of rules for a DID           |
| `rucio_add_rule`               | ✓      | Create a new replication rule                   |
| `rucio_delete_rule`            | ✓      | Delete a rule (optionally purge replicas)       |
| `rucio_update_rule`            | ✓      | Update lifetime, locked flag, comment, activity |
| `rucio_reduce_rule`            | ✓      | Reduce the number of copies in a rule           |
| `rucio_move_rule`              | ✓      | Move a rule to a different RSE expression       |
| `rucio_approve_rule`           | ✓      | Approve a rule awaiting approval                |
| `rucio_deny_rule`              | ✓      | Deny a rule awaiting approval                   |

### RSEs and storage

| Tool                        | Description                             |
| --------------------------- | --------------------------------------- |
| `rucio_list_rses`           | List RSEs matching an expression        |
| `rucio_list_rse_attributes` | Key-value attributes for an RSE         |
| `rucio_list_rse_usage`      | Total, used, and free storage at an RSE |

### Account

| Tool                        | Description                         |
| --------------------------- | ----------------------------------- |
| `rucio_list_scopes`         | List all available scopes           |
| `rucio_list_account_usage`  | Storage used per RSE for an account |
| `rucio_list_account_limits` | Storage quota limits for an account |

<!-- --8<-- [end:tools] -->

<!-- --8<-- [start:example-prompts] -->

## Example prompts

Once configured, you can ask Claude things like:

- _"Find all DAOD_PHYS containers for mc20_13TeV DSID 700320"_
- _"Which sites have dataset X available and how complete is each replica?"_
- _"Create a rule to replicate this dataset to a US Tier-1 disk site for 30
  days"_
- _"Is my proxy still valid? How long do I have left?"_
- _"Show me the replication rules for this container and their current states"_
- _"What's my storage quota at CERN-PROD_DATADISK?"_
<!-- --8<-- [end:example-prompts] -->

<!-- prettier-ignore-start -->
[actions-badge]:            https://github.com/kratsg/rucio-mcp/actions/workflows/ci.yml/badge.svg
[actions-link]:             https://github.com/kratsg/rucio-mcp/actions
[conda-badge]:              https://img.shields.io/conda/vn/conda-forge/rucio-mcp
[conda-link]:               https://github.com/conda-forge/rucio-mcp-feedstock
[github-discussions-badge]: https://img.shields.io/static/v1?label=Discussions&message=Ask&color=blue&logo=github
[github-discussions-link]:  https://github.com/kratsg/rucio-mcp/discussions
[pypi-link]:                https://pypi.org/project/rucio-mcp/
[pypi-platforms]:           https://img.shields.io/pypi/pyversions/rucio-mcp
[pypi-version]:             https://img.shields.io/pypi/v/rucio-mcp
[rtd-badge]:                https://readthedocs.org/projects/rucio-mcp/badge/?version=latest
[rtd-link]:                 https://rucio-mcp.readthedocs.io/en/latest/?badge=latest
[coverage-badge]:           https://codecov.io/github/kratsg/rucio-mcp/branch/main/graph/badge.svg
[coverage-link]:            https://codecov.io/github/kratsg/rucio-mcp

<!-- prettier-ignore-end -->
