# Deploy on Kubernetes with Helm

[Manual](../README.md) › [Operating the platform](../README.md#operating-the-platform) › **Deploy on Kubernetes with Helm**

> **How to.** Install the whole platform on a Kubernetes cluster from one Helm chart, on Azure
> AKS, AWS EKS or SAP BTP Kyma. For the person who has cluster access and is standing up an
> environment.
> **Scope:** the chart in `deploy/helm/onibex-ask`, the values it needs, and what to look at
> when a pod does not start.
> **Shell:** bash, on Linux or macOS, which is where a deployment normally runs.
> **Windows:** every `kubectl` and `helm` line is identical; the handful that are not have
> PowerShell equivalents at the end.

| | |
|---|---|
| **Who** | Whoever holds cluster credentials and the platform encryption key |
| **Time** | ~30 minutes for a first install, most of it waiting for images to pull |
| **You'll end with** | The nine services running, reachable through `kubectl port-forward` |

### What has to be installed

| Tool | Version | Used for |
|---|---|---|
| `kubectl` | Within one minor of the cluster. It is a supported skew of exactly one, so 1.28 against a 1.33 server works for simple commands and misbehaves on others | Everything |
| `helm` | 3 or later | Installing the chart |
| `python` | 3.10 or later | `scripts/make_realm_import.py`, and generating the encryption key |
| `openssl` | any | Generating passwords. Present on Linux and macOS; on Windows it ships with Git for Windows |
| `curl` | any | The checks at the end. **Not the `curl` in Windows PowerShell 5.1**, which is an alias for `Invoke-WebRequest` and takes different arguments |

Plus a namespace you can create objects in, and the seven ASK images published to a registry
the cluster can pull from.

---

## What this chart is, and what it deliberately is not

One chart renders every service the compose file runs: the two Python backends, the three
single-page apps, OpenSearch, Keycloak, and the two opt-in services.

**It names no cloud.** No Ingress, no storage class, no load balancer, no provider annotation.
That is not an omission, it is the design: those differ per target, and keeping them out is what
lets the same chart serve AKS, EKS and Kyma. Until a per-target values file adds an entry point,
you reach the apps with `kubectl port-forward`.

**It has been installed on Azure AKS 1.33**, with persistent volumes and a public entry point:
all seven services Ready, both backends answering `/v1/health`, OpenSearch green, four hostnames
answering over https with Let's Encrypt certificates, and the realm accepting the public redirect
URIs while rejecting an unlisted one. Everything beyond that, a data product published and a
question answered end to end, is still unverified.

---

## Before you start

**1. The images have to exist, and you have to know their tag.** Kubernetes builds nothing, it
pulls. The official images are published under `onibexenjoy`, all seven public, and that is the
`image.namespace` default, so a stock install needs no registry credentials and no pull secret.
Running your own build means running the `platform-images` workflow and setting
`image.namespace` to the account it published under.

Either way the tag is yours to supply, because there is no default that always exists.

The tag is where a first install usually fails, because the two ways of publishing produce
different ones and neither is `latest`:

| How it was published | Tag on the image |
|---|---|
| The workflow run by hand | `sha-<short commit>` only |
| A GitHub release | The git tag, for example `1.1.0` |

Leaving `image.tag` empty falls back to the chart's `appVersion`, which exists only after a
release. Check what is actually there before installing:

```bash
docker buildx imagetools inspect <registry>/<namespace>/ask-studio:<tag>
```

**2. Create the Secret out of band.** Three things cannot live anywhere else, because each is
needed before the store that holds everything else can be read.

```bash
kubectl create namespace onibex-ask

kubectl -n onibex-ask create secret generic ask-platform-secret \
  --from-literal=encryption-key="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  --from-literal=opensearch-user=admin \
  --from-literal=opensearch-password="$(openssl rand -base64 24)" \
  --from-literal=keycloak-admin-password="$(openssl rand -base64 24)"
```

> **The encryption key is not rotatable in place.** It decrypts every credential the platform
> stores in OpenSearch: the LLM provider keys, the database connections, the SAP password.
> Changing it is not a rotation, it is a data-loss event, and everything has to be entered again
> by hand in ASK Setup. Generate it once per environment and put it in a vault the same day.

**3. Decide the public address of the identity provider.** `auth.publicUrl` is the origin the
**browser** uses to reach Keycloak, and it is also the issuer stamped into every token. An
in-cluster Service name will not do: the OAuth exchange happens in the browser.

---

## Install

```bash
helm install ask deploy/helm/onibex-ask \
  --namespace onibex-ask \
  --values deploy/helm/onibex-ask/values-aks-dev.yaml \
  --set auth.publicUrl=https://auth.example.com
```

`values-aks-dev.yaml` pins both `image.namespace` and `image.tag`, so nothing about the registry
is passed on the command line. Add `--set image.namespace=...` and `--set image.tag=...` only
when running images you built yourself.

The install refuses to render rather than producing something half-working. Each refusal names
the value and says what goes wrong if it is guessed:

| If this is missing | Why the chart stops |
|---|---|
| `image.namespace` set to empty | The wrong account fails late as a pull error that names nothing. It has a default, so this only fires if you clear it |
| `auth.publicUrl` | An empty value used to serve a login page pointing at a host that does not exist, with nothing reporting it |
| A secret source | The backends refuse to boot without the encryption key anyway; failing here is faster to read |
| A valid `auth.mode` | The token validators accept exactly `keycloak` or `xsuaa`. Anything else matches no branch and every request is rejected while the pods report healthy |
| `keycloak.database.host` when production is on | Production mode without a database is a contradiction; development mode keeps state in a file inside the pod |

---

## Publishing it: why there is a gateway, and why TLS is not optional

Set `gateway.enabled` and the chart adds a small Caddy in front, one public Service per
hostname, and certificates it obtains and renews by itself.

**TLS is not a hardening step here, it is what makes the login work at all.** The three apps
sign in with PKCE and call `crypto.subtle`, which the browser only exposes in a secure context:
`https`, or `localhost`. On a plain `http://<ip>` address the login button throws and nothing
happens. That is a browser rule, so an entry point without TLS is not a cheaper option, it is a
broken one.

**Each app needs its own hostname.** They are built to be served from the root: the API client
asks for `/api`, the bundle asks for `/assets`, and the login returns to `<origin>/login/callback`
with the path discarded. Under one shared hostname all three collide, and no router can fix it
from outside, because those addresses are compiled into the JavaScript. Serving one hostname
with paths is possible but it is image work, not chart work.

On AKS, `service.beta.kubernetes.io/azure-dns-label-name` gets a free public name of the form
`<label>.<region>.cloudapp.azure.com`. It is a real public name, so Let's Encrypt will issue for
it, which means no domain of your own is needed to get a valid certificate. The label has to be
unique across the whole region, not just your subscription.

> **Leave port 80 open even when everything is served over 443.** It is where Let's Encrypt
> answers the challenge, at issue and again at every renewal. Close it and the certificate
> expires quietly ninety days later.

### Build the realm before the first public address exists

The realm committed here is a local demo: its users carry a password published on GitHub, and
its redirect URIs list `localhost` ports. Deploying it unchanged puts that password on whatever
address the platform answers on, and the login stops with `Invalid parameter: redirect_uri`
after the user has already typed it.

```bash
python scripts/make_realm_import.py --password 'Chosen.Initial.Password' \
  --host studio=https://studio.example.com \
  --host chat=https://chat.example.com \
  --host setup=https://setup.example.com \
  --out /tmp/realm.json

kubectl -n onibex-ask create secret generic ask-realm \
  --from-file=ask-platform-realm.json=/tmp/realm.json
rm /tmp/realm.json
```

Then set `keycloak.realmImportSecret=ask-realm`. Every password it writes is **temporary**, so
Keycloak requires a change at first sign-in and the shared initial value stops working once each
person has used it.

The Keycloak administrator is separate: its password comes from the platform Secret, and it is
not covered by the realm file. Give it the same treatment by hand, once:

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"requiredActions":["UPDATE_PASSWORD"]}' \
  "$AUTH/admin/realms/master/users/$ADMIN_ID"
