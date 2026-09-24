# Deploy ASK on SAP BTP Kyma

[Manual](../README.md) › [Operating the platform](../README.md#operating-the-platform) › **Deploy ASK on SAP BTP Kyma**

> **How to.** Install the whole platform on an SAP BTP Kyma cluster from one Helm chart, using the
> images Onibex publishes. Read top to bottom and run every command; there are no branches.
> **Shell:** bash. On Windows use Git Bash, and see
> [On Windows and PowerShell](kubernetes-reference.md#on-windows-and-powershell).

| | |
|---|---|
| **Who** | Whoever can sign in to the SAP BTP subaccount the Kyma environment belongs to, with a role on the cluster |
| **Time** | About 30 minutes, most of it waiting for images to pull |
| **You'll end with** | Eight of the nine services Ready, the three apps open in a browser on public HTTPS addresses under the cluster's own certificate, a working sign-in, no load balancer at all, and the MCP server deliberately unready until you register a contract |

**On another cloud?** [Deploy ASK on AWS EKS](kubernetes-deploy-aws-eks.md) and
[Deploy ASK on Azure AKS](kubernetes-deploy-azure-aks.md) have their own pages, because getting the
cluster ready is genuinely different on each. Everything that is the same on every cloud is in the
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
`onibexenjoy`, all public, and `values-kyma-dev.yaml` points at them. Kubernetes pulls; nothing is
compiled here. (If you do need your own build, see
[Running images you built yourself](kubernetes-reference.md#running-images-you-built-yourself).)

| Tool | Version | Used for |
|---|---|---|
| `kubectl` | Within one minor of the cluster, either way. The cluster this page was verified on runs 1.35, so a client older than 1.34 fails the skew. Check with `kubectl version` | Everything |
| `kubectl-oidc_login` | any | Signing in. The Kyma kubeconfig authenticates through a browser, and `kubectl` hands that to this plugin. See Step 0 |
| `helm` | 3 or later | Installing the chart |
| `python` | 3.10 or later | The realm file. **On most Linux boxes the command is `python3`**, and plain `python` does not exist: Amazon Linux 2023 and Ubuntu both ship it that way. Substitute it everywhere below, or install the alias package. Nothing here needs a library outside the standard one |
| `openssl` | any | Generating passwords. On Windows it ships with Git for Windows |
| `curl` | any | The checks at the end. **Not PowerShell 5.1's `curl`**, which is an alias for `Invoke-WebRequest` |

> **Check them in the shell you are actually going to use.** Git Bash and PowerShell read different
> PATHs on Windows, so a tool installed into `~/bin` from Git Bash is invisible to PowerShell, and
> Docker Desktop ships its own `kubectl` early in the Windows system PATH and will answer instead of
> the one you installed.
>
> ```bash
> which kubectl kubectl-oidc_login helm python openssl curl
> ```

### What this costs while it runs

| | |
|---|---|
| The Kyma environment | Billed through the subaccount's SAP BTP entitlement, not by anything on this page. Whoever holds the subaccount knows the figure |
| Load balancers | **None.** The four addresses ride the cluster's shared Istio gateway, which exists whether ASK is installed or not. On EKS the same four addresses cost about 73 USD a month |
| Volumes | 32Gi of block storage across three volumes. There is no fourth: the gateway volume that holds certificates on the other clouds does not exist here |

---

## Step 0. Point kubectl at the cluster

There is no cloud CLI that writes the kubeconfig, as `az` and `aws` do. **You download it:** in the
SAP BTP cockpit, open the subaccount, find the Kyma environment, and download the file behind
**KubeconfigURL**.

**Save it as its own file, and do not copy it over `~/.kube/config`.** SAP's own instructions say to,
and doing so deletes every other cluster you already had a context for.

```bash
mv ~/Downloads/kubeconfig.yaml ~/.kube/kyma.yaml
export KUBECONFIG=~/.kube/kyma.yaml
```

That kubeconfig signs in through a browser rather than carrying a credential, which is why `kubectl`
needs a plugin to do it. Download `kubelogin` for your platform from its
[releases page](https://github.com/int128/kubelogin/releases) and put it on your PATH.
**On Windows, rename `kubelogin.exe` to `kubectl-oidc_login.exe`.** The kubeconfig calls it by that
name, and under the original one `kubectl` does not find it and says only that the plugin is
missing.

Confirm you are talking to the right cluster before you change anything in it:

```bash
kubectl config current-context
kubectl version
kubectl get nodes -o wide
```

**The first command that reaches the cluster opens a browser, and your company's own sign-in page
there is correct**, Microsoft's for example, rather than an SAP one. Kyma signs you in through SAP
Cloud Identity Services, which usually hands on to the company's directory rather than holding
passwords itself. The callback listens on port 8000,
so that port has to be free. The token lasts an hour and renews by itself; the browser opens again
only when the renewal expires too.

Then check that the account you signed in with can act on the cluster, because a role on the
subaccount is not a role on the cluster:

```bash
kubectl auth whoami
kubectl auth can-i '*' '*' --all-namespaces
```

The second must say `yes`. Without a role, every command is refused as `Forbidden`, which reads
like a connection problem and is not one.

---

## Step 1. Check the ground before you build on it

A Kyma cluster arrives with everything this chart needs, so this step is a check rather than a
change. Each command answers something that otherwise surfaces several steps later looking like a
different problem.

```bash
kubectl get storageclass
kubectl get gateway -n kyma-system kyma-gateway -o jsonpath='{.spec.servers[*].hosts}'; echo
kubectl get peerauthentication -A
kubectl get ns onibex-ask
```

**`get storageclass` must show `(default)` next to one of them.** Every `storageClassName` in the
values file is deliberately empty, which means "use the cluster default", so a cluster without one
leaves every volume `Pending` forever with nothing naming the cause. Kyma has one; a stock EKS does
not, which is why that page has an extra step here.

**The gateway line prints a wildcard, `*.<cluster domain>`, and every address in Step 3 hangs from
it.** Write the domain down. It differs on every cluster and cannot be guessed.

**`get peerauthentication` shows whether the mesh demands mutual TLS.** On the cluster this page was
verified on it read `STRICT` in `istio-system`, which applies to the whole cluster, and that is what
makes Step 3a necessary rather than advisable.

**`get ns` because an existing namespace changes what the next step prints.**

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
  --from-literal=encryption-key="$(openssl rand -base64 32 | tr '+/' '-_')" \
  --from-literal=opensearch-user=admin \
  --from-literal=opensearch-password="$(openssl rand -base64 24)" \
  --from-literal=keycloak-admin-password="$(openssl rand -base64 24)" \
  --from-literal=ingest-api-key="$(openssl rand -hex 32)"
```

> **The encryption key is generated with `openssl` rather than Python on purpose.** A Fernet key is
> nothing more than url-safe base64 of 32 random bytes, which is what that line produces: 44
> characters, and `Fernet()` accepts it. The obvious alternative,
> `python -c 'from cryptography.fernet import Fernet; ...'`, needs `cryptography`, which is **not**
> in Python's standard library and is not on a fresh cloud box, so it fails with
> `ModuleNotFoundError` at the one step whose output you cannot inspect afterwards. Use it if you
> prefer and already have the package; the two produce the same thing.

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

## Step 3. Put the namespace in the mesh, and fix the addresses

### 3a. The mesh, before anything is installed

```bash
kubectl label namespace onibex-ask istio-injection=enabled
```

**Not optional, and it has to happen now, before the install.** Kyma publishes a Service through an
`APIRule`, and the operator behind it refuses any target pod without an Istio sidecar. The symptom
is four `APIRule`s in `Error` naming `does not have an injected istio sidecar`, while every pod looks
healthy. A sidecar is added when a pod is created, so labelling the namespace after the install
changes nothing until every pod is restarted.

**The whole namespace, not a chosen few pods.** With mutual TLS set to `STRICT`, a pod outside the
mesh cannot talk to one inside it, so leaving some out breaks the traffic between them.

From here on every pod runs two containers, the application and its sidecar, so `READY` reads
`2/2` on this page where the other clouds read `1/1`.

### 3b. The addresses

Four names, one per app plus one for the login, **all directly under the wildcard** from Step 1:

| For | Address |
|---|---|
| ASK Studio | `ask-studio.<cluster domain>` |
| ASK Chat | `ask-chat.<cluster domain>` |
| ASK Setup | `ask-setup.<cluster domain>` |
| Sign-in (Keycloak) | `ask-auth.<cluster domain>` |

**Directly under means one label deep.** The wildcard certificate covers exactly one level:
`ask-studio.<cluster domain>` is covered and `ask.studio.<cluster domain>` is not, and a browser
refuses the second outright with a certificate for the wrong name.

**Nothing to buy, nothing to issue, nothing to renew.** The certificate is the one the cluster's
gateway already holds. On the cluster this page was verified on it was a Let's Encrypt wildcard, sent
with its full chain and verified against the system trust store with no authority supplied.

`values-kyma-dev.yaml` carries the domain of the cluster it was verified on, in eight values: the
four `gateway.hosts`, `auth.publicUrl` and the three `publicUrls`. Put yours in all eight at once:

```bash
sed -i 's/ff90b8d\.kyma\.ondemand\.com/<cluster domain>/g' deploy/helm/onibex-ask/values-kyma-dev.yaml
grep -c '<cluster domain>' deploy/helm/onibex-ask/values-kyma-dev.yaml
```

The count must be at least eight. A lower one means an address still points at a cluster that is not
yours.

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

## Step 5. Install, in one pass

```bash
helm install ask deploy/helm/onibex-ask \
  --namespace onibex-ask \
  --values deploy/helm/onibex-ask/values-kyma-dev.yaml
```

**One pass, and that is a Kyma advantage.** EKS needs two because its addresses do not exist until
the load balancers do. Here they are names under a wildcard that exists already, so they are known
before anything is installed, and Keycloak's first boot happens once, with the realm in place.

**The realm is already named, and it cannot be added afterwards.** `values-kyma-dev.yaml` sets
`keycloak.realmImportSecret: ask-realm`, the Secret the realm step created. A realm is imported on a
**first** boot only: had Keycloak ever started without it, it would have written an empty datastore
to its volume, and every sign-in would return `Realm does not exist` while the pod reports healthy.

**Render it first.** The chart checks its values before producing anything, so the same command
with `template` in place of `install` turns every refusal into a two-second check that never
touches the cluster:

```bash
helm template ask deploy/helm/onibex-ask \
  --values deploy/helm/onibex-ask/values-kyma-dev.yaml > /dev/null
```

Silence means it rendered. Two of the refusals exist only for Kyma:

| If this is wrong | Why the chart stops |
|---|---|
| `kyma.enabled` and `gateway.enabled` both true | They publish the same four names by two routes, through two certificates, and only one of them answers the name in DNS |
| `kyma.enabled` with every address empty | The install would report success and publish nothing at all |

**No load balancer is created.** The install ends with four `APIRule`s, which Kyma turns into routes
on its shared gateway, and the closing notes print the four addresses.

---

## Watch it come up

```bash
kubectl -n onibex-ask get pods -w
kubectl -n onibex-ask get apirules
```

**Every `APIRule` must read `Ready`.** One in `Error` names its reason, and the one worth knowing in
advance is `does not have an injected istio sidecar`: Step 3a was skipped, or came after the pods
were created. Label the namespace and recreate them:

```bash
kubectl label namespace onibex-ask istio-injection=enabled
kubectl -n onibex-ask rollout restart deployment
kubectl -n onibex-ask rollout restart statefulset
```

Three things start in order, and knowing it saves you from chasing a pod that is only waiting:

1. **OpenSearch** must be Ready before either backend finishes its own boot.
2. **The apps** start independently. They serve a bundle and wait for nothing.
3. **The MCP server waits for something this runbook does not provide**, and the next part is about
   that.

### A clean install finishes at eight of nine, and the ninth reads `1/2`

**The MCP server stays `1/2 Running` and it never leaves on its own.** Its sidecar is ready; the
server itself is not. It fetches its API contracts from the admin API at boot, there are none stored
until somebody saves them on the Contracts page in ASK Setup, and it will not start with zero tools,
because a server that advertises nothing is worse than one that is honestly unready. So it retries,
with the wait doubling each time, until the contracts exist.

**So the expected end state here is eight pods at `2/2` and the MCP server at `1/2`.** Come back to
it after [Register an OpenAPI contract](../ask-setup/07-contracts.md); it goes to `2/2` within a
minute of contracts being saved, with no restart.

| Status | What it means |
|---|---|
| `1/2 Running` on the MCP server, **0 restarts**, no contracts saved yet | The expected end state of a clean install. Leave it |
| `1/2 Running` on the MCP server, contracts saved | Now it is worth reading: the admin API is unreachable from it, or the ingest key does not match |
| `1/2` with the **restart count climbing** | Not the wait. A waiting MCP server does not restart, because it has no liveness probe for exactly this reason. Read the log |
| `1/1` anywhere | That pod has no sidecar. Step 3a came after it was created; restart it |
| `CrashLoopBackOff` anywhere | A defect. The container died; waiting will not fix it. Read the log of the run that failed |

The restart column is the one to watch. Unready and patient looks almost identical to unready and
being killed, and the number is the only thing that separates them at a glance.

```bash
kubectl -n onibex-ask logs <pod> -c <container> --previous
```

With two containers per pod, `-c` names the one you mean: the application's container carries the
service's name, and the sidecar is `istio-proxy`. `--previous` reads the container that already
died rather than the one about to.

---

## Step 7. Check the public path before you involve a person

Substitute your own four addresses.

```bash
for h in <studio host> <chat host> <setup host> <auth host>; do
  printf '%-60s %s\n' "$h" "$(curl -s -o /dev/null -w '%{http_code}' "https://$h/")"
done
```

`200` from the three apps and `302` from Keycloak. No `-k`: the certificate is real, and a TLS error
is a finding rather than noise.

Then the two that catch the mistakes the realm step exists to prevent:

```bash
curl -s "https://<auth host>/realms/ask-platform/.well-known/openid-configuration" \
  | python -c "import sys,json; print(json.load(sys.stdin)['issuer'])"
```

It must print your `auth.publicUrl` followed by `/realms/ask-platform`, character for character.

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  "https://<auth host>/realms/ask-platform/protocol/openid-connect/auth?client_id=ask-studio&redirect_uri=https%3A%2F%2F<studio host>%2Flogin%2Fcallback&response_type=code&scope=openid&state=probe"
```

`302` means the realm accepts the address Studio is served from. `400` means it does not, and every
sign-in will stop after the password has been typed. Rebuild the realm with the right `--host`
values rather than debugging the browser.

**Then two that only Kyma needs, because each one found a real failure here that no other cloud
showed.**

**The sign-in's cross-origin check.** After the password, the browser exchanges a code for a token
by calling Keycloak from the app's own address, and it only does so if Keycloak's answer names that
address:

```bash
curl -s -i -X OPTIONS "https://<auth host>/realms/ask-platform/protocol/openid-connect/token" \
  -H "Origin: https://<studio host>" -H "Access-Control-Request-Method: POST" \
  | grep -i '^access-control-allow-origin'
```

It must print `https://<studio host>`. **Nothing printed is the failure, not a quiet success.** An
`APIRule` with no CORS policy removes those headers from the response rather than passing them on,
so Keycloak answers correctly and the gateway strips the answer. What a person sees is the password
change and the redirect both working, and then *Authentication error · Failed to fetch*, which reads
like the identity provider being down. The chart sets the policy on the sign-in address; this check
is how you know it arrived.

**An API call through an app:**

```bash
curl -s -o /dev/null -w '%{http_code}\n' "https://<studio host>/api/admin/config"
```

`401` is correct: the call carries no token. **`503` is the failure**, with a body reading
`upstream connect error or disconnect/reset before headers. reset reason: connection termination`.
It means the app is running images older than the ones `values-kyma-dev.yaml` names, whose nginx
forwarded the browser's hostname to the backend; inside a service mesh that matches no route. The
app loads normally and every call it makes fails, which looks like the backend being down.

**Test that exact path.** A path the app does not proxy answers `200`, because it falls back to the
app's own page, and that `200` reads like success while proving nothing.

**And then the one that matters most, because everything above can pass while the platform is
unusable.** It all tests the path to the browser. None of it tests whether the **backends** accept
the token that comes out of a sign-in, and that is a different path with its own way of failing: the
apps load, the sign-in completes, and then every screen reports
`Token validation failed: no configured issuer accepted the token`.

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

`200` with a JSON body is the platform working. `401` here, with a token Keycloak just issued, has
a cause particular to Kyma, and the admin API's log names it as a `403` while fetching the signing
keys:

```bash
kubectl -n onibex-ask logs deploy/ask-onibex-ask-admin-api -c admin-api --tail=40 | grep -i jwks
```

**Publishing a Service with an `APIRule` closes it from the inside.** The operator writes an
authorization policy that admits only the ingress gateway, so the backends, which fetch Keycloak's
keys over the cluster network, are refused by the mesh before Keycloak sees them. The chart ships a
second, narrow policy that lets them read exactly the keys and the discovery document and nothing
else. If this check fails, confirm it exists:

```bash
kubectl -n onibex-ask get authorizationpolicy
```

One of them must end in `-keycloak-internal`.

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

> **This page signs people in with the Keycloak the chart deploys.** To sign them in with the
> customer's own SAP identity instead, follow
> [Sign in with SAP Cloud Identity Services](sign-in-with-ias.md) once this page is done. It switches
> the installed platform with one more values file, and going back is dropping it. **Do not switch
> `auth.mode` to `xsuaa` to get there.** The apps cannot sign in against XSUAA directly: measured
> against a real instance, it refuses the token exchange for want of a client secret, and a browser
> can never hold one. The chart refuses the value for that reason.

---

## When you are done with it

[Uninstall, and what survives](kubernetes-reference.md#uninstall-and-what-survives) covers it.
There is no load balancer to wait for here, so nothing keeps billing once the release is gone except
the three volumes, which the chart keeps on purpose.

**Nothing cluster-wide was changed.** The only thing outside the release is the namespace label from
Step 3a, and it goes when the namespace does.

---

[← Back to the manual](../README.md) · [Kubernetes reference](kubernetes-reference.md) · [Deploy ASK on AWS EKS](kubernetes-deploy-aws-eks.md) · [Deploy ASK on Azure AKS](kubernetes-deploy-azure-aks.md)
