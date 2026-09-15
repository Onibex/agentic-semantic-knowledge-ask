# Deploy on Kubernetes with Helm

[Manual](../README.md) › [Operating the platform](../README.md#operating-the-platform) › **Deploy on Kubernetes with Helm**

> **How to.** Install the whole platform on a Kubernetes cluster from one Helm chart, on Azure
> AKS, AWS EKS or SAP BTP Kyma. For the person who has cluster access and is standing up an
> environment.
> **Scope:** the chart in `deploy/helm/onibex-ask`, the values it needs, and what to look at
> when a pod does not start.

| | |
|---|---|
| **Who** | Whoever holds cluster credentials and the platform encryption key |
| **Time** | ~30 minutes for a first install, most of it waiting for images to pull |
| **Prerequisites** | `kubectl` and `helm` 3 or later, a namespace you can create objects in, and the seven ASK images published to a registry the cluster can pull from |
| **You'll end with** | The nine services running, reachable through `kubectl port-forward` |

---

## What this chart is, and what it deliberately is not

One chart renders every service the compose file runs: the two Python backends, the three
single-page apps, OpenSearch, Keycloak, and the two opt-in services.

**It names no cloud.** No Ingress, no storage class, no load balancer, no provider annotation.
That is not an omission, it is the design: those differ per target, and keeping them out is what
lets the same chart serve AKS, EKS and Kyma. Until a per-target values file adds an entry point,
you reach the apps with `kubectl port-forward`.

**It has never been applied to a live cluster.** As of this page the chart renders, lints and
validates against a real Kubernetes API server in strict mode, and that is all it has done.
Treat a first install as the verification step, not as a routine.

---

## Before you start

**1. The images have to exist.** Kubernetes builds nothing, it pulls. Run the
`platform-images` workflow from the default branch and note the account you published under;
that account is `image.namespace`. Without this step every pod sits in `ImagePullBackOff`.

**2. Create the Secret out of band.** Three things cannot live anywhere else, because each is
needed before the store that holds everything else can be read.

```sh
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

```sh
helm install ask deploy/helm/onibex-ask \
  --namespace onibex-ask \
  --values deploy/helm/onibex-ask/values-aks-dev.yaml \
  --set image.namespace=<your-registry-account> \
  --set auth.publicUrl=https://auth.example.com
```

The install refuses to render rather than producing something half-working. Each refusal names
the value and says what goes wrong if it is guessed:

| If this is missing | Why the chart stops |
|---|---|
| `image.namespace` | There is no sensible default, and the wrong account fails late as a pull error that names nothing |
| `auth.publicUrl` | An empty value used to serve a login page pointing at a host that does not exist, with nothing reporting it |
| A secret source | The backends refuse to boot without the encryption key anyway; failing here is faster to read |
| A valid `auth.mode` | The token validators accept exactly `keycloak` or `xsuaa`. Anything else matches no branch and every request is rejected while the pods report healthy |
| `keycloak.database.host` when production is on | Production mode without a database is a contradiction; development mode keeps state in a file inside the pod |

---

## Reach the apps

```sh
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

```sh
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

**The admin API will not start.** It refuses to boot when the semantic-layer paths are empty or
do not point at a real directory. Check that the volume was bound: `kubectl -n onibex-ask get
pvc`.

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

```sh
helm uninstall ask --namespace onibex-ask
```

The semantic-layer volume is kept on purpose: it can hold YAML that was authored and not yet
pushed, and a chart should not decide to delete that. Remove it deliberately when you mean to:

```sh
kubectl -n onibex-ask delete pvc ask-onibex-ask-semantic-layer
```

The Secret is yours, not the chart's, and is not removed either.

---

## What is not done yet

- **No entry point.** Ingress, certificates and DNS are the next step and they are per target.
- **Keycloak defaults to development mode**, which keeps its realm in a file inside the pod and
  loses it when the pod is replaced. Set `keycloak.production=true` with a real database before
  anyone depends on the environment.
- **The apps run as root inside their container.** Their images are stock nginx on port 80.
  Fixing it means rebuilding them on an unprivileged base, which is image work rather than chart
  work.

---

[← Back to the manual](../README.md)