```

> **A realm is imported only on a first boot.** Once `keycloak.persistence` is on, the file is
> ignored on every later start and changes belong in the admin console. To re-import, scale
> Keycloak to zero, delete its PersistentVolumeClaim, and let the chart recreate it. That is
> also the only way to change the administrator password from the Secret, because Keycloak
> creates that user once and never revisits the variable.

## Reach the apps

```bash
kubectl -n onibex-ask port-forward svc/ask-studio 5173:80
kubectl -n onibex-ask port-forward svc/ask-chat 5174:80
kubectl -n onibex-ask port-forward svc/ask-setup 5175:80
kubectl -n onibex-ask port-forward svc/ask-onibex-ask-keycloak 8180:8080
```

The backends need no forward of their own: each app's nginx proxies `/api` to them by Service
name, inside the cluster.

---

## The order things come up, and what that means for a stuck pod

1. **OpenSearch** must be Ready before either backend finishes its own boot.
2. **The admin API** must be Ready before the MCP server stops retrying its contract fetch. The
   MCP server stays unready and retries rather than starting with zero tools, so a long
   `0/1 Running` there is expected while the admin API is still starting.
3. **The apps** start independently. They serve a bundle and do not wait for anything.

```bash
kubectl -n onibex-ask get pods -w
kubectl -n onibex-ask logs deploy/ask-onibex-ask-studio
```

### The failures worth knowing in advance

**An app pod restarts immediately and the log names a variable.** That is the intended
behaviour. The entrypoint refuses to start on an empty required value instead of falling back to
`localhost`, which is what used to produce a working-looking deployment pointing nowhere.

**Every request is rejected while the pods report healthy.** The issuer does not match. Compare
`auth.publicUrl` against the issuer in a token, and remember that the browser and the pods must
be told the same address unless `auth.jwksUrl` is set explicitly.

**The admin API will not start.** Two causes, and the traceback distinguishes them. It refuses
to boot when the semantic-layer paths are empty or do not point at a real directory, so check
that the volume was bound with `kubectl -n onibex-ask get pvc`. It also refuses an
unrecognised `platform.environment`: the settings object accepts `local` or `production` and
nothing else, so a reasonable-looking `development` crash-loops it forty lines into a pydantic
error. The chart now stops at render time on that one.

**An app pod crash-loops on `chown(/var/cache/nginx/client_temp) failed`.** nginx starts as
root, chowns its cache directories and drops its workers to an unprivileged user, so it needs
CHOWN, SETUID and SETGID kept. Dropping every capability and adding back only NET_BIND_SERVICE
looks tighter and stops all three apps.

**A rollout hangs with the new pod Pending and `Insufficient cpu`.** A rolling update reserves
the new pod's requests before releasing the old pod's, so a node with no spare CPU cannot hold
both. Set `updateStrategy: Recreate`, and read the note in `values.yaml` first: changing it on
an installed release fails until the Deployments are recreated.

**OpenSearch is Ready but searches behave oddly under load.** Many node images ship
`vm.max_map_count` at 65530 and OpenSearch wants 262144. Single-node mode skips the check that
would refuse to start, so the symptom arrives later. Raising it is a node-level change, which is
why the chart does not attempt it; on a cluster you do not own, use a managed OpenSearch endpoint
instead with `opensearch.enabled=false`.

**Restarting the MCP server from ASK Setup reports itself unsupported.** Correct. That button
drives a container runtime socket, there is no such socket in a pod, and mounting one would be
root on the node for anything that lands there.

---

## Uninstall, and what survives

```bash
helm uninstall ask --namespace onibex-ask
```

**Every volume survives, and so does the Secret.** A reinstall on top of them is a restore, not
a fresh install:

| Volume | Holds |
|---|---|
| `data-ask-onibex-ask-opensearch-0` | the registries, the RAG schema, and the encrypted store: LLM and database credentials, the SAP connection, the OpenAPI contracts |
| `ask-onibex-ask-semantic-layer` | the YAML corpus and the git working tree around it |
| `ask-onibex-ask-keycloak` | the realm, the users, and any password changed since the import |
| `ask-onibex-ask-gateway-data` | the Let's Encrypt certificates and the ACME account key |

Three carry `helm.sh/resource-policy: keep`. The OpenSearch one is a StatefulSet
`volumeClaimTemplates` claim, which Kubernetes never deletes on its own either. The Secret is
yours rather than the chart's, and is left for the same reason.

The semantic layer is the one to think about twice: it can hold YAML authored and not yet
pushed, and its git remote may not exist at all, in which case that volume is the only copy.

To start from nothing, name them:

```bash
kubectl -n onibex-ask delete pvc \
  ask-onibex-ask-semantic-layer \
  ask-onibex-ask-keycloak \
  ask-onibex-ask-gateway-data \
  data-ask-onibex-ask-opensearch-0

