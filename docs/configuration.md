---
icon: lucide/settings
---

# Configuration

## Quick setup

Select a bundled site preset with `--site`. The server resolves directly to the
bundled `rucio.cfg` — no prior setup step required.

```bash
export RUCIO_ACCOUNT=<your-escape-account>
rucio-mcp serve --site escape       # escape is the default
```

Available presets: `escape` (OIDC, default), `atlas` (OIDC), `cms` (OIDC),
`dune` (OIDC). All presets use OIDC by default; pass `--auth-type x509` to
switch to x509 proxy auth at runtime without a separate preset.

!!! tip "Site-managed Rucio clients (UChicago AF, CERN lxplus, CVMFS)" If your
site already provides a Rucio client installation, point `--rucio-cfg` at the
site's `rucio.cfg` directly — no preset needed. See
[Site-managed deployments](#site-managed-deployments) below.

## Environment variables

All authentication configuration is passed via environment variables, which are
read by both the `rucio-mcp` preflight check and the underlying Rucio client.

| Variable          | Required | Description                                                                                              |
| ----------------- | -------- | -------------------------------------------------------------------------------------------------------- |
| `RUCIO_CONFIG`    | No       | Direct path to a `rucio.cfg` file. Set automatically from `--site` or `--rucio-cfg`.                     |
| `RUCIO_AUTH_TYPE` | No       | Authentication method: `x509_proxy`, `userpass`, `oidc`, `x509`. Defaults to the value in `rucio.cfg`.   |
| `RUCIO_ACCOUNT`   | Yes      | Your Rucio account name                                                                                  |
| `X509_USER_PROXY` | x509     | Path to your VOMS proxy certificate. Defaults to `/tmp/x509up_u<uid>`.                                   |
| `X509_CERT_DIR`   | x509     | Directory of CA certificates for SSL verification. Set automatically by `ca-policy-lcg` when using pixi. |

## Authentication methods

=== "x509 proxy"

    Use `--auth-type x509` with any site preset. One preset covers both OIDC and
    x509 proxy — no separate `-x509` preset is needed.

    **ATLAS with pixi (recommended):** `ca-policy-lcg` is a bundled dependency
    and sets `X509_CERT_DIR` automatically to the certificates inside the conda
    environment (`$CONDA_PREFIX/etc/grid-security/certificates/`). You only
    need:

    ```bash
    export RUCIO_ACCOUNT=<your_atlas_account>
    pixi exec --with rucio-mcp voms-proxy-init -voms atlas
    rucio-mcp serve --site atlas --auth-type x509
    ```

    **ATLAS — on CVMFS-based facilities (UChicago AF, CERN lxplus, etc.):**

    ```bash
    export RUCIO_ACCOUNT=<your_atlas_account>
    export X509_CERT_DIR=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/etc/grid-security-emi/certificates
    export RUCIO_CONFIG=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0/etc/rucio.cfg
    voms-proxy-init -voms atlas
    rucio-mcp serve --site atlas --auth-type x509
    ```

    **CMS:**

    ```bash
    export RUCIO_ACCOUNT=<your_cms_account>
    voms-proxy-init -voms cms
    rucio-mcp serve --site cms --auth-type x509
    ```

    If `X509_CERT_DIR` is not set automatically, point it at a local CA bundle
    (e.g. from `ca-policy-lcg` or your system package manager):

    ```bash
    export X509_CERT_DIR=/etc/grid-security/certificates
    ```

    !!! note "x509 vs x509_proxy"
        `--auth-type x509` is a friendly alias for `x509_proxy` (VOMS proxy
        auth). The underlying rucio value used is `x509_proxy`. To use rucio's
        bare cert-based `x509` auth type, set `RUCIO_AUTH_TYPE=x509` or
        `auth_type = x509` in your `rucio.cfg` directly.

=== "userpass"

    Username and password authentication. Configure credentials in `rucio.cfg`:

    ```ini
    [client]
    rucio_host = https://rucio.cern.ch
    auth_host = https://rucio-auth.cern.ch
    auth_type = userpass
    username = <your_username>
    password = <your_password>
    account = <your_account>
    ```

    Or via environment variables:

    ```bash
    export RUCIO_AUTH_TYPE=userpass
    export RUCIO_CFG_CLIENT_USERNAME=<username>
    export RUCIO_CFG_CLIENT_PASSWORD=<password>
    export RUCIO_ACCOUNT=<account>
    ```

=== "OIDC"

    OpenID Connect authentication. Use the `escape`, `atlas`, `cms`, or `dune`
    presets, or point at a custom `rucio.cfg` with `auth_type = oidc`:

    ```bash
    export RUCIO_ACCOUNT=<your_account>
    rucio-mcp serve --site escape    # or --site atlas, --site cms, --site dune
    ```

    For OIDC with a custom cfg and an explicit auth-type override:

    ```bash
    rucio-mcp serve --rucio-cfg /path/to/rucio.cfg --auth-type oidc
    ```

## Rucio configuration presets

Bundled presets ship inside the package and are resolved at runtime — no copy
step is needed. Use `--site <name>` to select one.

=== "escape (default)"

    ```ini
    --8<-- "src/rucio_mcp/data/escape.cfg"
    ```

    > OIDC auth. Supports both stdio and HTTP transport modes.

=== "atlas"

    ```ini
    --8<-- "src/rucio_mcp/data/atlas.cfg"
    ```

    > OIDC auth. Supports both stdio and HTTP transport modes.

=== "cms"

    ```ini
    --8<-- "src/rucio_mcp/data/cms.cfg"
    ```

    > OIDC auth. Supports both stdio and HTTP transport modes.

=== "dune"

    ```ini
    --8<-- "src/rucio_mcp/data/dune.cfg"
    ```

    > OIDC auth. Supports both stdio and HTTP transport modes.

## Config resolution order

When `rucio-mcp serve` starts, it looks for `rucio.cfg` in this order:

1. **`--rucio-cfg <path>`** — explicit override, always used when provided.
2. **`--site <name>`** — resolves to the bundled preset for that site name.
3. **`$RUCIO_CONFIG`** — used when neither flag is given and the env var is set.
4. None found → startup fails with a clear error.

## Startup preflight checks

`rucio-mcp serve` runs preflight checks before starting and exits with a clear
error message if required configuration is missing.

**Config file not found:**

```
[rucio-mcp] Cannot start: configuration is incomplete.

  (1) rucio.cfg not found at /path/to/rucio.cfg.
      Use --site <name> to select a bundled preset, or
      --rucio-cfg <path> to point at a custom config file.
```

**Missing `X509_CERT_DIR` (warning, does not prevent startup):**

```
[rucio-mcp] WARNING: X509_CERT_DIR is not set. SSL certificate verification
    will fail when tools try to contact the Rucio server.
```

## Health check

Use `rucio-mcp ping` to verify connectivity to the Rucio server:

```bash
rucio-mcp ping
# version: 35.6.0
# account: gstark
# status: ok
```

This runs the same preflight checks as `serve` and then contacts the server, so
it also validates that your proxy and certificates are working.

## Site-managed deployments

If your facility provides a Rucio client installation (CVMFS, module system,
container image), point `--rucio-cfg` directly at the site's config file:

```bash
export RUCIO_ACCOUNT=<your_atlas_account>
voms-proxy-init -voms atlas
rucio-mcp serve \
  --site atlas \
  --auth-type x509 \
  --rucio-cfg /cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0/etc/rucio.cfg
```

Or set `RUCIO_CONFIG` before calling serve (without `--site`):

```bash
export RUCIO_CONFIG=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0/etc/rucio.cfg
rucio-mcp serve
```

## Hosting a pre-authenticated instance over HTTP (shared secret)

The HTTP transport normally runs as an OAuth 2.1 bridge, where each user logs in
via OIDC and the bearer is their own Rucio session token (see
[OAuth setup](oauth-setup.md)). That model does not fit a **single
pre-authenticated instance** — e.g. an x509/VOMS-proxy identity on a service
host that several clients should share.

For that case, start the server with `--shared-secret`. The server builds one
Rucio client from the environment (exactly like stdio, honoring `--auth-type`)
and gates every HTTP request behind a server-wide static bearer. This bypasses
the OIDC bridge entirely — there are no `/authorize`, `/token`, or `/register`
endpoints.

```bash
export RUCIO_ACCOUNT=<your_atlas_account>
voms-proxy-init -voms atlas
RUCIO_CONFIG=/cvmfs/.../rucio.cfg \
  rucio-mcp serve --transport http --site atlas --auth-type x509 \
    --shared-secret "$(openssl rand -hex 32)" --host 0.0.0.0 --port 8000
```

Clients must send the secret as a bearer token; any other (or missing) value is
rejected with `401`:

```bash
curl -X POST http://host:8000/site/atlas/ \
  -H 'Authorization: Bearer <secret>' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

Notes:

- The secret can also be supplied via the `RUCIO_MCP_SHARED_SECRET` environment
  variable instead of `--shared-secret`.
- Shared-secret mode serves **one** site (one env config = one pre-authenticated
  client); passing multiple `--site` flags is an error.
- `--resource-url` is optional here (it defaults to `http://<host>:<port>`);
  clients are configured with the bearer out-of-band rather than via OAuth
  discovery.

To run either HTTP mode on Kubernetes, see [Deploying with Helm](helm.md).

--8<-- "README.md:read-only"
