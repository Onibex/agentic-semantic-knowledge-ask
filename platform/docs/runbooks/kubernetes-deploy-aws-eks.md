# Deploy ASK on AWS EKS

[Manual](../README.md) › [Operating the platform](../README.md#operating-the-platform) › **Deploy ASK on AWS EKS**

> **How to.** Install the whole platform on an Amazon EKS cluster from one Helm chart, using the
> images Onibex publishes. Read top to bottom and run every command; there are no branches.
> **Shell:** bash. On Windows use Git Bash, and see
> [On Windows and PowerShell](kubernetes-reference.md#on-windows-and-powershell).

| | |
|---|---|
| **Who** | Whoever holds AWS credentials for the account the cluster is in |
| **Time** | About 40 minutes, most of it waiting for images to pull and load balancers to answer |
| **You'll end with** | Eight of the nine services Ready, the three apps open in a browser on public HTTPS addresses with a working sign-in, and the MCP server deliberately unready until you register a contract |

**On another cloud?** [Deploy ASK on Azure AKS](kubernetes-deploy-azure-aks.md) has its own page,
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
| `aws` | 2 | Getting a kubeconfig, and tagging subnets |
| `kubectl` | Within one minor of the cluster, either way. Check with `kubectl version` | Everything |
| `helm` | 3 or later | Installing the chart |
| `python` | 3.10 or later | The encryption key and the realm file |
| `openssl` | any | Generating passwords. On Windows it ships with Git for Windows |
| `curl` | any | The checks at the end. **Not PowerShell 5.1's `curl`**, which is an alias for `Invoke-WebRequest` |

> **Check them in the shell you are actually going to use.** Git Bash and PowerShell read different
> PATHs on Windows, so a `helm` installed into `~/bin` from Git Bash is invisible to PowerShell, and
> Docker Desktop ships its own `kubectl` early in the Windows system PATH and will answer instead of
> the one you installed. The same machine can report `kubectl` 1.28 in one window and 1.33 in the
> next, and only one of those passes the skew check.
>
> ```bash
> which aws kubectl helm python openssl curl
> ```

### What this costs while it runs

Worth knowing before you start, because two of these are decisions and not facts.

| | |
|---|---|
| The node | A `t3a.xlarge` is about 100 USD a month, and one is enough |
| Four load balancers | About 18 USD a month each, **about 73 USD in total** |
| EBS volumes | 33Gi of gp3, under 3 USD a month |

The four load balancers are the part to think about. They are four because a cloud-assigned name
belongs to one load balancer and the three apps cannot share a hostname. **With a domain of your
own that becomes one load balancer and four DNS records**, because the gateway already routes by
`Host` header. See [Step 3](#step-3-decide-the-addresses-people-will-use).

---

## Step 0. Point kubectl at the cluster

```bash
aws eks update-kubeconfig --region <region> --name <cluster>
```

**If that returns `AccessDeniedException` naming an `explicit deny`, you are not missing a
permission on the cluster.** Read the policy it names. An account with a policy along the lines of
`MFAactived` denies every action on a session that did not authenticate with MFA, so the error
arrives from EKS while the cause is your session, and no amount of granting EKS rights fixes it.
Get a session with MFA and use it:

```bash
aws iam list-mfa-devices --user-name <you>          # prints the serial number

aws sts get-session-token \
  --serial-number arn:aws:iam::<account>:mfa/<device> \
  --token-code <the six digits, freshly generated> \
  --duration-seconds 43200
```

That prints three values. Put them in a named profile, then use that profile from here on:

```bash
aws configure set aws_access_key_id     <AccessKeyId>     --profile mfa
aws configure set aws_secret_access_key <SecretAccessKey> --profile mfa
aws configure set aws_session_token     <SessionToken>    --profile mfa
aws configure set region                <region>          --profile mfa

aws eks update-kubeconfig --region <region> --name <cluster> --profile mfa
```

Passing `--profile` to `update-kubeconfig` is what makes this stick: the profile name is written
into the kubeconfig entry, so `kubectl` renews its own token for the life of the session without
you thinking about it. **The session expires**, twelve hours with the duration above, and when it
does every `kubectl` command starts failing at once. Repeat this step; nothing else is affected.

Confirm you are talking to the right cluster before you change anything in it:

```bash
kubectl config current-context
kubectl get nodes -o wide
```

---

## Step 1. Give the cluster the two things a stock EKS does not have

**Both of these fail silently.** Neither produces an error message that names the cause, and both
are cluster-wide changes, so if the cluster is shared, agree them first.

### 1a. A default StorageClass

A stock EKS cluster ships a `gp2` class and does not mark it default. Every `storageClassName` in
the values file is deliberately empty, which means "use the cluster default", so with no default
the four volumes stay `Pending` forever and no pod ever starts. Check first:

```bash
kubectl get sc
```

`(default)` appears next to the default class, and next to nothing when there is none. If there is
none, create one. `gp3` rather than `gp2`: it is cheaper per GB, it can be expanded, and it goes
through the EBS CSI driver that EKS already installs as an addon, where `gp2` still names the
in-tree provisioner.

```bash
kubectl apply -f - <<'EOF'
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  encrypted: "true"
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Delete
EOF
```

### 1b. Subnet tags, so a load balancer can be placed

A cluster is usually registered against private subnets. Its VPC normally also has public ones, but
AWS finds them **by tag**, so without the tags a `LoadBalancer` Service is created and simply never
gets an address. Find the public subnets, which are the ones whose route table sends `0.0.0.0/0` to
an internet gateway rather than a NAT gateway:

```bash
VPC=$(aws eks describe-cluster --name <cluster> --query 'cluster.resourcesVpcConfig.vpcId' --output text)

aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" \
  --query 'Subnets[].{id:SubnetId,az:AvailabilityZone,name:Tags[?Key==`Name`].Value|[0]}' --output table

aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC" \
  --query 'RouteTables[].{rt:RouteTableId,subnets:Associations[].SubnetId,igw:Routes[?GatewayId!=`local`].GatewayId}' --output json
```

The public subnets are the ones associated with a route table whose gateway starts `igw-`. Tag
those, and only those:

```bash
aws ec2 create-tags --resources <public subnet ids, space separated> \
  --tags Key=kubernetes.io/role/elb,Value=1 \
         Key=kubernetes.io/cluster/<cluster>,Value=shared
```

Measured after tagging: a load balancer is allocated within about five seconds, and answers from
the internet about fifty seconds later, once its health check passes. Nothing reports the gap, so a
Service that has an address but no answer yet is normal for that first minute.

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

**There is a chicken-and-egg problem here that is specific to AWS, and it decides the shape of the
next three steps.** On Azure you ask for a hostname and get it before anything runs. On AWS the
hostname is generated from the load balancer, so **it cannot be known until the Services exist**,
and the Services are created by the install. Hence two passes.

Read this whole step before running anything in it.

### If you have a domain of your own, use it

This is the better answer and it is also the cheaper one. Four names on your own domain are four
DNS records pointing at **one** load balancer, because the gateway routes by `Host` header. You get
a certificate with no browser warning, names people can read, and names that survive the load
balancer being replaced.

**They must be `CNAME` records, not `A` records.** A load balancer has no fixed address to put in
an `A` record; its addresses change without notice, and `kubectl get svc` prints a hostname in the
`EXTERNAL-IP` column precisely because there is no IP to print.

Order matters more than the commands. A certificate is issued by answering a challenge **at the
name**, so the DNS record has to resolve before the gateway first starts. In the other order
nothing errors loudly: the certificate is simply never issued.

1. Run the first pass below, and read the load balancer hostname it produces.
2. Create one `CNAME` per app pointing at that hostname.
3. Wait until all four resolve from outside the cluster.
4. Put your four names in `gateway.hosts`, set `gateway.tls.mode: acme` and
   `gateway.tls.email`, and continue from Step 4 with those names.

### If you do not have a domain, this is what you get

Four load balancer hostnames, one per app, and a certificate the gateway signs itself. Every
visitor accepts a browser warning once. The origin still counts as secure, so the sign-in works.

**Let's Encrypt is not an option on a load balancer hostname, and this is measured rather than
assumed.** Searching the Certificate Transparency logs for `%.us-east-2.elb.amazonaws.com` returns
**zero** certificates, from every certificate authority, across the entire history of the logs. The
same search for the equivalent Azure suffix returns over five thousand. Load balancer names are not
certifiable by anyone. Setting `gateway.tls.mode: acme` against one does not fail loudly; it simply
never obtains a certificate.

### The first pass: create the addresses, without Keycloak

Keycloak is left out of this pass **on purpose, and leaving it out is the whole trick**. A realm is
imported on a **first** boot only, and you cannot build the realm until you know the addresses. Let
Keycloak boot now and its first boot happens with no realm, which cannot be undone by adding one
later: you would have to delete its volume. Leaving it out means its first boot is the one in Step
5, with the realm already in place.

The gateway starts regardless, because it resolves its upstreams when a request arrives rather than
at startup.

```bash
helm install ask deploy/helm/onibex-ask \
  --namespace onibex-ask \
  --values deploy/helm/onibex-ask/values-eks-dev.yaml \
  --set keycloak.enabled=false \
  --set gateway.hosts.studio=studio.pass-one.invalid \
  --set gateway.hosts.chat=chat.pass-one.invalid \
  --set gateway.hosts.setup=setup.pass-one.invalid \
  --set gateway.hosts.auth=auth.pass-one.invalid \
  --set auth.publicUrl=https://auth.pass-one.invalid
```

`.invalid` is reserved by RFC 2606 and can never resolve, which is the point: nothing can
accidentally start depending on a placeholder. Now read the four names:

```bash
kubectl -n onibex-ask get svc -l app.kubernetes.io/component=gateway \
  -o custom-columns='SERVICE:.metadata.name,ADDRESS:.status.loadBalancer.ingress[0].hostname'
```

Four `*.elb.amazonaws.com` names appear within a few seconds. **Write them into
`values-eks-dev.yaml`** rather than passing them with `--set`: they are needed in three places
(`gateway.hosts`, `auth.publicUrl` and `publicUrls`), they are long, and you will need them again.
The file's `gateway.hosts` block is commented for exactly this.

The Services are keyed by app name and not by hostname, so everything from here on rewrites
configuration and restarts pods. **No load balancer is created again and no name changes.**

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

## Step 5. The second pass: Keycloak, with the realm and the real addresses

By now `values-eks-dev.yaml` holds the four real hostnames in `gateway.hosts`, `auth.publicUrl` and
`publicUrls`. This pass adds Keycloak, whose first boot is therefore the one that imports the realm.

**Render it first.** The chart checks eight values before producing anything, so the same command
with `template` in place of `upgrade` turns eight possible failures into a two-second check that
never touches the cluster:

```bash
helm template ask deploy/helm/onibex-ask \
  --values deploy/helm/onibex-ask/values-eks-dev.yaml > /dev/null
```

Silence means it rendered. Then:

```bash
helm upgrade ask deploy/helm/onibex-ask \
  --namespace onibex-ask \
  --values deploy/helm/onibex-ask/values-eks-dev.yaml
```

No `--set` this time, and nothing was dropped: `keycloak.realmImportSecret: ask-realm` is written
into `values-eks-dev.yaml` itself, because it is the name of a Secret rather than a credential and
because forgetting it is the most expensive mistake on this page. If you named the Secret something
else in the realm step, change it there.

`auth.publicUrl` is the origin the **browser** uses to reach Keycloak, and it is also the issuer
stamped into every token. An in-cluster Service name will not do: the OAuth exchange happens in the
browser. It has to match the gateway's Keycloak hostname exactly, and the chart refuses to install
if it is empty.

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

Four commands, and they fail in different places, which is the point. Substitute your own four
hostnames.

```bash
for h in <studio host> <chat host> <setup host> <auth host>; do
  printf '%-70s %s\n' "$h" "$(curl -sk -o /dev/null -w '%{http_code}' "https://$h/")"
done
```

`200` from the three apps and `302` from Keycloak. `000` means the load balancer is not answering
yet; give it the first minute described in Step 1b before treating it as broken.

Then the two that catch the mistakes this runbook exists to prevent:

```bash
curl -sk "https://<auth host>/realms/ask-platform/.well-known/openid-configuration" \
  | python -c "import sys,json; print(json.load(sys.stdin)['issuer'])"
```

It must print your `auth.publicUrl` followed by `/realms/ask-platform`, character for character.
`Realm does not exist` here means Keycloak booted once before the realm Secret existed; see
[the failures](kubernetes-reference.md#the-failures-worth-knowing-in-advance).

```bash
curl -sk -o /dev/null -w '%{http_code}\n' \
  "https://<auth host>/realms/ask-platform/protocol/openid-connect/auth?client_id=ask-studio&redirect_uri=https%3A%2F%2F<studio host>%2Flogin%2Fcallback&response_type=code&scope=openid&state=probe"
```

`302` means the realm accepts the address Studio is served from. `400` means it does not, and every
sign-in will stop after the password has been typed. Rebuild the realm with the right `--host`
values rather than debugging the browser.

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

> **With a self-signed gateway certificate, every browser warns once per hostname**, and there are
> four. That is expected and it is not a sign anything is wrong. It is also the reason to get a
> domain before showing this to anyone outside the team.

---

## When you are done with it

This environment costs about 73 USD a month in load balancers alone while it exists, so take it
down deliberately rather than by forgetting.
[Uninstall, and what survives](kubernetes-reference.md#uninstall-and-what-survives) covers it,
including the check from the AWS side that the load balancers really went.

The two cluster-wide changes from Step 1 are **not** part of the release and survive an uninstall:
the `gp3` StorageClass and the subnet tags. Leave them. They are harmless, they are what any other
workload on that cluster needs too, and removing them only guarantees the next install fails the
same way.

---

[← Back to the manual](../README.md) · [Kubernetes reference](kubernetes-reference.md) · [Deploy ASK on Azure AKS](kubernetes-deploy-azure-aks.md)
