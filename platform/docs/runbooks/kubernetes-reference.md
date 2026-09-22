# Kubernetes reference: the chart, the failures, and the teardown

[Manual](../README.md) › [Operating the platform](../README.md#operating-the-platform) › **Kubernetes reference**

> **Reference.** Everything about running ASK on Kubernetes that does not depend on which cloud you
> are on. Nothing here is a step. You do not read this page to install; you read it when the
> install stops, when you want your own images, or when you are taking the environment down.

**The steps live elsewhere, one page per cloud**, because the parts that differ are the first two
steps and nothing else:

| Your cluster | Follow |
|---|---|
| Amazon EKS | [Deploy ASK on AWS EKS](kubernetes-deploy-aws-eks.md) |
| Azure AKS | [Deploy ASK on Azure AKS](kubernetes-deploy-azure-aks.md) |
| SAP BTP Kyma | Not written yet. See [What is not done yet](#what-is-not-done-yet) |

---

## What this chart is, and what it deliberately is not

One chart renders every service the compose file runs: the two Python backends, the three
single-page apps, OpenSearch, Keycloak, and the two opt-in services.

**It names no cloud.** No storage class, no load balancer, no provider annotation in the chart
itself. That is not an omission, it is the design: those differ per target, and keeping them in a
values file is what lets the same chart serve AKS, EKS and Kyma. It is also why each cloud gets its
own runbook rather than its own branch inside one.

**Each app needs its own hostname, and no router can change that.** The three apps are built to be
served from the root: the API client asks for `/api`, the bundle asks for `/assets`, and the login
returns to `<origin>/login/callback` with the path discarded. Under one shared hostname all three
collide in all three places, and an Ingress cannot fix it from outside, because those addresses are
compiled into the JavaScript. Serving one hostname with paths is possible, but it is image work,
not chart work.

**Four hostnames mean four load balancers today, and a domain does not change that.** The gateway
is a single Caddy that tells the hostnames apart by the `Host` header, so in principle four DNS
names could point at one address. They do not, because **the chart renders one Service per
published hostname**, and each Service is what makes a cloud allocate an address. That shape came
from the no-domain case, where a cloud-assigned name belongs to one load balancer and there is no
choice. Collapsing them onto one is a chart change rather than a values change, and until it
happens, owning the domain removes the browser warning without removing the bill.

**A realm is imported only on a first boot.** Once `keycloak.persistence` is on, the file is
ignored on every later start and changes belong in the admin console. To re-import, scale Keycloak
to zero, delete its PersistentVolumeClaim, and let the chart recreate it. That is also the only way
to change the administrator password from the Secret, because Keycloak creates that user once and
never revisits the variable.

---

## Capacity, per service

The requests below are what the scheduler reserves. **`kubectl top` does not answer this
question**: it reports usage, and a node can be nearly idle and still have nothing left to give.

| Profile | CPU requests | Memory requests | Written for |
|---|---|---|---|
| `values.yaml`, chart defaults | 775m | 3008Mi | Nothing in particular. A starting point |
| `values-aks-dev.yaml` | 510m | 3200Mi | A shared node with almost nothing left |
| `values-eks-dev.yaml` | 2200m | 5476Mi | A dedicated four-vCPU node |

The two profiles are the same platform. The AKS one is small because the node it was measured on
had 18 millicores free, not because ASK is smaller on Azure. Read the header of either file before
copying its numbers anywhere.

Per service, so you can see where it goes and what disabling something buys you:

| Service | CPU | Memory |
|---|---|---|
| OpenSearch | 250m default, 100m on AKS, 500m on EKS | 1536Mi to 2Gi |
| Orchestrator | 250m default, 150m on AKS, 300m on EKS | 512Mi to 768Mi |
| Admin API | 100m default, 200m on EKS | 256Mi to 512Mi |
| Keycloak | 100m default, 50m on AKS, 200m on EKS | 256Mi to 768Mi |
| Studio, Chat, Setup | 25m each, 50m on EKS | 64Mi each |
| MCP server | 50m default, 10m on AKS, 100m on EKS | 128Mi |
| Gateway | 25m, 50m on EKS | 64Mi |

It has to fit **on one node**, not across the cluster, because a pod is scheduled to a single
node. Read what is left with:

```bash
kubectl describe node <node> | sed -n '/Allocated resources/,/Events/p'
```

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

**Every login fails with `Realm does not exist`, and the pod looks perfectly healthy.** The realm
was never imported, and it will not be imported now. A realm is read on a **first** boot only, so
installing without `keycloak.realmImportSecret` writes an empty datastore to the Keycloak volume,
and setting the value afterwards changes nothing: the file is mounted and ignored. Nothing logs an
error, because from Keycloak's side nothing went wrong. Build the realm **before** you install.
Recovering means throwing the volume away:

```bash
kubectl -n onibex-ask scale deploy ask-onibex-ask-keycloak --replicas=0
kubectl -n onibex-ask wait --for=delete pod -l app.kubernetes.io/component=keycloak --timeout=90s
kubectl -n onibex-ask delete pvc ask-onibex-ask-keycloak
helm upgrade ask deploy/helm/onibex-ask --namespace onibex-ask --values <your values file>
```

**The login works, and then every API call returns 401 saying "no configured issuer accepted the
token".** Two different causes, and the log tells them apart in one line.

The first is the one that cost a smoke test. **The backends could not fetch the signing keys**, so
the validator has nothing to check the signature with and rejects everything. It looks like an
issuer problem and is a network one:

```bash
kubectl -n onibex-ask logs deploy/<release>-admin-api | grep -i "JWKS fetch failed"
```

`CERTIFICATE_VERIFY_FAILED ... unable to get local issuer certificate` means the pods were sent to
fetch the keys over the public hostname, and with `gateway.tls.mode: internal` that certificate is
signed by Caddy's own authority, which no pod trusts. The chart now derives `KEYCLOAK_JWKS_URL`
from the in-cluster Service whenever Keycloak is in the release, so this is fixed rather than
configured around; on an older release, set it by hand:

```bash
--set auth.jwksUrl=http://<release>-keycloak:8080/realms/ask-platform/protocol/openid-connect/certs
```

Nothing is weakened by the short path: the validator checks signature and expiry and does **not**
check the issuer, so the token still carries the public issuer the browser saw.

The second cause is a genuine issuer mismatch, and then the log carries no JWKS error at all.
Compare `auth.publicUrl` against the issuer Keycloak advertises, which is readable without signing
in:

```bash
curl -sk https://<your auth host>/realms/ask-platform/.well-known/openid-configuration
```

**The sign-in stops with `Invalid parameter: redirect_uri`, after the password has been typed.**
The realm's whitelist does not list the address the app is served from. That is a realm problem,
not a chart problem: rebuild it with the right `--host` values. The check is one request, and it
is worth running before involving a person:

```bash
curl -sk -o /dev/null -w '%{http_code}\n' \
  "https://<auth host>/realms/ask-platform/protocol/openid-connect/auth?client_id=ask-studio&redirect_uri=https%3A%2F%2F<studio host>%2Flogin%2Fcallback&response_type=code&scope=openid&state=probe"
```

`302` means the address is accepted. `400` means it is not.

**The site is trusted on your machine and warns on everyone else's.** The certificate was loaded
without its intermediates. `gateway.tls.mode: existing` serves exactly the bytes in the Secret, so
a `--cert` holding only the leaf leaves every visitor to build the chain themselves, and only those
who happen to have cached the intermediate already can. Measured on a test chain: a client holding
only the root gets `unable to verify the first certificate` while a client that has the
intermediate gets `OK`, from the same server and the same certificate. Count what the server sends,
which should be more than one for anything but a self-signed certificate:

```bash
echo | openssl s_client -connect <host>:443 -servername <host> -showcerts 2>/dev/null \
  | grep -c 'BEGIN CERTIFICATE'
```

The fix is a new Secret built from the full chain file the authority issued, plus
`kubectl -n onibex-ask rollout restart deploy/<release>-gateway`. The restart is not optional:
Caddy reads those files when it loads its config, so replacing the Secret alone changes nothing.

**The admin API will not start.** Two causes, and the traceback distinguishes them. It refuses to
boot when the semantic-layer paths are empty or do not point at a real directory. It also refuses
an unrecognised `platform.environment`, which the chart now stops at render time.

**Keycloak crash-loops and the log says `invalidPasswordMinDigitsMessage`.** The realm enforces
`length(8) and digits(1) and upperCase(1)` **while importing**, not at first sign-in, so an initial
password that breaks it does not produce a user who must pick a better one: it aborts the import
and takes the server down with it. The message arrives about twenty lines into a Quarkus startup
log, with nothing naming the argument that caused it. The cause is the `--password` argument to
`make_realm_import.py`, and the fix is a new realm Secret built with a compliant password. The
script checks this before writing the file, so this only appears on a realm assembled some other
way.

**Every volume sits in `Pending` and nothing ever starts.** Two different causes that look
identical, and the second is the one that wastes an afternoon:

- `WaitForFirstConsumer` in the events is **normal**. The disk is deliberately not created until a
  pod that needs it is scheduled, so it lands in the right zone.
- **No default StorageClass at all** is not normal, and it is silent. Every `storageClassName` in
  the values files is deliberately empty, which means "use the cluster default", so a cluster
  without one leaves all four claims unbound forever with nothing naming the cause. A stock EKS
  cluster is in exactly this state. `kubectl get sc` prints `(default)` next to the class that is
  one, and next to nothing if there is none.

Read the events rather than the phase:

```bash
kubectl -n onibex-ask describe pvc <name>
```

`ProvisioningFailed` is a third, real, problem.

**An app pod crash-loops on `chown(/var/cache/nginx/client_temp) failed`.** nginx starts as root,
chowns its cache directories and drops its workers to an unprivileged user, so it needs CHOWN,
SETUID and SETGID kept. Dropping every capability and adding back only NET_BIND_SERVICE looks
tighter and stops all three apps.

**A rollout hangs with the new pod Pending and `Insufficient cpu`.** A rolling update reserves the
new pod's requests before releasing the old pod's, so a node with no spare CPU cannot hold both.
Set `updateStrategy: Recreate`, and read the note in `values.yaml` first: changing it on an
installed release fails until the Deployments are recreated.

**A rollout hangs with the new pod stuck on `Multi-Attach error`.** Different cause, same symptom
shape. Three workloads mount a ReadWriteOnce volume, and on most clouds that volume can be attached
to one node at a time, so a rolling update that lands the new pod on a second node deadlocks: the
old pod will not release until the new one is Ready, and the new one cannot start until the old one
releases. It does not appear on a single-node cluster, which is why it can hide for a long time.
`updateStrategy: Recreate` is the fix here too.

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
| `ask-onibex-ask-gateway-data` | the certificates and, on Let's Encrypt, the ACME account key |

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
the Secret step fail with `AlreadyExists` on an environment that is otherwise empty.

**Wait for the Services to go, because that is the billing stopping.** The `LoadBalancer` Services
take a minute or two to disappear after the uninstall. They sit in `Terminating` behind a
`service.kubernetes.io/load-balancer-cleanup` finalizer while the cloud releases the load balancers
and the addresses. Watch for `kubectl -n onibex-ask get svc` to come back empty rather than
assuming it happened, and on AWS confirm from the other side as well, because a load balancer left
behind keeps charging with nothing in the cluster pointing at it:

```bash
aws elb describe-load-balancers --query 'LoadBalancerDescriptions[].LoadBalancerName' --output text
```

**Two things that read as bugs when a volume is kept by accident.** Keycloak does not re-import the
realm, so a password changed in the console stays changed and the initial one keeps being rejected.
OpenSearch keeps every credential, so ASK Setup looks fully configured before anyone has configured
it.

**And one cost of deleting the gateway volume**, on Let's Encrypt only. Certificates are requested
again on the next start, and Let's Encrypt limits duplicate certificates to five per week for the
same set of names, so repeated teardowns can run out. Keeping that one volume and deleting the rest
avoids it. With a self-signed gateway certificate the volume costs nothing to lose.

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
- **SAP BTP Kyma has not been installed from this chart, and has no runbook.** AKS and EKS both
  have, and both turned up cluster-level prerequisites that no amount of reading the chart would
  have predicted. Kyma is expected to turn up more, since it also drags in an IAS tenant and the
  approuter. Its runbook will be written from an install that worked, the same way the other two
  were, rather than guessed in advance.
- **Four load balancers where one would do**, and a domain does not fix it. Covered under
  [What this chart is](#what-this-chart-is-and-what-it-deliberately-is-not). On AWS that is about
  73 USD a month against roughly 18 for one, and the gateway already tells the hostnames apart by
  the `Host` header, so what is missing is only the chart rendering one Service instead of four.

---

## On Windows and PowerShell

Every `kubectl` and `helm` line in the runbooks runs unchanged. What differs is the shell around
them, and these are the five places it bites.

**`curl` is not curl.** In Windows PowerShell 5.1 it is an alias for `Invoke-WebRequest`, which
takes different arguments and fails confusingly on `-X` or `-H`. Call the real one by its full
name, `curl.exe`, or run the checks from Git Bash.

**A tool installed in one shell is not on the PATH of the other.** Git Bash reads a different PATH
from PowerShell, so `helm` installed into `~/bin` from Git Bash is invisible to PowerShell, and
Docker Desktop's own `kubectl` sits early in the Windows system PATH and answers instead of the one
you installed. This is not theoretical: it is how a machine ends up reporting `kubectl` 1.28 in one
window and 1.33 in the next. `which kubectl helm` in the shell you are actually using settles it.

**There is no command substitution with `$(...)`, and no `\` line continuation.** Build the value
first, then pass it:

```powershell
$rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::Create()
$b = New-Object byte[] 32; $rng.GetBytes($b)
$key = [Convert]::ToBase64String($b).Replace('+','-').Replace('/','_')
$p1 = New-Object byte[] 18; $rng.GetBytes($p1)
$p2 = New-Object byte[] 18; $rng.GetBytes($p2)
$ing = New-Object byte[] 32; $rng.GetBytes($ing)

kubectl -n onibex-ask create secret generic ask-platform-secret `
  --from-literal=encryption-key=$key `
  --from-literal=opensearch-user=admin `
  --from-literal=opensearch-password=$([Convert]::ToBase64String($p1)) `
  --from-literal=keycloak-admin-password=$([Convert]::ToBase64String($p2)) `
  --from-literal=ingest-api-key=(($ing | ForEach-Object { $_.ToString('x2') }) -join '')
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

**Paths and deletion.** `rm` is `Remove-Item`. The realm file carries passwords, so deleting it
after loading the Secret is part of the procedure, not tidying.

**And `cmd.exe` is the one to avoid outright.** It does not expand `$(...)` at all and does not
treat it as an error either: the Secret is created with the literal string `$(python -c ...)` as
its value, the command reports success, and the failure surfaces three steps later as backends that
cannot decrypt anything. Same failure shape as the PowerShell trap above, with nothing to warn you.
The length check in the Secret step catches both.

Git Bash, WSL or a Linux shell avoids all of this. If you have one, use it: the commands in the
runbooks are then literal, with the single exception of the relative path noted in the realm step.

---

[← Back to the manual](../README.md)
