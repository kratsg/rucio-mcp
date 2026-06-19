{{/*
Expand the name of the chart.
*/}}
{{- define "rucio-mcp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "rucio-mcp.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Chart name and version label value.
*/}}
{{- define "rucio-mcp.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "rucio-mcp.labels" -}}
helm.sh/chart: {{ include "rucio-mcp.chart" . }}
{{ include "rucio-mcp.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels. Kept stable (name + instance) so existing ServiceMonitors and
the AF dashboard's job="rucio-mcp" continue to match.
*/}}
{{- define "rucio-mcp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "rucio-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
ServiceAccount name to use.
*/}}
{{- define "rucio-mcp.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "rucio-mcp.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Name of the Secret holding the shared bearer (existing or chart-created).
*/}}
{{- define "rucio-mcp.sharedSecretName" -}}
{{- if .Values.auth.sharedSecret.existingSecret -}}
{{- .Values.auth.sharedSecret.existingSecret -}}
{{- else -}}
{{- printf "%s-shared-secret" (include "rucio-mcp.fullname" .) -}}
{{- end -}}
{{- end }}

{{/*
Validate the auth configuration. Fails the render early with a clear message
rather than producing a manifest the server would reject at startup.
*/}}
{{- define "rucio-mcp.validate" -}}
{{- if eq .Values.auth.mode "oidc" -}}
  {{/* resourceUrl resolution enforces its own requirement */}}
{{- else if eq .Values.auth.mode "sharedSecret" -}}
  {{- $ss := .Values.auth.sharedSecret -}}
  {{- if ne (len .Values.auth.sites) 1 -}}
    {{- fail "auth.mode=sharedSecret serves exactly one site: set auth.sites to a single entry" -}}
  {{- end -}}
  {{- if not $ss.rucioAccount -}}
    {{- fail "auth.mode=sharedSecret requires auth.sharedSecret.rucioAccount" -}}
  {{- end -}}
  {{- if and (not $ss.existingSecret) (not $ss.secretValue) -}}
    {{- fail "auth.mode=sharedSecret requires auth.sharedSecret.existingSecret or auth.sharedSecret.secretValue" -}}
  {{- end -}}
  {{- if or (eq $ss.authType "x509") (eq $ss.authType "x509_proxy") -}}
    {{- if not $ss.x509.existingSecret -}}
      {{- fail "auth.sharedSecret.authType x509/x509_proxy requires auth.sharedSecret.x509.existingSecret" -}}
    {{- end -}}
  {{- end -}}
{{- else -}}
  {{- fail (printf "auth.mode must be 'oidc' or 'sharedSecret', got %q" .Values.auth.mode) -}}
{{- end -}}
{{- end }}

{{/*
Public resource URL for oidc mode: explicit value, else derived from ingress host.
*/}}
{{- define "rucio-mcp.resourceUrl" -}}
{{- if .Values.server.resourceUrl -}}
{{- .Values.server.resourceUrl -}}
{{- else if .Values.ingress.host -}}
{{- printf "https://%s" .Values.ingress.host -}}
{{- else -}}
{{- fail "auth.mode=oidc requires server.resourceUrl or ingress.host to be set" -}}
{{- end -}}
{{- end }}

{{/*
Build the `rucio-mcp serve` argument string from values. The shared bearer is
passed via the RUCIO_MCP_SHARED_SECRET env var (not a flag) to keep it out of
the process table.
*/}}
{{- define "rucio-mcp.serveArgs" -}}
{{- include "rucio-mcp.validate" . -}}
{{- $args := list "--transport" "http"
    "--host" (.Values.server.host | toString)
    "--port" (.Values.server.port | toString)
    "--metrics-port" (.Values.server.metricsPort | toString)
    "--forwarded-allow-ips" (printf "'%s'" .Values.forwardedAllowIps)
    "--log-level" .Values.logLevel -}}
{{- range .Values.auth.sites -}}
{{- $args = append $args "--site" -}}
{{- $args = append $args (. | toString) -}}
{{- end -}}
{{- if .Values.readOnly -}}
{{- $args = append $args "--read-only" -}}
{{- end -}}
{{- if eq .Values.auth.mode "oidc" -}}
{{- $args = append $args "--resource-url" -}}
{{- $args = append $args (include "rucio-mcp.resourceUrl" .) -}}
{{- else -}}
{{- $args = append $args "--auth-type" -}}
{{- $args = append $args .Values.auth.sharedSecret.authType -}}
{{- if .Values.server.resourceUrl -}}
{{- $args = append $args "--resource-url" -}}
{{- $args = append $args .Values.server.resourceUrl -}}
{{- end -}}
{{- end -}}
{{- $args | join " " -}}
{{- end }}
