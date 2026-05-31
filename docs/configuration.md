---
icon: lucide/settings
---

# Configuration

## Quick setup

Select a bundled site preset with `--site`. The server resolves directly to the
bundled `rucio.cfg` — no prior setup step required.

```bash
export RUCIO_ACCOUNT=<your-atlas-account>
voms-proxy-init -voms atlas
rucio-mcp serve --site atlas        # atlas is also the default
```

Available presets: `atlas` (x509 proxy, stdio only), `escape` (OIDC, stdio and
HTTP).

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
| `RUCIO_AUTH_TYPE` | No       | Authentication method: `x509_proxy`, `userpass`, `oidc`, `x509`. Defaults to `x509_proxy`.               |
| `RUCIO_ACCOUNT`   | Yes      | Your Rucio account name                                                                                  |
| `X509_USER_PROXY` | x509     | Path to your VOMS proxy certificate. Defaults to `/tmp/x509up_u<uid>`.                                   |
| `X509_CERT_DIR`   | x509     | Directory of CA certificates for SSL verification. Set automatically by `ca-policy-lcg` when using pixi. |

## Authentication methods

=== "x509 proxy (ATLAS)"

    The most common method at ATLAS sites. Requires a valid VOMS proxy.

    **With pixi (recommended):** `ca-policy-lcg` is a bundled dependency and
    sets `X509_CERT_DIR` automatically to the certificates inside the conda
    environment (`$CONDA_PREFIX/etc/grid-security/certificates/`). You only
    need:

    ```bash
    export RUCIO_ACCOUNT=<your_atlas_account>
    pixi exec --with rucio-mcp voms-proxy-init -voms atlas
    rucio-mcp serve --site atlas
    ```

    **Without pixi — on CVMFS-based facilities (UChicago AF, CERN lxplus, etc.):**

    ```bash
    export RUCIO_ACCOUNT=<your_atlas_account>
    export RUCIO_AUTH_TYPE=x509_proxy
    export X509_CERT_DIR=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/etc/grid-security-emi/certificates
    export RUCIO_CONFIG=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0/etc/rucio.cfg
    voms-proxy-init -voms atlas
    rucio-mcp serve
    ```

    **Without pixi — elsewhere:** set `X509_CERT_DIR` to a local CA bundle.
    If you have CVMFS with ATLAS installed, the path is already available:

    ```bash
    export X509_CERT_DIR=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/etc/grid-security-emi/certificates
    ```

    Otherwise, install `ca-policy-lcg` from conda-forge or from your system
    package manager (`fetch-crl` / `ca-policy-egi-core`).

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

    OpenID Connect authentication. Use the `escape` preset or point at a custom
    `rucio.cfg` with `auth_type = oidc`:

    ```bash
    export RUCIO_ACCOUNT=<your_account>
    rucio-mcp serve --site escape
    ```

    For OIDC with a custom cfg and an explicit auth-type override:

    ```bash
    rucio-mcp serve --rucio-cfg /path/to/rucio.cfg --auth-type oidc
    ```

## Rucio configuration presets

Bundled presets ship inside the package and are resolved at runtime — no copy
step is needed. Use `--site <name>` to select one.

=== "ATLAS"

    ```ini
    --8<-- "src/rucio_mcp/data/atlas.cfg"
    ```

    > x509 proxy auth only. HTTP mode is not yet supported for ATLAS because
    > Rucio does not currently offer OIDC for ATLAS end-users.

=== "ESCAPE"

    ```ini
    --8<-- "src/rucio_mcp/data/escape.cfg"
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
  --rucio-cfg /cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0/etc/rucio.cfg
```

Or set `RUCIO_CONFIG` before calling serve (without `--site`):

```bash
export RUCIO_CONFIG=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0/etc/rucio.cfg
rucio-mcp serve
```

--8<-- "README.md:read-only"
