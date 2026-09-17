# The `onibex-ask` Helm chart

One chart, one values file per target. It renders every service the platform runs and names no
cloud, which is what lets the same chart serve Azure AKS, AWS EKS and SAP BTP Kyma.

For the install procedure, the failure modes and the uninstall, read
[Deploy on Kubernetes with Helm](../../../docs/runbooks/kubernetes-deploy.md). This page is the
values reference.

## What it renders

| Workload | Kind | Default | Note |
|---|---|---|---|
| ASK Orchestrator | Deployment | on | Chat backend, port 8080 |
| ASK Admin API | Deployment | on | Admin backend, port 8081. Pinned at one replica |
| ASK Studio, ASK Chat, ASK Setup | Deployment | on | nginx serving a bundle, proxying `/api` by Service name |
| OpenSearch | StatefulSet | on | Switchable for a managed endpoint |
| Keycloak | Deployment | on | Switchable for an external identity provider |
| MCP server | Deployment | off | Needs SAP credentials |
| Teams bot | Deployment | off | Needs a Microsoft app registration |

No Ingress, no storage class, no load balancer, no provider annotation. Those are per target and
belong in a values file.

## The values that have no default

The chart stops at render time rather than producing a deployment that starts and then serves
something broken. Each refusal names the value.

| Value | What it is |
|---|---|
| `image.namespace` | The registry account the seven images were published under |
| `auth.publicUrl` | The identity provider's origin **as the browser reaches it**, which is also the token issuer |
| `secrets.existingSecret` or `secrets.create` | Where the encryption key and the OpenSearch credentials come from |

## Values reference

### Images

| Key | Default | Note |
|---|---|---|
| `image.registry` | `docker.io` | |
| `image.namespace` | *(required)* | |
| `image.tag` | chart `appVersion` | The image workflow publishes no `latest` tag on purpose |
| `image.pullPolicy` | `IfNotPresent` | |
| `image.pullSecrets` | `[]` | Public images need none |

### Identity

| Key | Default | Note |
|---|---|---|
| `auth.mode` | `keycloak` | `keycloak` or `xsuaa`, and nothing else. There is no `both` |
| `auth.publicUrl` | *(required)* | Scheme included, no trailing slash |
| `auth.realm` | `ask-platform` | |
| `auth.jwksUrl` | derived | Set it when the pods and the browser cannot use one address |
| `auth.chatMode` | follows `auth.mode` | `none` runs ASK Chat without a login, for a plain-HTTP host where PKCE cannot work |
| `publicUrls.studio` / `.chat` / `.setup` | `""` | Cross-app links. Empty hides a link rather than breaking it |

### Secrets

| Key | Default | Note |
|---|---|---|
| `secrets.existingSecret` | `""` | Recommended. Create it out of band so no key passes through a values file |
| `secrets.create` | `false` | Throwaway environments only; the key lands in the release manifest |
| `secrets.keys.*` | see `values.yaml` | Key names inside the Secret |
| `sapAiCore.existingSecret` | `""` | Mounts the SAP AI Core service key at `config/aicore_config.json` |
| `xsuaa.existingSecret` | `""` | BTP only. Every reference is optional, so its absence is normal elsewhere |

### OpenSearch

| Key | Default | Note |
|---|---|---|
| `opensearch.enabled` | `true` | `false` plus `opensearch.host` points at a managed endpoint |
| `opensearch.javaOpts` | `-Xms512m -Xmx512m -XX:+UseG1GC` | Heap at or below half the container. Two OOM crash loops taught this |
| `opensearch.memoryLock` | `false` | `mlockall` needs privileges the baseline Pod Security Standard forbids |
| `opensearch.persistence.*` | 20Gi, default class | |

### Keycloak

| Key | Default | Note |
|---|---|---|
| `keycloak.enabled` | `true` | `false` when the issuer lives elsewhere |
| `keycloak.production` | `false` | `false` runs `start-dev`, which is not a production mode and loses state on pod replacement |
| `keycloak.database.*` | empty | Required when `production` is true |
| `keycloak.proxyHeaders` | `xforwarded` | Without it, Keycloak behind a proxy issues http redirects and the login breaks |
| `keycloak.realmImportConfigMap` | `""` | Imported on first boot only |

### Workloads

| Key | Default | Note |
|---|---|---|
| `orchestrator.replicas` | `1` | |
| `adminApi.replicas` | `1` | Cannot be raised. It owns a git working tree on a ReadWriteOnce volume |
| `studio.replicas` / `chat` / `setup` | `1` | |
| `mcpServer.enabled` | `false` | |
| `teamsBot.enabled` | `false` | Needs `teamsBot.existingSecret` |
| `semanticLayer.persistence.enabled` | `true` | `false` uses an emptyDir and loses unpushed YAML on every restart |
| `platform.semanticLanguage` | `en` | Must match the language the corpus is authored in |
| `platform.columnNaming` | `technical` | Fixed before the first ingest |

### Cluster behaviour

| Key | Default | Note |
|---|---|---|
| `topologySpread.enabled` | `true` | Applied only above one replica. There is no `podAffinity` anywhere in this chart |
| `podDisruptionBudget.enabled` | `true` | Rendered only above one replica, because a budget over a single replica blocks node drains |
| `serviceAccount.create` | `true` | With no Role and no RoleBinding: nothing in ASK talks to the Kubernetes API |

## Bundled values files

| File | For |
|---|---|
| `values.yaml` | The documented defaults. Every entry carries its reason |
| `values-aks-dev.yaml` | Azure AKS, development, on a shared node measured at 99% reserved CPU and 2% real usage. Small requests, generous limits |

## Verifying a change

```sh
helm lint deploy/helm/onibex-ask
helm template ask deploy/helm/onibex-ask -n onibex-ask \
  --set image.namespace=onibex --set auth.publicUrl=https://auth.example.com \
  --set secrets.existingSecret=ask-platform-secret \
  | kubectl apply --dry-run=client --validate=strict -f -
```

The last step is the one that catches a mistyped field name, because it validates against a real
API server rather than against a local guess.
