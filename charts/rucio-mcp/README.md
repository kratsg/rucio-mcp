# rucio-mcp Helm chart

Deploys [rucio-mcp](https://github.com/kratsg/rucio-mcp) over **HTTP transport**
on Kubernetes, in one of two auth models selected by `auth.mode`:

- **`oidc`** — multi-user OAuth 2.1 bridge; each user logs in via their IdP. No
  credentials live in the pod. Can serve several sites at once.
- **`sharedSecret`** — a single env-built Rucio client (e.g. an x509 robot
  identity) gated by a static bearer token. Serves exactly one site.

There is no published rucio-mcp container image: an init container runs the
`ghcr.io/prefix-dev/pixi` image and installs the pinned `rucioMcp.version` from
conda-forge into a shared volume at pod startup.

## Quick start

```bash
# OIDC bridge, multiple sites (the hosted/multi-user model)
helm install rucio-mcp ./charts/rucio-mcp \
  --namespace mcp --create-namespace \
  --set ingress.host=rucio-mcp.example.com
```

```bash
# x509 + shared-secret, single pre-authenticated site
kubectl -n mcp create secret generic rucio-x509 \
  --from-file=usercert.pem=robotcert.pem \
  --from-file=userkey.pem=robotkey.pem

helm install rucio-mcp ./charts/rucio-mcp \
  --namespace mcp --create-namespace \
  --set ingress.host=rucio-mcp.example.com \
  --set auth.mode=sharedSecret \
  --set 'auth.sites={atlas}' \
  --set auth.sharedSecret.rucioAccount=myrobot \
  --set auth.sharedSecret.authType=x509 \
  --set auth.sharedSecret.x509.existingSecret=rucio-x509 \
  --set auth.sharedSecret.x509.certKey=usercert.pem \
  --set auth.sharedSecret.x509.keyKey=userkey.pem \
  --set auth.sharedSecret.secretValue="$(openssl rand -hex 32)"
```

## Key values

| Key                        | Default                      | Description                                                       |
| -------------------------- | ---------------------------- | ----------------------------------------------------------------- |
| `auth.mode`                | `oidc`                       | `oidc` or `sharedSecret`                                          |
| `auth.sites`               | `[atlas, cms, dune, escape]` | Sites to serve; exactly one in `sharedSecret` mode                |
| `rucioMcp.version`         | `0.7.1`                      | rucio-mcp release pinned into `pixi.toml`                         |
| `rucioMcp.pixiLockContent` | `""`                         | Frozen `pixi.lock` for reproducible installs (`--set-file`)       |
| `readOnly`                 | `true`                       | Disable write tools                                               |
| `server.resourceUrl`       | `""`                         | Public URL; derived from `ingress.host` in `oidc` mode if empty   |
| `ingress.host`             | `""`                         | External hostname (required when `ingress.enabled`)               |
| `serviceMonitor.enabled`   | `false`                      | Create a Prometheus-Operator `ServiceMonitor` (requires its CRDs) |
| `grafanaDashboard.enabled` | `false`                      | Ship the Grafana dashboard ConfigMap                              |

See [`values.yaml`](values.yaml) for the full, documented set.

## Freezing the deployed version

By default `pixi install` resolves dependencies fresh at each pod start. For
reproducible rollouts, generate a lock against the rendered `pixi.toml` after a
release and feed it back in:

```bash
helm template r ./charts/rucio-mcp --show-only templates/configmap.yaml \
  --set ingress.host=rucio-mcp.example.com \
  | yq '.data["pixi.toml"]' > /tmp/pixi.toml
pixi lock --manifest-path /tmp/pixi.toml          # writes /tmp/pixi.lock
helm upgrade rucio-mcp ./charts/rucio-mcp \
  --reuse-values --set-file rucioMcp.pixiLockContent=/tmp/pixi.lock
```

Full documentation: see the project docs, "Deploying with Helm".