kubectl -n onibex-ask delete secret <the secret you created>
kubectl delete namespace onibex-ask
```

The namespace matters because installing starts by creating it, and a namespace left behind
makes that first command fail with `AlreadyExists` on an environment that is otherwise empty.

The four `LoadBalancer` Services take a minute or two to disappear after the uninstall. They sit
in `Terminating` behind a `service.kubernetes.io/load-balancer-cleanup` finalizer while the
cloud releases the load balancers and the public IP addresses. That is the billing stopping, so
it is worth waiting for `kubectl -n onibex-ask get svc` to come back empty rather than assuming
it happened.

**Two things that read as bugs when a volume is kept by accident.** Keycloak does not re-import
the realm, so a password changed in the console stays changed and the initial one keeps being
rejected. OpenSearch keeps every credential, so ASK Setup looks fully configured before anyone
has configured it.

**And one cost of deleting the gateway volume.** Certificates are requested again on the next
start. Let's Encrypt limits duplicate certificates to five per week for the same set of names,
so repeated teardowns can run out. Keeping that one volume and deleting the rest avoids it.

---

## What is not done yet

- **Keycloak runs its embedded file database.** `keycloak.production: false` runs `start-dev`.
  A volume keeps that file across restarts, which is what makes a changed password stick, but it
  is still one instance writing one local file: no second replica, and no rolling upgrade across
  schema versions. A deployment anyone depends on sets `keycloak.production: true` and points
  `keycloak.database` at a Postgres.
- **The apps run as root inside their container.** Their images are stock nginx on port 80.
  Fixing it means rebuilding them on an unprivileged base, which is image work rather than chart
  work. Three backends are in the same position for the same reason: their Dockerfiles declare
  no `USER`, which is why they render with `rootImageSecurityContext` instead of the
  `runAsUser: 1000` the others get.
- **Only AKS has been installed from this chart.** Nothing in it is Azure-specific beyond the
  DNS-label annotation in the AKS profile, but EKS and Kyma have not been exercised, and the
  gateway's assumption that a `LoadBalancer` Service yields a routable address is the part most
  likely to need a different answer on each.

---

## On Windows and PowerShell

Every `kubectl` and `helm` line above runs unchanged. What differs is the shell around them, and
these are the four places it bites.

**`curl` is not curl.** In Windows PowerShell 5.1 it is an alias for `Invoke-WebRequest`, which
takes different arguments and fails confusingly on `-X` or `-H`. Call the real one by its full
name, `curl.exe`, or run the checks from Git Bash.

**There is no command substitution with `$(...)`, and no `\` line continuation.** Build the value
first, then pass it:

```powershell
$rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::Create()
$b = New-Object byte[] 32; $rng.GetBytes($b)
$key = [Convert]::ToBase64String($b).Replace('+','-').Replace('/','_')
$p1 = New-Object byte[] 18; $rng.GetBytes($p1)
$p2 = New-Object byte[] 18; $rng.GetBytes($p2)

