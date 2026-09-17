{{/*
Shared template helpers.

The validation block at the bottom is the reason this file matters more than
most: every value that can produce a pod which reaches Ready while being
useless is checked here and fails the render with the name of the value.
*/}}

{{- define "onibex-ask.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "onibex-ask.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "onibex-ask.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Labels for every object. `component` comes in through the dict. */}}
{{- define "onibex-ask.labels" -}}
helm.sh/chart: {{ include "onibex-ask.chart" .ctx }}
{{ include "onibex-ask.selectorLabels" . }}
app.kubernetes.io/version: {{ .ctx.Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .ctx.Release.Service }}
app.kubernetes.io/part-of: onibex-ask
{{- with .ctx.Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "onibex-ask.selectorLabels" -}}
app.kubernetes.io/name: {{ include "onibex-ask.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "onibex-ask.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "onibex-ask.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/*
A first-party image reference, assembled from the registry values so that
moving registries is one line per target.
Usage: include "onibex-ask.image" (dict "ctx" $ "repository" $.Values.image.repositories.studio)
*/}}
{{- define "onibex-ask.image" -}}
{{- $img := .ctx.Values.image -}}
{{- $tag := default .ctx.Chart.AppVersion $img.tag -}}
{{- $parts := list -}}
{{- if $img.registry -}}{{- $parts = append $parts $img.registry -}}{{- end -}}
{{- if $img.namespace -}}{{- $parts = append $parts $img.namespace -}}{{- end -}}
{{- $parts = append $parts .repository -}}
{{- printf "%s:%s" (join "/" $parts) $tag -}}
{{- end -}}

{{- define "onibex-ask.imagePullSecrets" -}}
{{- with .Values.image.pullSecrets }}
imagePullSecrets:
{{- range . }}
  - name: {{ . }}
{{- end }}
{{- end }}
{{- end -}}

{{/* The Secret holding the irreducible three. */}}
{{- define "onibex-ask.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secret" (include "onibex-ask.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/* Where OpenSearch lives: this release's Service, or an external endpoint. */}}
{{- define "onibex-ask.opensearchHost" -}}
{{- if .Values.opensearch.host -}}
{{- .Values.opensearch.host -}}
{{- else if .Values.opensearch.enabled -}}
{{- printf "%s-opensearch" (include "onibex-ask.fullname" .) -}}
{{- else -}}
{{- fail "opensearch.enabled is false, so opensearch.host must name the external endpoint." -}}
{{- end -}}
{{- end -}}

{{/*
KEYCLOAK_JWKS_URL, which is the variable the validators actually read. An
earlier manifest published KEYCLOAK_ISSUER instead; nothing reads it, and being
optional it went unnoticed while every request was rejected.
*/}}
{{- define "onibex-ask.jwksUrl" -}}
{{- if .Values.auth.jwksUrl -}}
{{- .Values.auth.jwksUrl -}}
{{- else -}}
{{- printf "%s/realms/%s/protocol/openid-connect/certs" (trimSuffix "/" .Values.auth.publicUrl) .Values.auth.realm -}}
{{- end -}}
{{- end -}}

{{/* The OpenSearch client contract, identical in both backends. */}}
{{- define "onibex-ask.opensearchEnv" -}}
- name: OPENSEARCH_HOST
  value: {{ include "onibex-ask.opensearchHost" . | quote }}
- name: OPENSEARCH_PORT
  value: {{ .Values.opensearch.port | quote }}
- name: OPENSEARCH_USE_SSL
  value: {{ .Values.opensearch.useSsl | quote }}
- name: OPENSEARCH_USER
  valueFrom:
    secretKeyRef:
      name: {{ include "onibex-ask.secretName" . }}
      key: {{ .Values.secrets.keys.opensearchUser }}
      optional: true
- name: OPENSEARCH_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "onibex-ask.secretName" . }}
      key: {{ .Values.secrets.keys.opensearchPassword }}
      optional: true
{{- end -}}

{{/* Everything both Python backends share. */}}
{{- define "onibex-ask.backendEnv" -}}
- name: ENVIRONMENT
  value: {{ .Values.platform.environment | quote }}
- name: AUTH_MODE
  value: {{ .Values.auth.mode | quote }}
{{- /*
  Never true, and never a value. The bypass turned the admin API into an
  unauthenticated surface, so the chart does not offer the switch at all.
*/}}
- name: DEV_BYPASS_AUTH
  value: "false"
- name: LOG_LEVEL
  value: {{ .Values.platform.logLevel | quote }}
- name: PYTHONUNBUFFERED
  value: "1"
- name: KEYCLOAK_JWKS_URL
  value: {{ include "onibex-ask.jwksUrl" . | quote }}
- name: ASK_SEMANTIC_LANGUAGE
  value: {{ .Values.platform.semanticLanguage | quote }}
- name: ONIBEX_ENCRYPTION_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "onibex-ask.secretName" . }}
      key: {{ .Values.secrets.keys.encryptionKey }}
{{ include "onibex-ask.opensearchEnv" . }}
{{- include "onibex-ask.xsuaaEnv" . }}
{{- end -}}

{{/*
BTP only. Every key is optional, so the pods start on a cluster where this
Secret does not exist, which is every target that is not Kyma.
*/}}
{{- define "onibex-ask.xsuaaEnv" -}}
{{- $secret := .Values.xsuaa.existingSecret -}}
{{- if $secret }}
{{- range $var, $key := dict "XSUAA_URL" "url" "XSUAA_CLIENT_ID" "clientid" "XSUAA_CLIENT_SECRET" "clientsecret" "XSUAA_UAA_DOMAIN" "uaadomain" "XSUAA_VERIFICATION_KEY" "verificationkey" "XSUAA_XSAPPNAME" "xsappname" }}
- name: {{ $var }}
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ $key }}
      optional: true
{{- end }}
{{- end }}
{{- end -}}

