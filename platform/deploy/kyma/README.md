<!-- SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0 -->
<!-- Copyright (c) 2026 Onibex, LLC. All rights reserved. -->

# Kyma-only manifests

Everything in this folder depends on custom resources that **only SAP BTP Kyma
provides**. Nothing here applies on EKS or AKS, and that is why it sits apart
from the manifests one level up rather than mixed in with them.

The parent folder is portable: Namespace, ConfigMap, Secret, Deployment and
Service are plain Kubernetes and apply anywhere. Keeping the two apart is what
lets `kubectl apply` succeed on the first target without anybody having to know
which objects to skip.

## What is in here and what each thing is for

| File | Kind | Provided by | What it does |
|---|---|---|---|
| `apirule-orchestrator.yaml` | `APIRule` | Kyma | Publishes the orchestrator outside the cluster |
| `apirule-studio.yaml` | `APIRule` | Kyma | Publishes the Studio SPA outside the cluster |
| `peer-authentication.yaml` | `PeerAuthentication` | Istio | Lets the orchestrator accept non-mTLS traffic inside the mesh |

An `APIRule` is not a Kubernetes object. Kyma installs it as a CRD and its
operator translates it into Istio resources (a VirtualService plus its
authorization policy) attached to `kyma-system/kyma-gateway`. On a cluster
without Kyma the API server does not know the kind at all, and `kubectl apply`
fails with `no matches for kind "APIRule" in version
"gateway.kyma-project.io/v2"`. Same story for `PeerAuthentication`, which needs
Istio: Kyma ships it, a plain EKS or AKS cluster does not.

Both APIRules set `noAuth: true` on purpose. It does not mean the endpoint is
open. It means the gateway forwards the request with its `Authorization` header
untouched, because the token is validated further in: in process by the
orchestrator for the API, and in the browser by PKCE for the SPA.

## Applying

```bash
# Any cluster, including Kyma: the portable base
kubectl apply -f  platform/deploy/namespace.yaml
kubectl apply -f  platform/deploy/ask-config-configmap.yaml
kubectl apply -f  platform/deploy/ask-orchestrator-deploy/
kubectl apply -f  platform/deploy/ask-admin-api-deploy/
kubectl apply -f  platform/deploy/ask-studio-deploy/

# Kyma only, afterwards
kubectl apply -f  platform/deploy/kyma/
```

Replace `<YOUR_CLUSTER_DOMAIN>` in both APIRules with the cluster's domain
first. On EKS and AKS there is no external entry point yet: reach a pod with
`kubectl port-forward` until the chart adds an Ingress. See the open item below.

## What else a Kyma deployment needs, beyond these three files

Written down here so the next person does not have to rediscover it:

* **`AUTH_MODE`, and it is a decision, not a copy.** The two backends ship
  `keycloak`, which is the EKS path. A Kyma deployment fronted by SAP SSO wants
  `xsuaa`. The value is read on every request, so switching it is a plain edit
  and no restart.

  **It will never accept `both`.** The validator is an `if` / `elif` with no
  `else` (`auth/validator.py:338`, identical in both backends), so any value
  that is not `keycloak` or `xsuaa` matches no branch, `claims` stays `None`,
  and **every request 401s while the pods report healthy**. `both` was set in
  the admin API manifest until 2026-09-09 for exactly this reason: it looked
  like it meant "accept either".

  Which value is right depends entirely on how SSO ends up configured on the
  BTP side, so it cannot be decided before that tenant exists. If the answer
  turns out to be "accept an SAP token from some clients and a Keycloak one
  from others", **that is a code change**, not a values one: the validator has
  to try each configured issuer in turn, with a test pinning that a token one
  issuer rejects is still accepted by the other. Do not assume it works today.
* **The `xsuaa-ask-secret` filled in.** Every XSUAA reference in the two
  Deployments is marked `optional: true` precisely so their absence does not
  block a non-BTP cluster. On Kyma they stop being optional in practice: with
  `AUTH_MODE=xsuaa` and no `XSUAA_URL`, `_validate_xsuaa` logs at debug level
  and returns None, and every request 401s with no obvious cause.
* **The SPAs' auth configuration**, which today is baked into each image at
  build time. Task T3 moves it to container start, and until that lands a Kyma
  deployment needs its own image build per cluster domain.
* **The IAS tenant and the approuter**, which are outside this repo and outside
  our control. That dependency is why Kyma is the third target and not the
  first.

Reference material from the earlier BTP deployment (`xs-security.json`, the SSO
notes) is archived under `platform/_internal/archive/`, which is untracked, so
it exists only on a machine that had it.

## When the Helm chart arrives (phase 4)

The chart replaces both this folder and its parent. The mapping is meant to be
mechanical:

| Chart template | Guard | Source |
|---|---|---|
| `templates/apirule.yaml` | `{{- if .Values.kyma.enabled }}` | the two files here |
| `templates/peerauthentication.yaml` | `{{- if .Values.kyma.enabled }}` | the file here |
| `templates/ingress.yaml` | `{{- if .Values.ingress.enabled }}` | does not exist yet |

`values-kyma.yaml` turns the first two on, `values-eks.yaml` and
`values-aks.yaml` turn the Ingress on instead. One chart, one values file per
target.

**Open item, deliberately not decided here:** the Ingress does not exist because
writing it means choosing an ingress class, a hostname and a TLS source, and
those differ per target (AWS Load Balancer Controller on EKS, nginx or AGIC on
AKS). That is a values decision and it belongs with the chart, not with a raw
manifest that would have to guess.
