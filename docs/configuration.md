---
icon: lucide/settings
---

# Configuration

## Environment variables

All authentication configuration is passed via environment variables, which are
read by both the `rucio-mcp` preflight check and the underlying Rucio client.

| Variable          | Required | Description                                                     |
| ----------------- | -------- | --------------------------------------------------------------- |
| `RUCIO_HOME`      | Yes      | Path to rucio-clients directory containing `etc/rucio.cfg`      |
| `RUCIO_AUTH_TYPE` | Yes      | Authentication method: `x509_proxy`, `userpass`, `oidc`, `x509` |
| `RUCIO_ACCOUNT`   | Yes      | Your Rucio account name                                         |
| `X509_USER_PROXY` | x509     | Path to your VOMS proxy certificate                             |
| `X509_CERT_DIR`   | x509     | Directory of CA certificates for SSL verification. Set automatically by `ca-policy-lcg` when using pixi. |

## Authentication methods

=== "x509 proxy (ATLAS)"

    The most common method at ATLAS sites. Requires a valid VOMS proxy.

    **With pixi (recommended):** `ca-policy-lcg` is a bundled dependency and
    sets `X509_CERT_DIR` automatically to the certificates inside the conda
    environment (`$CONDA_PREFIX/etc/grid-security/certificates/`). You only
    need:

    ```bash
    voms-proxy-init -voms atlas
    export RUCIO_ACCOUNT=<your_atlas_account>
    export RUCIO_AUTH_TYPE=x509_proxy
    export RUCIO_HOME=/path/to/rucio-clients
    ```

    **Without pixi — on CVMFS-based facilities (UChicago AF, CERN lxplus, etc.):**

    ```bash
    voms-proxy-init -voms atlas
    export RUCIO_ACCOUNT=<your_atlas_account>
    export RUCIO_AUTH_TYPE=x509_proxy
    export X509_CERT_DIR=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/etc/grid-security-emi/certificates
    export RUCIO_HOME=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0
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

## Startup preflight checks

`rucio-mcp serve` runs preflight checks before starting and exits with a clear
error message if required configuration is missing.

**Missing `RUCIO_HOME`:**

```
[rucio-mcp] Cannot start: configuration is incomplete.

  (1) RUCIO_HOME is not set. Set it to the rucio-clients directory
      that contains etc/rucio.cfg.
      Example:
        export RUCIO_HOME=/cvmfs/atlas.cern.ch/repo/ATLASLocalRootBase/x86_64/rucio-clients/35.6.0
```

**Missing `RUCIO_AUTH_TYPE`:**

```
[rucio-mcp] Cannot start: configuration is incomplete.

  (1) RUCIO_AUTH_TYPE is not set. Set it to your authentication method,
      or add 'auth_type = ...' to the [client] section of rucio.cfg.
      Example:
        export RUCIO_AUTH_TYPE=x509_proxy
```

**Missing `X509_CERT_DIR` (warning, does not prevent startup):**

```
[rucio-mcp] WARNING: X509_CERT_DIR is not set. SSL certificate verification
    will fail when tools try to contact the Rucio server.
```

--8<-- "README.md:read-only"