{{/* The browser-facing configuration the three SPAs read at container start. */}}
{{- define "onibex-ask.spaEnv" -}}
- name: ASK_AUTH_MODE
  value: {{ .mode | quote }}
- name: ASK_KEYCLOAK_URL
  value: {{ .ctx.Values.auth.publicUrl | quote }}
- name: ASK_KEYCLOAK_REALM
  value: {{ .ctx.Values.auth.realm | quote }}
- name: ASK_KEYCLOAK_CLIENT_ID
  value: {{ .clientId | quote }}
{{- end -}}

{{/*
Spread replicas across nodes. This is what replaced the podAffinity, which
required co-location onto a pod that had been deleted and left both backends
Pending forever with an error that pointed nowhere near the cause.
*/}}
{{- define "onibex-ask.topologySpread" -}}
{{- if and .ctx.Values.topologySpread.enabled (gt (int .replicas) 1) }}
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: {{ .ctx.Values.topologySpread.topologyKey }}
    whenUnsatisfiable: {{ .ctx.Values.topologySpread.whenUnsatisfiable }}
    labelSelector:
      matchLabels:
        {{- include "onibex-ask.selectorLabels" (dict "ctx" .ctx "component" .component) | nindent 8 }}
{{- end }}
{{- end -}}

{{/*
Values that must not be guessed. Each of these produced, or would produce, a
pod that starts and then serves something broken, which is far more expensive
to diagnose than a failed render.
*/}}
{{- define "onibex-ask.validate" -}}
{{- if not (has .Values.auth.mode (list "keycloak" "xsuaa")) -}}
{{- fail (printf "auth.mode is %q. The token validators accept exactly \"keycloak\" or \"xsuaa\"; any other value matches no branch, leaves the claims unset and makes every request 401 while the pods report healthy. There is no \"both\": accepting two issuers at once is a code change." .Values.auth.mode) -}}
{{- end -}}

