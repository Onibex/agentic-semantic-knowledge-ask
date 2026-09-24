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

WHEN KEYCLOAK IS IN THE RELEASE, THE PODS FETCH THE KEYS OVER THE CLUSTER
NETWORK, not over the public hostname. This is not an optimisation. Deriving it
from auth.publicUrl sends the backends out through the gateway, and with
gateway.tls.mode=internal that certificate is signed by Caddy's own authority,
which no pod trusts. The fetch fails with CERTIFICATE_VERIFY_FAILED, the
validator ends up with no keys, and EVERY request is answered 401 with "no
configured issuer accepted the token" while all nine pods report healthy and the
browser login itself works perfectly. It cost a smoke test to find, because the
sign-in redirect chain is fine and only the first API call fails.

Nothing is lost by taking the short path: the validator checks the signature and
the expiry and does NOT check the issuer, so the keys are the same keys whichever
address they arrive from, and the token still carries the public issuer the
browser saw.

auth.jwksUrl still overrides, and an identity provider outside the release still
derives from auth.publicUrl, because there is no in-cluster Service to use.
*/}}
{{- define "onibex-ask.jwksUrl" -}}
{{- if .Values.auth.jwksUrl -}}
{{- .Values.auth.jwksUrl -}}
{{- else if .Values.keycloak.enabled -}}
{{- printf "http://%s-keycloak:8080/realms/%s/protocol/openid-connect/certs" (include "onibex-ask.fullname" .) .Values.auth.realm -}}
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
{{- if eq .Values.auth.mode "ias" }}
{{- /* The tenant, for the keys, and the client id, for the audience. Both
       are needed; the validator fails closed without either. */}}
- name: IAS_URL
  value: {{ .Values.auth.ias.url | quote }}
- name: IAS_CLIENT_ID
  value: {{ .Values.auth.ias.clientId | quote }}
{{- end }}
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

{{/*
The four things that get a public hostname, and the in-cluster Service behind
each one.

There are four and not nine because the backends are never published: each SPA
image carries an nginx that proxies /api to ask-admin-api over the cluster
network, so the browser only ever talks to the three apps and to the identity
provider.

THIS LIST IS SHARED ON PURPOSE. Caddy reads it to build its Caddyfile and the
APIRule template reads it to expose the same four Services through Istio. When
it lived inside gateway.yaml, adding a target on one publishing path silently
left the other one behind. Parsed with fromYaml at the call site, because Helm
templates return strings.
*/}}
{{- define "onibex-ask.publishedBackends" -}}
studio:
  service: ask-studio
  port: 80
chat:
  service: ask-chat
  port: 80
setup:
  service: ask-setup
  port: 80
auth:
  service: {{ include "onibex-ask.fullname" . }}-keycloak
  port: 8080
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
{{- if eq .mode "ias" }}
{{- /* One IAS application for the three apps: its redirect URIs list
       all three origins, and it is the audience the backends check. */}}
- name: ASK_IAS_URL
  value: {{ .ctx.Values.auth.ias.url | quote }}
- name: ASK_IAS_CLIENT_ID
  value: {{ .ctx.Values.auth.ias.clientId | quote }}
{{- end }}
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
{{- if not (has .Values.auth.mode (list "keycloak" "xsuaa" "ias")) -}}
{{- fail (printf "auth.mode is %q. The token validators accept exactly \"keycloak\", \"ias\" or \"xsuaa\"; any other value matches no branch, leaves the claims unset and makes every request 401 while the pods report healthy. There is no \"both\": accepting two issuers at once is a code change." .Values.auth.mode) -}}
{{- end -}}

{{- $chat := default .Values.auth.mode .Values.auth.chatMode -}}
{{- if not (has $chat (list "keycloak" "xsuaa" "ias" "none")) -}}
{{- fail (printf "auth.chatMode is %q. The SPA entrypoint accepts keycloak, ias, xsuaa or none, and stops on anything else rather than guessing. \"dev\" in particular was never a value anything understood: it fell through to the unknown branch, which happened to mean no login at all." $chat) -}}
{{- end -}}

{{- if and (eq .Values.auth.mode "keycloak") (not .Values.auth.publicUrl) (not .Values.auth.jwksUrl) -}}
{{- fail "auth.publicUrl is empty. It is the origin of the identity provider AS THE BROWSER REACHES IT, scheme included and no trailing slash, and it must match the issuer in the tokens Keycloak signs. Leaving it empty used to produce a login page pointing at a host that does not exist, with nothing reporting it." -}}
{{- end -}}

{{- if and (eq .Values.auth.mode "ias") (or (not .Values.auth.ias.url) (not .Values.auth.ias.clientId)) -}}
{{- fail "auth.mode is ias, so both auth.ias.url and auth.ias.clientId must be set. The url is the customer's IAS tenant origin, for example https://<tenant>.accounts.ondemand.com. The client id is not optional: the backends refuse every token without it, because it is what they check the audience against, and without that check a token issued to any other application in the customer's tenant would be accepted." -}}
{{- end -}}

{{- if not .Values.image.namespace -}}
{{- fail "image.namespace is empty. Set it to the registry account the seven ASK images were published under, for example \"onibex\". The chart renders <registry>/<namespace>/<repository>:<tag> and there is no default, because pulling from the wrong account fails late and confusingly." -}}
{{- end -}}

