# Deploy ASK on Azure AKS

[Manual](../README.md) › [Operating the platform](../README.md#operating-the-platform) › **Deploy ASK on Azure AKS**

> **How to.** Install the whole platform on an Azure AKS cluster from one Helm chart, using the
> images Onibex publishes. Read top to bottom and run every command; there are no branches.
> **Shell:** bash. On Windows use Git Bash, and see
> [On Windows and PowerShell](kubernetes-reference.md#on-windows-and-powershell).

| | |
|---|---|
| **Who** | Whoever holds credentials for the subscription the cluster is in |
| **Time** | About 30 minutes, most of it waiting for images to pull |
| **You'll end with** | Eight of the nine services Ready, the three apps open in a browser on public HTTPS addresses with certificates from Let's Encrypt and a working sign-in, and the MCP server deliberately unready until you register a contract |

**On another cloud?** [Deploy ASK on AWS EKS](kubernetes-deploy-aws-eks.md) has its own page,
because the first two steps are genuinely different. Everything that is the same on every cloud is in the
[Kubernetes reference](kubernetes-reference.md).

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
compiled here. (If you do need your own build, see
[Running images you built yourself](kubernetes-reference.md#running-images-you-built-yourself).)

| Tool | Version | Used for |
|---|---|---|
| `az` | 2 | Getting a kubeconfig |
| `kubectl` | Within one minor of the cluster, either way. Check with `kubectl version`; fix with `az aks install-cli --client-version <the cluster's minor>` | Everything |
| `helm` | 3 or later | Installing the chart |
| `python` | 3.10 or later | The encryption key and the realm file |
| `openssl` | any | Generating passwords. On Windows it ships with Git for Windows |
| `curl` | any | The checks at the end. **Not PowerShell 5.1's `curl`**, which is an alias for `Invoke-WebRequest` |

> **`kubectl` has three ways to be wrong and they chain.** Too old fails the skew; running
> `az aks install-cli` with no `--client-version` installs the newest stable, which fails the skew
> from the other side; and on Windows, Docker Desktop ships its own `kubectl` early in the system
> PATH, so the right one can be installed and still not be the one that runs.
>
> ```bash
> which az kubectl helm python openssl curl
> ```
>
> settles the third, and it has to be run in the shell you are actually going to use: Git Bash and
> PowerShell read different PATHs, so a tool installed from one can be invisible to the other.

### What this costs while it runs

| | |
|---|---|
| The node | Depends on the size. A four-vCPU node is around 190 USD a month |
| Four static public IPs | 0.005 USD an hour each, **about 14.60 USD in total** |
| Disks | 33Gi of managed disk, a few USD a month |

---

## Step 0. Point kubectl at the cluster

```bash
az login
az aks get-credentials --resource-group <group> --name <cluster>
```

You need the resource group as well as the cluster name, and the two are easy to lose track of on
a subscription you do not own. `az aks list -o table` prints both.

Confirm you are talking to the right cluster before you change anything in it:

```bash
kubectl config current-context
kubectl version
kubectl get nodes -o wide
```

---

## Step 1. Check the ground before you build on it

AKS gives you both of the things a cluster needs here, so this step is a check rather than a
change. Run it anyway: each command answers something that otherwise surfaces several steps later
looking like a different problem.

```bash
kubectl get storageclass
kubectl get ns onibex-ask
kubectl describe node <node> | sed -n '/Allocated resources/,/Events/p'
```

**`get storageclass` must show `(default)` next to one of them**, normally `managed-csi`. Every
`storageClassName` in the values file is deliberately empty, which means "use the cluster default",
so a cluster without one leaves all four volumes `Pending` forever with nothing naming the cause.

**`get ns` because an existing namespace changes what the next step prints.**

**And the node line because a pod is scheduled to a single node**, so the platform has to fit on
one, not across the cluster. `kubectl top` does not answer this question: it reports usage, and a
node can be nearly idle with nothing left to reserve. The per-service breakdown is in
[Capacity, per service](kubernetes-reference.md#capacity-per-service).

> **On a shared cluster, read the numbers before you install and again before you change anything.**
> `values-aks-dev.yaml` exists because the node it was written for had eighteen millicores free. Its
> requests are small for that reason and not because ASK is smaller on Azure.

---

<!-- shared:secret start -->
## Create the namespace and the Secret

**Five values** cannot live in the chart: four because they are needed before the store that
holds everything else can be read, and one because it is how two services authenticate to each
other.

```bash
kubectl create namespace onibex-ask
```

`AlreadyExists` here is benign if the namespace is empty, which
`kubectl -n onibex-ask get all` will tell you. It is a leftover from a previous install, and
[Uninstall, and what survives](kubernetes-reference.md#uninstall-and-what-survives) says how to
clear it properly. Run the Secret as its own command so a namespace that already exists does not
look like the Secret failing:

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
<!-- shared:secret end -->

---

## Step 3. Decide the addresses people will use

Settle this before installing, because the realm in the next step is built from the answer.

### The free Azure names, which is what `values-aks-dev.yaml` is set up for

AKS gives every public IP a DNS name of the form `<label>.<region>.cloudapp.azure.com` when the
Service carries `service.beta.kubernetes.io/azure-dns-label-name`. That is a real public name, so
**Let's Encrypt issues for it** and no domain of your own is needed. The name also survives the IP
changing, which is what matters once anything points at it.

Edit the four labels in the `gateway.hosts` and `gateway.service.perHostAnnotations` blocks of
`values-aks-dev.yaml`. **A label has to be unique across the whole region**, not just your
subscription, because the zone is shared by every Azure customer. A taken label leaves the Service
without an address and says so only in its events, so check before committing to one:

```bash
nslookup <label>.<region>.cloudapp.azure.com 2>&1 | grep -q "Non-existent domain" && echo free || echo TAKEN
```

Grep the message rather than testing the exit code. **`nslookup` exits 0 even for a name that does
not exist**, so an exit-code test reports every label as taken.

### If you have a domain of your own

The production case. The free Azure names above already give you trusted certificates, so a domain
here buys readability and permanence rather than removing a warning.

<!-- shared:domain start -->
A domain is what removes the browser warning. It also gives people names they can read, and names
that survive the address behind them being replaced. Six things are needed and none of them are
ASK:

1. **A domain you control**, with access to edit its DNS records.
2. **Four names**, one per app plus one for the login: for example `ask`, `chat`, `setup` and
   `auth` under your domain. They cannot share one. The three apps are built to be served from the
   root and collide on `/api`, `/assets` and the login callback.
3. **Port 80 reachable from the internet.** It is where the certificate authority checks the domain
   is yours, at issue and again at every renewal. Closing it breaks nothing today; it makes the
   certificate expire quietly ninety days later.
4. **No `CAA` record that excludes Let's Encrypt.** Corporate domains often carry them, and they
   block issuance without explaining why. `dig CAA yourdomain.com` shows them; the authority has to
   be allowed by name.
5. **An address for expiry warnings**, in `gateway.tls.email`. Renewal is the only thing keeping
   these certificates alive and that address is the only notice anyone gets if it stops. Use a team
   alias, not a person.
6. **The records resolving BEFORE the gateway starts with those names.** A certificate is issued by
   answering a challenge at the name itself, so in the other order nothing errors loudly: the
   certificate is simply never issued and the site keeps answering on plain http.

Then it is five values: the four `gateway.hosts`, `auth.publicUrl`, the three `publicUrls`,
`gateway.tls.mode: acme` and `gateway.tls.email`. Nothing else, and nothing from the cloud: no
managed certificate service, no second ingress controller, no cert-manager.

**If you already have a certificate, use it instead of asking for one.** Set
`gateway.tls.mode: existing` and put it in a Secret, which covers an organisation with its own
authority, a wildcard already paid for, or a policy against letting an internal service reach a
public authority at all:

```bash
kubectl -n onibex-ask create secret tls ask-gateway-tls \
  --cert=fullchain.pem --key=privkey.pem
```

Then `gateway.tls.existingSecret: ask-gateway-tls` and none of points 3, 4 or 5 above apply: port
80 is not used, `CAA` records are irrelevant, and there is no authority to email. **Points 1 and 2
still do, and two more take their place:**

- **`--cert` must be the FULL CHAIN**, leaf plus intermediates, not the leaf alone. Measured, not
  assumed: with the leaf alone, a client holding only the root fails with `unable to verify the
  first certificate` while a client that already cached the intermediate says `OK`. The person who
  tested it is usually the second kind, which is why this ships and then fails on everyone else's
  machine.
- **Renewal becomes a human's job.** `acme` renews every sixty days on its own; this mode renews
  never, and when the certificate expires the site goes untrusted for everyone at once with no
  warning sent to anybody. Replacing it needs a `kubectl rollout restart` of the gateway as well as
  a new Secret: Caddy reads the files when it loads its config.

And on point 2, the question to settle before promising anything: **an internal corporate authority
is trusted on the machines where IT installed it and nowhere else.** Staff see no warning, anyone
from outside sees one.
<!-- shared:domain end -->

**On AKS the records are `A` records, one per app, each pointing at its own address.** Unlike a
load balancer hostname on AWS, a `LoadBalancer` Service here yields a static IP, so there is a real
address to put in the record. There are four of them: the chart renders one Service per published
hostname, and they share the cluster's single Azure load balancer but not their IPs.

So the order is:

1. Install with `gateway.enabled=true` and read the addresses Azure assigned:
   `kubectl -n onibex-ask get svc`.
2. Create four `A` records, each pointing at **its own app's** `EXTERNAL-IP`.
3. Wait until all four resolve from outside the cluster.
4. Put the four names in `gateway.hosts`, `auth.publicUrl` and `publicUrls`, **remove the
   `azure-dns-label-name` annotations** (they are only for the free Azure names), and upgrade.

The certificates arrive within a minute or two of the gateway restarting with names that already
resolve.

### Or no public address at all

Install with `gateway.enabled=false` and forward the ports to your own machine. Good for a first
look and for a cluster with no load balancer. The realm step still needs addresses: use the
`localhost` ones below.

```bash
kubectl -n onibex-ask port-forward svc/ask-studio 5173:80
kubectl -n onibex-ask port-forward svc/ask-chat 5174:80
kubectl -n onibex-ask port-forward svc/ask-setup 5175:80
kubectl -n onibex-ask port-forward svc/ask-onibex-ask-keycloak 8180:8080
```

> **Why there is no third option.** A plain `http://<ip>` address does not work, and not for
> security reasons. The three apps sign in with PKCE and call `crypto.subtle`, which browsers
> expose only in a secure context: `https`, or `localhost`. On plain http the sign-in button
> throws and nothing happens. That is a browser rule, not a setting. The port-forward option works
> precisely because `localhost` is on that list.

---

<!-- shared:realm start -->
## Build the realm for those addresses

The realm committed in this repository is a local demo. Its users carry a password published on
GitHub, and its redirect URIs list `localhost` ports. Deploying it unchanged puts that password on
whatever address the platform answers on, and the sign-in stops with `Invalid parameter:
redirect_uri` after the user has already typed it.

Generate one for your addresses instead, using the three app addresses you now have.

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

The Keycloak administrator is separate: its password comes from the Secret, and the realm file
does not cover it. Give it the same treatment by hand, once, after the platform is up:

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"requiredActions":["UPDATE_PASSWORD"]}' \
  "$AUTH/admin/realms/master/users/$ADMIN_ID"
```
<!-- shared:realm end -->

---

## Step 5. Install

```bash
helm install ask deploy/helm/onibex-ask \
  --namespace onibex-ask \
  --values deploy/helm/onibex-ask/values-aks-dev.yaml \
  --set auth.publicUrl=https://auth.example.com \
  --set keycloak.realmImportSecret=ask-realm
```

`auth.publicUrl` is the origin the **browser** uses to reach Keycloak, and it is also the issuer
stamped into every token. An in-cluster Service name will not do: the OAuth exchange happens in the
browser. It has to match the Keycloak hostname from Step 3 exactly, and the chart refuses to install
if it does not.

**`keycloak.realmImportSecret` is not optional and it cannot be added afterwards.** A realm is
imported on a **first** boot only. Install without it and Keycloak writes an empty datastore to its
volume; setting the value later changes nothing, the file is mounted and ignored, and every sign-in
returns `Realm does not exist` while the pod reports perfectly healthy.

**Render it first.** The chart checks eight values before producing anything, so the same command
with `template` in place of `install` turns eight possible failures into a two-second check that
never touches the cluster:

```bash
helm template ask deploy/helm/onibex-ask \
  --values deploy/helm/onibex-ask/values-aks-dev.yaml \
  --set auth.publicUrl=https://auth.example.com \
  --set keycloak.realmImportSecret=ask-realm \
  --set secrets.existingSecret=ask-platform-secret > /dev/null
```

Silence means it rendered. Anything else is one of the refusals below, quoted in full.

The chart refuses to render rather than producing something half-working. Each refusal names the
value and says what goes wrong if it is guessed:

| If this is wrong | Why the chart stops |
|---|---|
| `auth.publicUrl` empty, or not the gateway's Keycloak host | A login page pointing at a host that does not exist, with nothing reporting it |
| No secret source | The backends refuse to boot without the encryption key anyway; failing here is faster to read |
| `auth.mode` not `keycloak` or `xsuaa` | Anything else matches no branch and every request is rejected while the pods report healthy |
| `platform.environment` not `local` or `production` | A reasonable-looking `development` crash-loops the admin API forty lines into a pydantic error |
| `keycloak.database.host` empty while production is on | Production mode without a database is a contradiction |
| `image.namespace` cleared | It has a default, so this only fires if you empty it deliberately |
| `adminApi.replicas` above 1 | Two pods against one git checkout of the semantic layer overwrite each other |

---

<!-- shared:watch start -->
## Watch it come up

```bash
kubectl -n onibex-ask get pods -w
```

Three things start in order, and knowing it saves you from chasing a pod that is only waiting:

1. **OpenSearch** must be Ready before either backend finishes its own boot.
2. **The apps** start independently. They serve a bundle and wait for nothing.
3. **The MCP server waits for something this runbook does not provide**, and the next part is
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
this part is done. Come back to this pod after
[Register an OpenAPI contract](../ask-setup/07-contracts.md), and only then treat `0/1` as a
problem.

| Status | What it means |
|---|---|
| `0/1 Running` on the MCP server, **0 restarts**, no contracts saved yet | The expected end state of a clean install. Leave it |
| `0/1 Running` on the MCP server, contracts saved | Now it is worth reading: the admin API is unreachable from it, or the ingest key does not match |
| `0/1 Running` with the **restart count climbing** | Not the wait. A waiting MCP server does not restart, because it has no liveness probe for exactly this reason. Read the log |
| `CrashLoopBackOff` anywhere | A defect. The container died; waiting will not fix it. Read the log of the run that failed |

The restart column is the one to watch. Unready and patient looks almost identical to unready and
being killed, and the number is the only thing that separates them at a glance.

```bash
kubectl -n onibex-ask logs <pod> --previous
```

`--previous` matters: without it you read the container that is about to die rather than the one
that already did, and on a fast crash loop you often get nothing at all.

If something is stuck,
[the failures worth knowing in advance](kubernetes-reference.md#the-failures-worth-knowing-in-advance)
covers the ones that have actually happened.
<!-- shared:watch end -->

---

## Step 7. Check the public path before you involve a person

Substitute your own four hostnames.

```bash
for h in <studio host> <chat host> <setup host> <auth host>; do
  printf '%-60s %s\n' "$h" "$(curl -s -o /dev/null -w '%{http_code}' "https://$h/")"
done
```

`200` from the three apps and `302` from Keycloak. No `-k` here, unlike the EKS page: on AKS these
are real Let's Encrypt certificates and a TLS error is a finding rather than noise.

Then the two that catch the mistakes this runbook exists to prevent:

```bash
curl -s "https://<auth host>/realms/ask-platform/.well-known/openid-configuration" \
  | python -c "import sys,json; print(json.load(sys.stdin)['issuer'])"
```

It must print your `auth.publicUrl` followed by `/realms/ask-platform`, character for character.
`Realm does not exist` here means Keycloak booted once before the realm Secret existed; see
[the failures](kubernetes-reference.md#the-failures-worth-knowing-in-advance).

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  "https://<auth host>/realms/ask-platform/protocol/openid-connect/auth?client_id=ask-studio&redirect_uri=https%3A%2F%2F<studio host>%2Flogin%2Fcallback&response_type=code&scope=openid&state=probe"
```

`302` means the realm accepts the address Studio is served from. `400` means it does not, and every
sign-in will stop after the password has been typed. Rebuild the realm with the right `--host`
values rather than debugging the browser.

**And then the one that matters most, because the three above can all pass while the platform is
unusable.** Everything so far tests the sign-in redirect chain, which is the browser talking to
Keycloak. It says nothing about whether the **backends** accept the token that comes out of it, and
that is a different path with its own way of failing: the apps load, the login completes, and then
every screen reports `Token validation failed: no configured issuer accepted the token`.

Take a token and make a real call. The realm's `kafka-ingest` client has a service account, so this
needs no person and no browser. Its secret is one of the three the realm step printed:

```bash
TOKEN=$(curl -s -d client_id=kafka-ingest -d client_secret=<the one from the realm step> \
  -d grant_type=client_credentials \
  "https://<auth host>/realms/ask-platform/protocol/openid-connect/token" \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

kubectl -n onibex-ask port-forward deploy/ask-onibex-ask-admin-api 18081:8081 &
curl -s -w '\n%{http_code}\n' -H "Authorization: Bearer $TOKEN" http://127.0.0.1:18081/v1/admin/config
```

`200` with a JSON body is the platform working. `401` here, with a token Keycloak just issued, is
the failure described under
[the failures worth knowing in advance](kubernetes-reference.md#the-failures-worth-knowing-in-advance).
It is less likely on AKS, where the gateway's certificate comes from Let's Encrypt and every pod
trusts it already, which is exactly why it went unnoticed until the same chart met a self-signed
one.

---

<!-- shared:signin start -->
## Sign in, and change the passwords

Open ASK Setup at its address and sign in with the initial password from the realm step. Keycloak
asks for a new one immediately; that is the shared value retiring.

From there the platform is empty and
[Configure the platform first · ASK Setup](../ask-setup/README.md) takes over: the database, the
model provider, then the semantic layer in ASK Studio.

**And this is where the ninth pod comes up.** Registering your first contract on the
[Register an OpenAPI contract](../ask-setup/07-contracts.md) page gives the MCP server the thing it
has been waiting for. It picks them up within a minute and goes Ready on its own, with no restart.
If you are not using SAP actions at all, leave it unready or install with `mcpServer.enabled=false`.
<!-- shared:signin end -->

> **Leave port 80 open even when everything is served over 443.** It is where Let's Encrypt answers
> the challenge, at issue and again at every renewal. Close it and the certificate expires quietly
> ninety days later.

---

## When you are done with it

[Uninstall, and what survives](kubernetes-reference.md#uninstall-and-what-survives) covers it. Wait
for the Services to disappear rather than assuming they did: that is the four public IPs being
released, and it is the billing stopping.

**Keep the gateway volume if you are going to reinstall.** It holds the Let's Encrypt certificates,
and Let's Encrypt allows only five duplicate certificates per week for the same set of names, so a
few teardowns in one afternoon can lock the environment out until the window rolls over.

---

[← Back to the manual](../README.md) · [Kubernetes reference](kubernetes-reference.md) · [Deploy ASK on AWS EKS](kubernetes-deploy-aws-eks.md)
