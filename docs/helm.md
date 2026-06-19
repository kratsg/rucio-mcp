---
icon: lucide/ship-wheel
---

# Deploying with Helm

The chart at
[`charts/rucio-mcp`](https://github.com/kratsg/rucio-mcp/tree/main/charts/rucio-mcp)
deploys rucio-mcp over **HTTP transport** on Kubernetes. It supports the two
hosted auth models the server implements, selected by `auth.mode`:

- **`oidc`** — the multi-user [OAuth 2.1 bridge](oauth-setup.md): each user logs
  in via their IdP and the bearer is their own Rucio session token. No
  credentials live in the pod, and one deployment can serve several sites.
- **`sharedSecret`** — a single
  [pre-authenticated client over a static bearer](configuration.md#hosting-a-pre-authenticated-instance-over-http-shared-secret):
  the pod runs one env-built Rucio client (e.g. an x509 robot identity) and
  gates every request behind a shared secret. Serves exactly one site.

There is no published rucio-mcp image. An init container runs the
`ghcr.io/prefix-dev/pixi` image and installs the pinned `rucioMcp.version` from
conda-forge into a shared volume; the main container then runs
`rucio-mcp serve`.

## Prerequisites

- A Kubernetes cluster and Helm 3+.
- An ingress controller and (for TLS) cert-manager, if `ingress.enabled` (the
  default). Defaults assume `nginx` + a `letsencrypt-prod` ClusterIssuer.
- The
  [Prometheus Operator](https://github.com/prometheus-operator/prometheus-operator)
  CRDs if `serviceMonitor.enabled` (the default) — otherwise set it to `false`.

## OIDC bridge mode (multi-user)

```bash
helm install rucio-mcp ./charts/rucio-mcp \
  --namespace mcp --create-namespace \
  --set ingress.host=rucio-mcp.example.com
```

This serves the default site set (`atlas`, `cms`, `dune`, `escape`) read-only,
with each site mounted at `/site/<name>/`. The public `server.resourceUrl` used
to build OAuth redirect URIs is derived from `ingress.host`; set it explicitly
if the server sits behind a different external URL.

Point an MCP client at the per-site URL (e.g.
`https://rucio-mcp.example.com/site/atlas/`); it discovers the OAuth endpoints
automatically. See [OAuth setup](oauth-setup.md) for the client side.

## x509 + shared-secret mode (single pre-authenticated site)

First create the Secrets the pod consumes — the chart never holds the x509
material itself. Provide a robot cert/key (or a refreshed VOMS proxy) in a
Secret you manage:

```bash
# x509 robot credentials (bare cert + key)
kubectl -n mcp create secret generic rucio-x509 \
  --from-file=usercert.pem=robotcert.pem \
  --from-file=userkey.pem=robotkey.pem
```

Then install in shared-secret mode:

```bash
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

Notes:

- `auth.sites` must hold exactly one site in this mode (one env config = one
  pre-authenticated client); the chart fails the render otherwise.
- For a VOMS proxy instead of a bare cert, set
  `auth.sharedSecret.authType=x509_proxy` and
  `auth.sharedSecret.x509.proxyKey=<key>` (mounted to `X509_USER_PROXY`).
  Proxies are short-lived — refresh the Secret out-of-band; the chart only
  consumes it.
- The CA trust bundle (`X509_CERT_DIR`) is set automatically by `ca-policy-lcg`,
  which rucio-mcp already depends on. To force the latest CA bundle, add it to
  the rendered `pixi.toml`:
  `--set rucioMcp.extraPixiDependencies.ca-policy-lcg='*'`.
- Prefer `auth.sharedSecret.existingSecret` (a Secret you create with key
  `shared-secret`) over `secretValue` in production so the token never lands in
  Helm values or CI logs.

Retrieve the generated bearer and configure clients with it out-of-band:

```bash
kubectl -n mcp get secret rucio-mcp-shared-secret \
  -o jsonpath='{.data.shared-secret}' | base64 -d; echo
```

```json
{
  "mcpServers": {
    "rucio-atlas": {
      "type": "http",
      "url": "https://rucio-mcp.example.com/site/atlas/",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

## Monitoring

- `serviceMonitor.enabled` (default `true`) creates a `ServiceMonitor` scraping
  `/metrics` on the metrics port.
- `grafanaDashboard.enabled` ships the bundled dashboard as a ConfigMap labelled
  for the Grafana sidecar. Set `grafanaDashboard.namespace` to the namespace
  your Grafana watches if it differs from the release namespace:

```bash
helm upgrade rucio-mcp ./charts/rucio-mcp --reuse-values \
  --set grafanaDashboard.enabled=true \
  --set grafanaDashboard.namespace=prom
```

## Freezing the deployed version

The chart ships `pixi.toml` (pinning `rucioMcp.version`) but **no `pixi.lock`**
— a release must exist before it can be locked, and `pixi install` otherwise
resolves dependencies fresh at each pod start. For reproducible rollouts,
generate a lock against the rendered `pixi.toml` and feed it back in:

```bash
helm template r ./charts/rucio-mcp --show-only templates/configmap.yaml \
  --set ingress.host=rucio-mcp.example.com \
  | yq '.data["pixi.toml"]' > /tmp/pixi.toml
pixi lock --manifest-path /tmp/pixi.toml          # writes /tmp/pixi.lock alongside it
helm upgrade rucio-mcp ./charts/rucio-mcp --reuse-values \
  --set-file rucioMcp.pixiLockContent=/tmp/pixi.lock
```

When `rucioMcp.pixiLockContent` is set, the lock is mounted next to `pixi.toml`
and pixi installs from it.

## Verifying and validating the chart

```bash
pixi run helm-lint       # lint the chart
pixi run helm-template   # render with default (OIDC) values
helm test rucio-mcp -n mcp   # run the /healthz test hook against a live release
```

## Uninstall

```bash
helm uninstall rucio-mcp -n mcp
```

Secrets you created yourself (the x509 Secret, and any `existingSecret` for the
bearer) are not owned by the release and must be removed separately.