kubectl -n onibex-ask create secret generic ask-platform-secret `
  --from-literal=encryption-key=$key `
  --from-literal=opensearch-user=admin `
  --from-literal=opensearch-password=$([Convert]::ToBase64String($p1)) `
  --from-literal=keycloak-admin-password=$([Convert]::ToBase64String($p2))
```

> `RandomNumberGenerator::Fill` and `SHA256::HashData` do not exist in Windows PowerShell 5.1.
> They fail at the call and leave the surrounding command running with an EMPTY value, which
> creates a Secret that looks fine and holds nothing. Check what you wrote:
> `kubectl -n onibex-ask get secret ask-platform-secret -o jsonpath='{.data.encryption-key}'`
> decoded should be 44 characters.

**Reading a value back out of a Secret**, which is the equivalent of `| base64 -d`:

```powershell
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((kubectl -n onibex-ask get secret ask-platform-secret -o "jsonpath={.data.encryption-key}")))
```

**Paths and deletion.** `/tmp/realm.json` is `$env:TEMP\realm.json`, and `rm` is `Remove-Item`.
The realm file carries passwords, so deleting it after loading the Secret is part of the
procedure, not tidying.

Git Bash, WSL or a Linux shell avoids all four. If you have one, use it: the commands in this
page are then literal.

---

[← Back to the manual](../README.md)
