# Deployment manifests

Two things live here and they are not equivalent. Read this before applying anything.

## Use the Helm chart

[`helm/onibex-ask`](helm/onibex-ask/README.md) renders every service the platform runs, for
Azure AKS, AWS EKS and SAP BTP Kyma, from one chart with a values file per target. It is the
supported way to deploy on Kubernetes.

The procedure is in
[Deploy on Kubernetes with Helm](../docs/runbooks/kubernetes-deploy.md).

## The loose manifests are earlier work

`ask-admin-api-deploy/`, `ask-orchestrator-deploy/`, `ask-studio-deploy/`, the two ConfigMaps
and `secret.example.yaml` predate the chart. They cover three of the nine services, carry no
RBAC and describe one hardcoded namespace.

They are kept because they are where several decisions were worked out and written down, and the
chart inherits those decisions rather than replacing them: the dead `podAffinity` and why it is
gone, `KEYCLOAK_JWKS_URL` being the variable the validators actually read, `AUTH_MODE` accepting
exactly two values, and `settings.json` as a read-only ConfigMap.

**Prefer the chart.** Applying this folder directly gives an incomplete stack: ASK Setup, ASK
Chat, the MCP server and the Teams bot have no manifest here, and OpenSearch and Keycloak are
referenced as if they already existed.

`kyma/` holds the BTP-specific exposure objects and is likewise superseded by the chart's Kyma
values file when that target comes up.
