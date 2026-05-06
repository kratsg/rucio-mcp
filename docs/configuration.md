---
icon: lucide/settings
---

# Configuration

## Quick setup

The easiest way to configure `rucio-mcp` is the `init` subcommand, which writes
a preset `rucio.cfg` to `~/.config/rucio-mcp/rucio.cfg` so the server finds it
automatically — no extra environment variables required.

```bash
rucio-mcp init atlas        # write the ATLAS preset
rucio-mcp init --list       # show all available presets
```

Then set your account and renew your proxy:

```bash
export RUCIO_ACCOUNT=<your-atlas-account>
voms-proxy-init -voms atlas
rucio-mcp serve
```

!!! tip "Site-managed Rucio clients (UChicago AF, CERN lxplus, CVMFS)" If your
site already provides a Rucio client installation, set `RUCIO_CONFIG` to point
directly at the site's `rucio.cfg` — `init` is not needed and `RUCIO_CONFIG`
takes full priority. See [Site-managed deployments](#site-managed-deployments)
below.

## Environment variables

All authentication configuration is passed via environment variables, which are
read by both the `rucio-mcp` preflight check and the underlying Rucio client.

| Variable          | Required               | Description                                                                                              |
| ----------------- | ---------------------- | -------------------------------------------------------------------------------------------------------- |
| `RUCIO_CONFIG`    | No (if `init` was run) | Direct path to a `rucio.cfg` file. Takes highest priority when set.                                      |
| `RUCIO_AUTH_TYPE` | No                     | Authentication method: `x509_proxy`, `userpass`, `oidc`, `x509`. Defaults to `x509_proxy`.               |
| `RUCIO_ACCOUNT`   | Yes                    | Your Rucio account name                                                                                  |
| `X509_USER_PROXY` | x509                   | Path to your VOMS proxy certificate. Defaults to `/tmp/x509up_u<uid>`.                                   |
| `X509_CERT_DIR`   | x509                   | Directory of CA certificates for SSL verification. Set automatically by `ca-policy-lcg` when using pixi. |

## Authentication methods

=== "x509 proxy (ATLAS)"

    The most common method at ATLAS sites. Requires a valid VOMS proxy.

    **With pixi (recommended):** `ca-policy-lcg` is a bundled dependency and
    sets `X509_CERT_DIR` automatically to the certificates inside the conda
    environment (`$CONDA_PREFIX/etc/grid-security/certificates/`). You only
    need:

    ```bash
    rucio-mcp init atlas
    export RUCIO_ACCOUNT=<your_atlas_account>
    voms-proxy-init -voms atlas
    rucio-mcp serve
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

    OpenID Connect authentication. Set up via `rucio.cfg` or:

    ```bash
    export RUCIO_AUTH_TYPE=oidc
    export RUCIO_ACCOUNT=<your_account>
    ```

    Then authenticate interactively with `rucio login` before starting the server.

## Rucio configuration presets

`rucio-mcp init <preset>` copies a bundled `rucio.cfg` to
`~/.config/rucio-mcp/rucio.cfg`. The file is a starting point — edit it after
running `init` if your site uses non-standard endpoints.

=== "ATLAS"

    ```ini
    --8<-- "src/rucio_mcp/data/atlas.cfg"
    ```

## Config resolution order

When `rucio-mcp serve` starts, it looks for `rucio.cfg` in this order:

1. **`$RUCIO_CONFIG`** — used when `RUCIO_CONFIG` is explicitly set to a file
   path. Never overridden.
2. **`~/.config/rucio-mcp/rucio.cfg`** — used when `RUCIO_CONFIG` is unset and
   this file exists (created by `rucio-mcp init`). `RUCIO_CONFIG` is set to this
   path for the lifetime of the process.
3. Neither found → startup fails with a clear error pointing to
   `rucio-mcp init`.

`XDG_CONFIG_HOME` is respected: if set, step 2 looks in
`$XDG_CONFIG_HOME/rucio-mcp/rucio.cfg` instead.

## Startup preflight checks

`rucio-mcp serve` runs preflight checks before starting and exits with a clear
error message if required configuration is missing.

**No config found:**

```
[rucio-mcp] Cannot start: configuration is incomplete.

  (1) RUCIO_CONFIG is not set and no managed config was found.
      Run one of the following to get started:
        rucio-mcp init atlas
        rucio-mcp init --list
      Or set RUCIO_CONFIG manually:
        export RUCIO_CONFIG=/path/to/rucio.cfg
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
container image), point `RUCIO_CONFIG` directly at the site's config file and
skip `init`:

```bash
export RUCIO_CONFIG=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0/etc/rucio.cfg
export RUCIO_ACCOUNT=<your_atlas_account>
voms-proxy-init -voms atlas
rucio-mcp serve
```

`RUCIO_CONFIG` always takes priority over the managed config location.

--8<-- "README.md:read-only"