{{- /*
  XSUAA CANNOT SIGN A BROWSER IN ON ITS OWN, and this was measured rather than
  read, against a real instance on 2026-09-23. The three SPAs sign in with the
  authorization code flow plus PKCE, as public clients, because a browser can
  never hold a client secret. XSUAA refuses exactly that exchange:

    POST /oauth/token, client_id and no secret
    -> 401 {"error":"invalid_client","error_description":"Bad credentials"}

  It rejects the CLIENT before it looks at the code. SAP's own sample confirms
  the design limit: it puts SAP Cloud Identity Services (IAS) in front as the
  public client and exchanges that token for an XSUAA one server-side. The
  classic alternative is an approuter holding the secret, which this chart
  does not ship.

  So until one of those exists, this mode renders pods that start and a
  sign-in that cannot finish, after the password has been typed. The same
  probe against IAS returns 400 invalid_grant, rejecting the fake code and not
  the client, which is why IAS is the supported way to use the customer's SAP
  identity.
*/}}
{{- $chatMode := default .Values.auth.mode .Values.auth.chatMode -}}
{{- if or (eq .Values.auth.mode "xsuaa") (eq $chatMode "xsuaa") -}}
{{- fail "auth.mode (or auth.chatMode) is xsuaa, and the three SPAs cannot sign in against XSUAA directly: XSUAA requires a client secret at the token exchange (401 invalid_client, measured 2026-09-23) and a browser can never hold one. For the customer's SAP identity use SAP Cloud Identity Services instead. The backends still validate XSUAA tokens correctly, for a front end that holds the secret server-side, but this chart does not ship one." -}}
{{- end -}}

{{- if and .Values.kyma.enabled .Values.gateway.enabled -}}
{{- fail "kyma.enabled and gateway.enabled are both true. They are two ways to publish the SAME four hostnames: Kyma routes them through Istio on the shared gateway, the gateway block runs a Caddy of its own behind one load balancer per name. Running both exposes every app twice through two different certificates while only one of them answers the name in DNS, and the one that answers depends on which Service the cloud wired up. On Kyma set gateway.enabled=false; everywhere else set kyma.enabled=false." -}}
{{- end -}}

{{- if and .Values.kyma.enabled (not (compact (values .Values.gateway.hosts))) -}}
{{- fail "kyma.enabled is true but every entry in gateway.hosts is empty, so the render produces no APIRule and the install publishes nothing at all while reporting success. gateway.hosts is the list of published hostnames whoever does the publishing; put the four names under the cluster's wildcard domain there." -}}
{{- end -}}

{{- if and (not .Values.secrets.existingSecret) (not .Values.secrets.create) -}}
{{- fail "No secret source. Either set secrets.existingSecret to a Secret you created out of band (recommended), or set secrets.create=true and fill in secrets.encryptionKey. The encryption key decrypts everything the platform stores in OpenSearch, so the backends refuse to boot without it." -}}
{{- end -}}

{{- if and .Values.secrets.create (not .Values.secrets.encryptionKey) -}}
{{- fail "secrets.create is true but secrets.encryptionKey is empty. Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\". It must stay byte-identical across upgrades or every stored secret becomes unreadable." -}}
{{- end -}}

{{- /* Only reachable when the chart owns the Secret. With secrets.existingSecret
       the chart cannot see inside it, so a missing ingest key surfaces as the
       MCP server crash-looping instead. That is why the runbook creates all five
       keys and prints their lengths rather than relying on this. */ -}}
{{- if and .Values.secrets.create .Values.mcpServer.enabled (not .Values.secrets.ingestApiKey) -}}
{{- fail "mcpServer.enabled is true but secrets.ingestApiKey is empty. The MCP server sends that key to the admin API to download its API contracts at boot, and a server with no contracts has no tools to offer, so it refuses to start: the pod lands in CrashLoopBackOff naming ASK_INGEST_API_KEY. Generate one with `openssl rand -hex 32`, or set mcpServer.enabled=false if you do not need SAP actions." -}}
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
{{- if not (has .Values.gateway.tls.mode (list "acme" "internal" "existing")) -}}
{{- fail (printf "gateway.tls.mode is %q. It accepts exactly \"acme\", \"internal\" or \"existing\". This one fails more quietly than the others: an unrecognised value matches no branch, so the Caddyfile is rendered with no tls directive at all. Caddy then falls back to its own default, which is to request a public certificate for every hostname, with no address to warn anyone when renewal stops working. The site can look right for ninety days and then go untrusted with nobody notified." .Values.gateway.tls.mode) -}}
{{- end -}}
{{- if eq .Values.gateway.tls.mode "existing" -}}
{{- if not .Values.gateway.tls.existingSecret -}}
{{- fail "gateway.tls.mode is \"existing\" but gateway.tls.existingSecret is empty, so there is no certificate to serve. Create one out of band and name it here:\n  kubectl -n <ns> create secret tls ask-gateway-tls --cert=fullchain.pem --key=privkey.pem\n--cert must be the FULL CHAIN, leaf plus intermediates. A leaf on its own works in the browser of whoever tested it, because that browser had the intermediate cached, and warns on every other machine." -}}
{{- end -}}
{{- if or (not .Values.gateway.tls.certKey) (not .Values.gateway.tls.keyKey) -}}
{{- fail "gateway.tls.mode is \"existing\" but gateway.tls.certKey or gateway.tls.keyKey is empty. They name the two entries inside the Secret and default to the kubernetes.io/tls names, tls.crt and tls.key. Emptying one renders a Caddyfile pointing at a directory instead of a file, and Caddy refuses to start." -}}
{{- end -}}
{{- end -}}
{{- /* An empty gateway.tls.email is deliberately NOT fatal: values.yaml
       documents it as optional and says so in as many words, and a render that
       stops would contradict its own contract. It is a real cost all the same,
       so NOTES.txt warns about it where warnings belong. */ -}}
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
