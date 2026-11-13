# Orchestrator troubleshooting

[Manual](../README.md) › [Operating the platform](../README.md#operating-the-platform) › **Orchestrator troubleshooting**

> **How to.** Diagnose the chat backend when it misbehaves. For ops and on-call.
> **Scope:** the `ask-orchestrator` deployment.

---

## ⚠️ XSUAA dev bypass: DO NOT TOUCH IN PRODUCTION

The orchestrator implements a **dual-flag** bypass for local development:

```
bypass_active == True    iff    ENVIRONMENT == "local"  AND  DEV_BYPASS_AUTH == "true"
```

In any other combination, including `ENVIRONMENT=production` with
`DEV_BYPASS_AUTH=true`. The bypass is **ignored** and real XSUAA validation
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
| `GET /v1/health`              | `{"status":"ok"}`: unauthenticated, used by probes |
| `GET /openapi.json`           | OpenAPI 3.x JSON                                  |
| `POST /v1/query`              | `QueryResponse` with valid `mode_used`            |
| `kubectl get pods -n onibex-ask -l app=ask-orchestrator` | All replicas Ready |

---

## Common problems

### 1. `/v1/query` returns 401 "Missing bearer token"

- **Cause:** request didn't include `Authorization: Bearer <jwt>`.
- **In ASK Chat:** the browser attaches the access token it obtained from the
  identity provider; the SPA's Nginx then proxies `/api/orchestrator/*` to the
  orchestrator **preserving that header**. A 401 therefore means either the
  browser session has no token (log in again) or a proxy in front of the SPA is
  stripping `Authorization`.
- **In machine-to-machine callers (watsonx, [Apache Kafka](https://kafka.apache.org/) Connect, LangFlow):** include a
  client-credentials token in the Authorization header.

### Validating JWT forwarding end-to-end

Manual procedure, run after deploying the orchestrator + ASK Chat:

1. Deploy: `kubectl apply -f deploy/ask-orchestrator-deploy/`
2. Open ASK Chat and log in.
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
- **Fix:** check the deployment binding to the XSUAA secret, every field above
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
     - The LLM or embedder provider refuses the call → ASK Setup, **LLM Providers**, press **Test**
       on the active connection and on the embedder; the error names the cause.

### 4. Pod fails liveness probe immediately

- **Cause:** `config/settings.json` is missing or unreadable from `/app/config`.
- **Fix:** the deployment mounts `ask-config-pvc` at `/app/config`.
  Verify `kubectl describe pod` shows the volume bound and the file exists
  inside the container (`kubectl exec ... -- ls /app/config/`).

### 5. ASK Chat shows "Orchestrator unreachable"

- The SPA's Nginx couldn't reach the orchestrator it proxies to.
- Check:
  - `kubectl get svc -n onibex-ask ask-orchestrator-service`
  - `kubectl exec deployment/ask-chat -- wget -qO- http://ask-orchestrator-service/v1/health`
  - Network policies between pods.

### 6. Turn off clarifications in the chat

Use this when the chat asks before answering where it should not, and it has to answer straight
away while the cause is looked at.

Docker Compose:

1. On the server, open `config/settings.json` (the folder is mounted into the orchestrator at
   `/app/config`).
2. Set this key at the top level of the file:
   `"chat": {"ask_for_clarification": false}`
3. Restart the orchestrator: `docker compose restart ask-orchestrator`
4. Ask a question that used to get a clarification. The answer now comes straight away and
   states the reading it took.

Kubernetes:

1. Set the same key in `settings.json` of the `ask-config` ConfigMap.
2. Restart the orchestrator: `kubectl rollout restart deployment/ask-orchestrator -n onibex-ask`
3. Check as in step 4 above.

To turn asking back on, set the key to `true` or remove it: asking is on when the key is absent.

Why it works this way: the orchestrator reads `settings.json` once and keeps it in memory, so it
needs a restart (or `POST /v1/internal/reload` with a service token) to read the file again;
nothing is rebuilt or redeployed. In Kubernetes the file is mounted with `subPath`, which a
running pod never refreshes, so the pod has to restart. The switch only stops the chat from
asking: replies to greetings and similar messages, and the agent API, are not affected.

---

## Useful commands

```bash
# tail orchestrator logs
kubectl logs -n onibex-ask deployment/ask-orchestrator -f

# port-forward for local debugging
kubectl port-forward -n onibex-ask svc/ask-orchestrator-service 8080:80

# hit the orchestrator with a forged token (fails fast, useful to verify auth wiring)
curl -X POST http://127.0.0.1:8080/v1/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer fake.jwt.token" \
  -d '{"question":"how many open POs?","mode":"precise"}'
```

---

[← Back to the manual](../README.md)
