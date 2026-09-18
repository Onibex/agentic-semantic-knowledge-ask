# Deploy on Kubernetes with Helm

[Manual](../README.md) › [Operating the platform](../README.md#operating-the-platform) › **Deploy on Kubernetes with Helm**

> **How to.** Install the whole platform on a Kubernetes cluster from one Helm chart, on Azure
> AKS, AWS EKS or SAP BTP Kyma. Six steps, using the images Onibex publishes.
> **Shell:** bash, on Linux or macOS. Every `kubectl` and `helm` line is identical on Windows;
> the handful of surrounding commands that are not have PowerShell equivalents at the end.

| | |
|---|---|
| **Who** | Whoever holds cluster credentials |
| **Time** | About 30 minutes, most of it waiting for images to pull |
| **You'll end with** | Eight of the nine services Ready, the three apps open in a browser with a working sign-in, and the MCP server deliberately unready until you register a contract |

---

## What you need

**Every command on this page runs from `platform/`**, the directory holding `docker-compose.yml`,
and every path is relative to it. The repository root also has a `scripts/` directory, so running
from there does not fail with "no such file": it fails later and less clearly.

```bash
cd platform
```

**You do not build anything.** The seven images are already published on Docker Hub under
`onibexenjoy`, all public, and the chart points at them by default. Kubernetes pulls; nothing is
compiled here. (If you do need your own build, see [Running images you built
yourself](#running-images-you-built-yourself) at the end. Skip it otherwise.)

| Tool | Version | Used for |
|---|---|---|
| `kubectl` | Within one minor of the cluster, either way. Check with `kubectl version`; fix with `az aks install-cli --client-version <the cluster's minor>` | Everything |
| `helm` | 3 or later | Installing the chart |
| `python` | 3.10 or later | The encryption key and the realm file |
| `openssl` | any | Generating passwords. On Windows it ships with Git for Windows |
| `curl` | any | The checks at the end. **Not PowerShell 5.1's `curl`**, which is an alias for `Invoke-WebRequest` |

> **`kubectl` has three ways to be wrong and they chain.** Too old fails the skew; running
> `az aks install-cli` with no `--client-version` installs the newest stable, which fails the skew
> from the other side; and on Windows, Docker Desktop ships its own `kubectl` early in the system
> PATH, so the right one can be installed and still not be the one that runs. `which kubectl`
> settles the third.

### Capacity

The requests below are what the scheduler reserves. **`kubectl top` does not answer this
question**: it reports usage, and a node can be nearly idle and still have nothing left to give.

| Profile | CPU requests | Memory requests |
|---|---|---|
| `values.yaml`, chart defaults | 775m | 3008Mi |
| `values-aks-dev.yaml` | 510m | 3200Mi |

Per service, so you can see where it goes and what disabling something buys you:

| Service | CPU | Memory |
|---|---|---|
| OpenSearch | 250m default, 100m in the AKS profile | 1536Mi |
| Orchestrator | 250m default, 150m in the AKS profile | 512Mi |
| Admin API | 100m | 512Mi |
| Keycloak | 100m default, 50m in the AKS profile | 256Mi |
| Studio, Chat, Setup | 25m each | 64Mi each |
| MCP server | 50m default, 10m in the AKS profile | 128Mi |
| Gateway | 25m | 64Mi |

It has to fit **on one node**, not across the cluster, because a pod is scheduled to a single
node. Read what is left with:

```bash
kubectl describe node <node> | sed -n '/Allocated resources/,/Events/p'
```

---

## Step 0. Check the ground before you build on it

Six commands. Each one answers something that otherwise surfaces several steps later as a
different-looking failure.

```bash
which kubectl helm python openssl curl
kubectl config current-context
kubectl version
kubectl get storageclass
kubectl get ns onibex-ask
kubectl describe node <node> | sed -n '/Allocated resources/,/Events/p'
```

**`which` on all five at once is the one people skip.** Installed and findable are different
questions, and the gap is invisible until a command fails: a tool answering in one shell and not
in another, or a second copy earlier in the PATH answering instead of the one you installed.

The rest: `current-context` because installing into the wrong cluster is quiet and expensive;
`version` for the skew above; `get storageclass` because there has to be a default one for the
volumes to bind; `get ns` because an existing namespace changes what Step 1 prints; and the node
line for the capacity table above.

---

## Step 1. Create the namespace and the Secret

**Five values** cannot live in the chart: four because they are needed before the store that
holds everything else can be read, and one because it is how two services authenticate to each
other.

```bash
kubectl create namespace onibex-ask
```

`AlreadyExists` here is benign if the namespace is empty, which
`kubectl -n onibex-ask get all` will tell you. It is a leftover from a previous install, and the
[uninstall section](#uninstall-and-what-survives) says how to clear it properly. Run the Secret
as its own command so a namespace that already exists does not look like the Secret failing:

```bash
kubectl -n onibex-ask create secret generic ask-platform-secret \
  --from-literal=encryption-key="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  --from-literal=opensearch-user=admin \
  --from-literal=opensearch-password="$(openssl rand -base64 24)" \
  --from-literal=keycloak-admin-password="$(openssl rand -base64 24)" \
  --from-literal=ingest-api-key="$(openssl rand -hex 32)"
```

**Check what you actually wrote before moving on.** Every value above comes from a command
substitution, and a substitution that fails silently produces a Secret that looks fine and holds
nothing:

```bash
for k in encryption-key opensearch-user opensearch-password keycloak-admin-password ingest-api-key; do
  printf '%-24s %s bytes\n' "$k" \
    "$(kubectl -n onibex-ask get secret ask-platform-secret -o "jsonpath={.data.$k}" | base64 -d | wc -c)"
done
```

Expect 44, 5, 32, 32 and 64. **A zero means the substitution failed and the key is empty.**

> **`ingest-api-key` is the one people skip, and it stops the install.** The name says ingest, but
> the MCP server sends it on two calls that have nothing to do with ingestion: the API contracts
> it downloads at boot, and the SAP connection it re-reads every minute. A server with no
> contracts has no tools to offer, so it refuses to start rather than come up empty, and the pod
> lands in `CrashLoopBackOff` naming `ASK_INGEST_API_KEY`. Leave it out only with
> `mcpServer.enabled=false`.

> **The encryption key is not rotatable in place.** It decrypts every credential the platform
> stores: the LLM provider keys, the database connections, the SAP password. Changing it is not a
> rotation, it is a data-loss event, and everything has to be entered again by hand in ASK Setup.
> Generate it once per environment and put it in a vault the same day.

---

## Step 2. Decide the addresses people will use

This decides the next two steps, so settle it before installing. There are two answers and both
are legitimate.

**A. Public hostnames, one per app.** The chart adds a small Caddy in front, one public Service
per hostname, and certificates it obtains and renews by itself. On AKS you get the hostnames free:
the annotation `service.beta.kubernetes.io/azure-dns-label-name` yields
`<label>.<region>.cloudapp.azure.com`, a real public name Let's Encrypt will issue for, so no
domain of your own is needed. The label has to be unique across the whole region.

`values-aks-dev.yaml` is set up this way. Edit the four labels in its `gateway.hosts` block, then
use those four addresses in step 3. A label has to be free across the whole region, so check
before you commit to one:

```bash
nslookup <label>.<region>.cloudapp.azure.com 2>&1 | grep -q "Non-existent domain" && echo free || echo TAKEN
```

Grep the message rather than testing the exit code. **`nslookup` exits 0 even for a name that does
not exist**, so an exit-code test reports every label as taken.

**A.2. Your own domain.** The production case, and the ordering matters more than the commands.
Certificates are issued by answering a challenge at the name itself, so **the DNS record has to
exist and resolve before the gateway first starts**. In the other order nothing errors loudly: the
certificate is simply never issued, and the site keeps answering on plain http.

1. Install with `gateway.enabled=true` and read the addresses the cloud assigned:
   `kubectl -n onibex-ask get svc`.
2. Create one `A` record per app, pointing at the matching `EXTERNAL-IP`.
3. Wait until all four resolve from outside the cluster.
4. Put the four names in `gateway.hosts`, **remove the `azure-dns-label-name` annotations** (they
   are only for the free Azure names), and upgrade.

The certificates arrive within a minute or two of the gateway restarting with names that already
resolve.

**B. No public address, reached through a tunnel.** Install with `gateway.enabled=false` and
forward the ports to your own machine. Good for a first look and for a cluster with no load
balancer.

```bash
kubectl -n onibex-ask port-forward svc/ask-studio 5173:80
kubectl -n onibex-ask port-forward svc/ask-chat 5174:80
kubectl -n onibex-ask port-forward svc/ask-setup 5175:80
kubectl -n onibex-ask port-forward svc/ask-onibex-ask-keycloak 8180:8080
```

> **Why there is no third option.** A plain `http://<ip>` address does not work, and not for
> security reasons. The three apps sign in with PKCE and call `crypto.subtle`, which browsers
> expose only in a secure context: `https`, or `localhost`. On plain http the sign-in button
> throws and nothing happens. That is a browser rule, not a setting. Option B works precisely
> because `localhost` is on that list.

---

## Step 3. Build the realm for those addresses

The realm committed in this repository is a local demo. Its users carry a password published on
GitHub, and its redirect URIs list `localhost` ports. Deploying it unchanged puts that password on
whatever address the platform answers on, and the sign-in stops with `Invalid parameter:
redirect_uri` after the user has already typed it.

Generate one for your addresses instead, using the four you chose in step 2:

**The realm enforces its own password policy on this value, at import time**, so pick one that
satisfies `length(8) and digits(1) and upperCase(1)` before you run anything. The script checks it
and refuses; Keycloak, if the check is ever bypassed, aborts the whole realm import instead.

```bash
python scripts/make_realm_import.py --password 'Chosen.Initial.Password1' \
  --host studio=https://studio.example.com \
  --host chat=https://chat.example.com \
  --host setup=https://setup.example.com \
  --out ./realm.json

kubectl -n onibex-ask create secret generic ask-realm \
  --from-file=ask-platform-realm.json=./realm.json
rm ./realm.json
```

> The file is written to the current directory rather than `/tmp` on purpose. Under Git Bash on
> Windows, a leading `/` triggers MSYS path translation, so `/tmp/realm.json` reaches the program
> rewritten into a Windows path and the two commands can disagree about where the file is. A
> relative path is never translated.

Every password it writes is **temporary**, so Keycloak requires a change at first sign-in and the
shared initial value stops working once each person has used it.

**It also prints three new client secrets, and that output is the only time you see them.** The
realm holds three confidential clients whose secrets are committed to this repository as demo
values, and one of them, `kafka-ingest`, has a service account carrying the `ask-admin` role.
Nothing tells a service-account token apart from a person's, so shipping that secret unchanged
puts the whole administrative API behind a credential anyone can read on GitHub. The script
replaces all three every time it runs.

Copy them somewhere safe before you delete the realm file. Anything authenticating as one of
those clients needs the new value: for the Kafka Connect HTTP Sink that is `oauth2.client.secret`.

The Keycloak administrator is separate: its password comes from the Secret in step 1, and the
realm file does not cover it. Give it the same treatment by hand, once, after the platform is up:

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"requiredActions":["UPDATE_PASSWORD"]}' \
  "$AUTH/admin/realms/master/users/$ADMIN_ID"
```

---

## Step 4. Install

```bash
helm install ask deploy/helm/onibex-ask \
  --namespace onibex-ask \
  --values deploy/helm/onibex-ask/values-aks-dev.yaml \
  --set auth.publicUrl=https://auth.example.com \
  --set keycloak.realmImportSecret=ask-realm
```

`auth.publicUrl` is the origin the **browser** uses to reach Keycloak, and it is also the issuer
stamped into every token. An in-cluster Service name will not do: the OAuth exchange happens in
the browser. It has to match the Keycloak hostname from step 2 exactly, and the chart refuses to
install if it does not.

**Render it first.** The chart checks seven values before producing anything, so the same command
with `template` in place of `install` turns seven possible failures into a two-second check that
never touches the cluster:

```bash
helm template ask deploy/helm/onibex-ask \
  --values deploy/helm/onibex-ask/values-aks-dev.yaml \
  --set auth.publicUrl=https://auth.example.com \
  --set keycloak.realmImportSecret=ask-realm \
  --set secrets.existingSecret=ask-platform-secret > /dev/null
```

Silence means it rendered. Anything else is one of the refusals below, quoted in full.

The install refuses to render rather than producing something half-working. Each refusal names the
value and says what goes wrong if it is guessed:

| If this is wrong | Why the chart stops |
|---|---|
| `auth.publicUrl` empty, or not the gateway's Keycloak host | A login page pointing at a host that does not exist, with nothing reporting it |
| No secret source | The backends refuse to boot without the encryption key anyway; failing here is faster to read |
| `auth.mode` not `keycloak` or `xsuaa` | Anything else matches no branch and every request is rejected while the pods report healthy |
| `platform.environment` not `local` or `production` | A reasonable-looking `development` crash-loops the admin API forty lines into a pydantic error |
| `keycloak.database.host` empty while production is on | Production mode without a database is a contradiction |
| `image.namespace` cleared | It has a default, so this only fires if you empty it deliberately |

---

## Step 5. Watch it come up

```bash
kubectl -n onibex-ask get pods -w
```

Three things start in order, and knowing it saves you from chasing a pod that is only waiting:

1. **OpenSearch** must be Ready before either backend finishes its own boot.
2. **The apps** start independently. They serve a bundle and wait for nothing.
3. **The MCP server waits for something this runbook does not provide**, and the next section is
   about that.

### A clean install finishes at eight of nine, not nine of nine

**The MCP server stays `0/1 Running` and it never leaves on its own.** It is not waiting for the
admin API. It fetches its API contracts from the admin API at boot, there are none stored until
somebody saves them on the Contracts page in ASK Setup, and it will not start with zero tools
because a server that advertises nothing is worse than one that is honestly unready. So it retries,
with the wait doubling each time, until the contracts exist.

That makes it the one pod whose readiness depends on a human, and its wait crossing minutes is the
system working rather than failing. It goes Ready within a minute of contracts being saved, with no
restart.

**So the expected end state here is eight Ready and the MCP unready.** If the other eight are Ready,
Step 5 is done. Come back to this pod after
[Register an OpenAPI contract](../ask-setup/07-contracts.md), and only then treat `0/1` as a
problem.

| Status | What it means |
|---|---|
| `0/1 Running` on the MCP server, no contracts saved yet | The expected end state of a clean install. Leave it |
| `0/1 Running` on the MCP server, contracts saved | Now it is worth reading: the admin API is unreachable from it, or the ingest key does not match |
| `CrashLoopBackOff` anywhere | A defect. The container died; waiting will not fix it. Read the log of the run that failed |

```bash
kubectl -n onibex-ask logs <pod> --previous
```

`--previous` matters: without it you read the container that is about to die rather than the one
that already did, and on a fast crash loop you often get nothing at all.

If something is stuck, [the failures worth knowing in advance](#the-failures-worth-knowing-in-advance)
covers the ones that have actually happened.

---

## Step 6. Sign in, and change the passwords

Open ASK Setup at the address from step 2 and sign in with the initial password from step 3.
Keycloak asks for a new one immediately; that is the shared value retiring.

From there the platform is empty and
[Configure the platform first · ASK Setup](../ask-setup/README.md) takes over: the database, the
model provider, then the semantic layer in ASK Studio.

**And this is where the ninth pod comes up.** Registering your first contract on the
[Register an OpenAPI contract](../ask-setup/07-contracts.md) page gives the MCP server the thing it
has been waiting for since Step 5. It picks them up within a minute and goes Ready on its own, with
no restart. If you are not using SAP actions at all, leave it unready or install with
`mcpServer.enabled=false`.

> **Leave port 80 open even when everything is served over 443.** It is where Let's Encrypt
> answers the challenge, at issue and again at every renewal. Close it and the certificate expires
> quietly ninety days later.

---

## What this chart is, and what it deliberately is not

One chart renders every service the compose file runs: the two Python backends, the three
single-page apps, OpenSearch, Keycloak, and the two opt-in services.

**It names no cloud.** No storage class, no load balancer, no provider annotation in the chart
itself. That is not an omission, it is the design: those differ per target, and keeping them in a
values file is what lets the same chart serve AKS, EKS and Kyma.

**Each app needs its own hostname, and no router can change that.** The three apps are built to be
served from the root: the API client asks for `/api`, the bundle asks for `/assets`, and the login
returns to `<origin>/login/callback` with the path discarded. Under one shared hostname all three
collide in all three places, and an Ingress cannot fix it from outside, because those addresses are
compiled into the JavaScript. Serving one hostname with paths is possible, but it is image work,
not chart work.

**A realm is imported only on a first boot.** Once `keycloak.persistence` is on, the file is
ignored on every later start and changes belong in the admin console. To re-import, scale Keycloak
to zero, delete its PersistentVolumeClaim, and let the chart recreate it. That is also the only way
to change the administrator password from the Secret, because Keycloak creates that user once and
never revisits the variable.

---

## Running images you built yourself

Skip this unless you are changing the product. The published images are the supported path.

Run the `platform-images` workflow, then pass the account it published under and the tag it
produced:

```bash
helm install ask deploy/helm/onibex-ask ... \
  --set image.namespace=<your-account> \
  --set image.tag=<the tag>
```

The tag is where this usually fails, because neither way of publishing produces `latest`:

| How it was published | Tag on the image |
|---|---|
| The workflow run by hand | `sha-<short commit>` only |
| A GitHub release | The git tag, for example `1.1.0` |

Leaving `image.tag` empty falls back to the chart's `appVersion`, which exists only after a
release. Check what is actually there first:

```bash
docker buildx imagetools inspect docker.io/<account>/ask-studio:<tag>
```

If your registry is private, create a pull secret and name it in `image.pullSecrets`.

---

## The failures worth knowing in advance

**An app pod restarts immediately and the log names a variable.** That is the intended behaviour.
The entrypoint refuses to start on an empty required value instead of falling back to `localhost`,
which is what used to produce a working-looking deployment pointing nowhere.

**Every request is rejected while the pods report healthy.** The issuer does not match. Compare
`auth.publicUrl` against the issuer in a token, and remember that the browser and the pods must be
told the same address unless `auth.jwksUrl` is set explicitly.

**The admin API will not start.** Two causes, and the traceback distinguishes them. It refuses to
boot when the semantic-layer paths are empty or do not point at a real directory. It also refuses
an unrecognised `platform.environment`, which the chart now stops at render time.

**Keycloak crash-loops and the log says `invalidPasswordMinDigitsMessage`.** The realm enforces
`length(8) and digits(1) and upperCase(1)` **while importing**, not at first sign-in, so an initial
password that breaks it does not produce a user who must pick a better one: it aborts the import
and takes the server down with it. The message arrives about twenty lines into a Quarkus startup
log, with nothing naming the argument that caused it. The cause is `--password` back in
[Step 3](#step-3-build-the-realm-for-those-addresses), and the fix is a new realm Secret built with
a compliant password. `make_realm_import.py` checks this before writing the file, so this only
appears on a realm assembled some other way.

**A volume sits in `Pending` and it is usually fine.** Do not read `Pending` from
`kubectl get pvc` as a failure. The default StorageClass on AKS, and on most managed clusters, is
`WaitForFirstConsumer`: the disk is deliberately not created until a pod that needs it is
scheduled, so that it lands in the right zone. Read the events instead of the phase:

```bash
kubectl -n onibex-ask describe pvc <name>
```

`WaitForFirstConsumer` in the events is normal. `ProvisioningFailed` is the real problem.

**An app pod crash-loops on `chown(/var/cache/nginx/client_temp) failed`.** nginx starts as root,
chowns its cache directories and drops its workers to an unprivileged user, so it needs CHOWN,
SETUID and SETGID kept. Dropping every capability and adding back only NET_BIND_SERVICE looks
tighter and stops all three apps.

**A rollout hangs with the new pod Pending and `Insufficient cpu`.** A rolling update reserves the
new pod's requests before releasing the old pod's, so a node with no spare CPU cannot hold both.
Set `updateStrategy: Recreate`, and read the note in `values.yaml` first: changing it on an
installed release fails until the Deployments are recreated.

**OpenSearch is Ready but searches behave oddly under load.** Many node images ship
`vm.max_map_count` at 65530 and OpenSearch wants 262144. Single-node mode skips the check that
would refuse to start, so the symptom arrives later. Raising it is a node-level change, which is
why the chart does not attempt it; on a cluster you do not own, use a managed OpenSearch endpoint
instead with `opensearch.enabled=false`.

**Restarting the MCP server from ASK Setup reports itself unsupported.** Correct. That button
drives a container runtime socket, there is no such socket in a pod, and mounting one would be root
on the node for anything that lands there. It is also unnecessary: the MCP server re-reads its SAP
connection from the store about once a minute, so a change in ASK Setup applies on its own.

---

## Uninstall, and what survives

```bash
helm uninstall ask --namespace onibex-ask
```

**Every volume survives, and so does the Secret.** A reinstall on top of them is a restore, not a
fresh install:

| Volume | Holds |
|---|---|
| `data-ask-onibex-ask-opensearch-0` | the registries, the RAG schema, and the encrypted store: LLM and database credentials, the SAP connection, the OpenAPI contracts |
| `ask-onibex-ask-semantic-layer` | the YAML corpus and the git working tree around it |
| `ask-onibex-ask-keycloak` | the realm, the users, and any password changed since the import |
| `ask-onibex-ask-gateway-data` | the Let's Encrypt certificates and the ACME account key |

Three carry `helm.sh/resource-policy: keep`. The OpenSearch one is a StatefulSet
`volumeClaimTemplates` claim, which Kubernetes never deletes on its own either. The Secret is yours
rather than the chart's, and is left for the same reason.

The semantic layer is the one to think about twice: it can hold YAML authored and not yet pushed,
and its git remote may not exist at all, in which case that volume is the only copy. Export it from
ASK Studio first, on the Health page.

To start from nothing, name them:

```bash
kubectl -n onibex-ask delete pvc \
  ask-onibex-ask-semantic-layer \
  ask-onibex-ask-keycloak \
  ask-onibex-ask-gateway-data \
  data-ask-onibex-ask-opensearch-0

kubectl -n onibex-ask delete secret ask-platform-secret ask-realm
kubectl delete namespace onibex-ask
```

The namespace matters because installing starts by creating it, and a namespace left behind makes
step 1 fail with `AlreadyExists` on an environment that is otherwise empty.

The `LoadBalancer` Services take a minute or two to disappear after the uninstall. They sit in
`Terminating` behind a `service.kubernetes.io/load-balancer-cleanup` finalizer while the cloud
releases the load balancers and the public IP addresses. That is the billing stopping, so it is
worth waiting for `kubectl -n onibex-ask get svc` to come back empty rather than assuming it
happened.

**Two things that read as bugs when a volume is kept by accident.** Keycloak does not re-import the
realm, so a password changed in the console stays changed and the initial one keeps being rejected.
OpenSearch keeps every credential, so ASK Setup looks fully configured before anyone has configured
it.

**And one cost of deleting the gateway volume.** Certificates are requested again on the next
start. Let's Encrypt limits duplicate certificates to five per week for the same set of names, so
repeated teardowns can run out. Keeping that one volume and deleting the rest avoids it.

---

## What is not done yet

- **Keycloak runs its embedded file database.** `keycloak.production: false` runs `start-dev`. A
  volume keeps that file across restarts, which is what makes a changed password stick, but it is
  still one instance writing one local file: no second replica, and no rolling upgrade across
  schema versions. A deployment anyone depends on sets `keycloak.production: true` and points
  `keycloak.database` at a Postgres.
- **The apps run as root inside their container.** Their images are stock nginx on port 80. Fixing
  it means rebuilding them on an unprivileged base, which is image work rather than chart work.
  Three backends are in the same position for the same reason: their Dockerfiles declare no `USER`,
  which is why they render with `rootImageSecurityContext` instead of the `runAsUser: 1000` the
  others get.
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

**And `cmd.exe` is the one to avoid outright.** It does not expand `$(...)` at all and does not
treat it as an error either: the Secret in Step 1 is created with the literal string
`$(python -c ...)` as its value, the command reports success, and the failure surfaces three steps
later as backends that cannot decrypt anything. Same failure shape as the PowerShell trap above,
with nothing to warn you. The length check at the end of Step 1 catches both.

Git Bash, WSL or a Linux shell avoids all of this. If you have one, use it: the commands in this
page are then literal, with the single exception of the relative path noted in Step 3.

---

[← Back to the manual](../README.md)
