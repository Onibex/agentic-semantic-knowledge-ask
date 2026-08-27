# ASK Orchestrator — Troubleshooting Runbook

[Manual](../README.md) › [Operating the platform](../README.md#operating-the-platform) › **ASK Orchestrator — Troubleshooting Runbook**

> **Audience:** ops / on-call.
> **Scope:** the `ask-orchestrator` deployment.

---

## ⚠️ XSUAA dev bypass — DO NOT TOUCH IN PRODUCTION

The orchestrator implements a **dual-flag** bypass for local development:

```
bypass_active == True    iff    ENVIRONMENT == "local"  AND  DEV_BYPASS_AUTH == "true"
```

In any other combination — including `ENVIRONMENT=production` with
`DEV_BYPASS_AUTH=true` — the bypass is **ignored** and real XSUAA validation
runs. This is enforced by a unit test (`test_production_with_bypass_flag_set_still_validates`)
that fails the build if regressed.

**The production deployment ConfigMap fixes:**
```
ENVIRONMENT=production
DEV_BYPASS_AUTH=false
```

**NEVER set `DEV_BYPASS_AUTH=true` in any non-`local` environment.**

If you must test against staging without an XSUAA round-trip, exec into a pod
and use `kubectl port-forward`, never re-deploy with the flag flipped.

---

## Health checks

| Check                         | Expected                                          |
|-------------------------------|---------------------------------------------------|
| `GET /v1/health`              | `{"status":"ok"}` — unauthenticated, used by probes |
| `GET /openapi.json`           | OpenAPI 3.x JSON                                  |
| `POST /v1/query`              | `QueryResponse` with valid `mode_used`            |
| `kubectl get pods -n onibex-ask -l app=ask-orchestrator` | All replicas Ready |

---

## Common problems

### 1. `/v1/query` returns 401 "Missing bearer token"

- **Cause:** request didn't include `Authorization: Bearer <jwt>`.
- **In the chat SPA:** the browser attaches the access token it obtained from the
  identity provider; the SPA's Nginx then proxies `/api/orchestrator/*` to the
  orchestrator **preserving that header**. A 401 therefore means either the
  browser session has no token (log in again) or a proxy in front of the SPA is
  stripping `Authorization`.
- **In machine-to-machine callers (watsonx, [Apache Kafka](https://kafka.apache.org/) Connect, LangFlow):** include a
  client-credentials token in the Authorization header.

### Validating JWT forwarding end-to-end

Manual procedure — run after deploying the orchestrator + chat SPA:

1. Deploy: `kubectl apply -f deploy/ask-orchestrator-deploy/`
2. Open the chat SPA and log in.
3. Ask a Precise/Smart question through the UI.
4. From a separate shell, tail orchestrator logs:
   ```
   kubectl logs -n onibex-ask deployment/ask-orchestrator -f
   ```
   Expect the request log line to include:
   - `auth_bypass: false`
   - `user_email` populated
   - the matching `trace_id`
5. If the orchestrator returns 401, capture:
   - The `Authorization` header the browser actually sent (devtools → Network →
     the failing `/api/orchestrator/query` request).
   - The proxy hop that forwarded the call (the SPA's `nginx.conf` `location
     /api/orchestrator/`).
   - Whether `XSUAA_VERIFICATION_KEY` matches the key used to sign the JWT.

### 2. `/v1/query` returns 503 "XSUAA credentials not configured"

- **Cause:** the deployment is missing one of `XSUAA_CLIENT_ID`,
  `XSUAA_CLIENT_SECRET`, `XSUAA_URL`, `XSUAA_UAA_DOMAIN`,
  `XSUAA_VERIFICATION_KEY`, `XSUAA_XSAPPNAME`.
- **Fix:** check the deployment binding to the XSUAA secret — every field above
  must be present in the Secret the Deployment mounts.

### 3. `/v1/query` returns 500 "PIPELINE_ERROR"

- **Cause:** one of the chained services (intent resolution, SQL generation, SQL
  execution) raised. The orchestrator wraps the exception into `ErrorResponse`
  and surfaces it.
- **Diagnose:**
  1. Look up the `trace_id` returned in the response.
  2. `kubectl logs -n onibex-ask deployment/ask-orchestrator | grep <trace_id>`.
  3. Common roots:
     - `OpenSearchAskRepository` connection refused → check `opensearch.host` in `config/settings.json`.
     - HANA / Postgres connection refused → check `hana` / `postgresql` block.
     - SAP AI Core deployment ID changed → check `deployments.llm` / `deployments.embeddings`.

### 4. Pod fails liveness probe immediately

- **Cause:** `config/settings.json` is missing or unreadable from `/app/config`.
- **Fix:** the deployment mounts `ask-config-pvc` at `/app/config`.
  Verify `kubectl describe pod` shows the volume bound and the file exists
  inside the container (`kubectl exec ... -- ls /app/config/`).

### 5. Chat SPA shows "Orchestrator unreachable"

- The SPA's Nginx couldn't reach the orchestrator it proxies to.
- Check:
  - `kubectl get svc -n onibex-ask ask-orchestrator-service`
  - `kubectl exec deployment/ask-chat-spa -- wget -qO- http://ask-orchestrator-service/v1/health`
  - Network policies between pods.

---

## Useful commands

```bash
# tail orchestrator logs
kubectl logs -n onibex-ask deployment/ask-orchestrator -f

# port-forward for local debugging
kubectl port-forward -n onibex-ask svc/ask-orchestrator-service 8080:80

# hit the orchestrator with a forged token (fails fast — useful to verify auth wiring)
curl -X POST http://127.0.0.1:8080/v1/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer fake.jwt.token" \
  -d '{"question":"how many open POs?","mode":"precise"}'
```

---

[← Back to the manual](../README.md)