{{- $chat := default .Values.auth.mode .Values.auth.chatMode -}}
{{- if not (has $chat (list "keycloak" "xsuaa" "none")) -}}
{{- fail (printf "auth.chatMode is %q. The SPA entrypoint accepts keycloak, xsuaa or none, and stops on anything else rather than guessing. \"dev\" in particular was never a value anything understood: it fell through to the unknown branch, which happened to mean no login at all." $chat) -}}
{{- end -}}

{{- if and (ne .Values.auth.mode "xsuaa") (not .Values.auth.publicUrl) (not .Values.auth.jwksUrl) -}}
{{- fail "auth.publicUrl is empty. It is the origin of the identity provider AS THE BROWSER REACHES IT, scheme included and no trailing slash, and it must match the issuer in the tokens Keycloak signs. Leaving it empty used to produce a login page pointing at a host that does not exist, with nothing reporting it." -}}
{{- end -}}

{{- if not .Values.image.namespace -}}
{{- fail "image.namespace is empty. Set it to the registry account the seven ASK images were published under, for example \"onibex\". The chart renders <registry>/<namespace>/<repository>:<tag> and there is no default, because pulling from the wrong account fails late and confusingly." -}}
{{- end -}}

{{- if and (not .Values.secrets.existingSecret) (not .Values.secrets.create) -}}
{{- fail "No secret source. Either set secrets.existingSecret to a Secret you created out of band (recommended), or set secrets.create=true and fill in secrets.encryptionKey. The encryption key decrypts everything the platform stores in OpenSearch, so the backends refuse to boot without it." -}}
{{- end -}}

{{- if and .Values.secrets.create (not .Values.secrets.encryptionKey) -}}
{{- fail "secrets.create is true but secrets.encryptionKey is empty. Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\". It must stay byte-identical across upgrades or every stored secret becomes unreadable." -}}
{{- end -}}

{{- if and .Values.keycloak.enabled .Values.keycloak.production (not .Values.keycloak.database.host) -}}
{{- fail "keycloak.production is true but keycloak.database.host is empty. Production mode needs a real database; `start-dev` keeps state in an embedded file that does not survive a pod restart. Either point at a managed PostgreSQL or set keycloak.production=false and accept what that means." -}}
{{- end -}}

{{- if .Values.gateway.enabled -}}
{{- $anyHost := false -}}
{{- range $app, $host := .Values.gateway.hosts }}{{- if $host }}{{- $anyHost = true }}{{- end }}{{- end -}}
{{- if not $anyHost -}}
{{- fail "gateway.enabled is true but every gateway.hosts entry is empty, so the gateway would publish nothing. Each app needs its own hostname: they are built to be served from the root and collide on /api, /assets and the login callback when they share one." -}}
{{- end -}}
{{- if and .Values.gateway.hosts.auth .Values.keycloak.enabled -}}
{{- $expected := printf "https://%s" .Values.gateway.hosts.auth -}}
{{- if ne (trimSuffix "/" .Values.auth.publicUrl) $expected -}}
{{- fail (printf "auth.publicUrl is %q but the gateway publishes Keycloak at %q. They have to be the same string: auth.publicUrl is the issuer Keycloak stamps into every token, and the backends reject a token whose issuer is not what they were told to expect. The symptom is every request being rejected while all the pods report healthy." .Values.auth.publicUrl $expected) -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- if not (has .Values.platform.environment (list "local" "production")) -}}
{{- fail (printf "platform.environment is %q. The backends validate it against a literal and accept exactly \"local\" or \"production\". A reasonable-looking \"development\" does not crash at render, it crash-loops the admin API forty lines into a pydantic traceback." .Values.platform.environment) -}}
{{- end -}}

{{- if gt (int .Values.adminApi.replicas) 1 -}}
{{- fail "adminApi.replicas is above 1. The admin API owns a git working tree on a ReadWriteOnce volume, so a second replica either fails to schedule on another node or races on the same checkout. Scaling it horizontally needs the git remote to become the source of truth first." -}}
{{- end -}}
{{- end -}}
