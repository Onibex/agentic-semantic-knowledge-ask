# Kafka Connect HTTP Sink → /v1/ingest/sap-json

The ASK Admin API exposes a machine-to-machine ingestion endpoint that is
designed to be consumed by Kafka Connect HTTP Sink connectors (Confluent,
Lenses, Aiven) and similar agents such as IBM Watson X webhooks. The
endpoint accepts an SAP metadata JSON payload, parses it into Bronze +
Silver ASK YAMLs, writes them to the workspace, and indexes the catalog
in OpenSearch — exactly the same operation ASK Studio performs,
just behind a different auth dependency.

## Endpoint

```
POST /v1/ingest/sap-json
Host: <admin-api-host>
Authorization:    (none)
X-API-Key:        <static secret>
Content-Type:     application/json

Body: {"data": <SAP metadata JSON>}
```

Response (200):

```json
{
  "entities_indexed": 12,
  "fields_indexed":   84,
  "edges_indexed":    9,
  "error":            null
}
```

| Status | Meaning |
|---|---|
| 200 | Ingestion succeeded; counts in body. |
| 401 | `X-API-Key` missing or wrong. **Do NOT retry — fix the secret.** |
| 503 | Server has no API key configured. **Safe to retry**; Kafka Connect will redeliver until the secret is mounted. |
| 500 | Server-side ingestion error. Retryable. |

## Auth: API key in a custom HTTP header

The endpoint compares the inbound `X-API-Key` header against the
`ASK_INGEST_API_KEY` environment variable using a constant-time compare
(`hmac.compare_digest`). There is no token exchange, no OAuth2 flow, no
JWT validation — that is the entire point: Kafka Connect cannot perform
those flows reliably.

### Generating a key

```bash
openssl rand -hex 32
# → e.g. 5c3e8a... 64 hex chars
```

### Provisioning the secret in Kubernetes (production)

```bash
kubectl create secret generic ask-ingest-api-key \
  --from-literal=ASK_INGEST_API_KEY="$(openssl rand -hex 32)" \
  -n <your-namespace>
```

Then mount it into the `ask-admin-api` Deployment:

```yaml
env:
  - name:  ASK_INGEST_API_KEY
    valueFrom:
      secretKeyRef:
        name: ask-ingest-api-key
        key:  ASK_INGEST_API_KEY
```

### Local development

In `.env` (or `docker-compose.yml`):

```bash
ASK_INGEST_API_KEY=dev-local-key-change-me
```

The default compose file ships with this placeholder so a fresh
`docker compose up` works end-to-end.

## Kafka Connect HTTP Sink configuration

The exact property names vary between connectors. Examples below cover
the most common implementations.

### Confluent / Lenses HTTP Sink

```properties
name=ask-ingest-sap-json
connector.class=io.confluent.connect.http.HttpSinkConnector
topics=sap.metadata.dumps

http.api.url=https://admin.ask.example.com/v1/ingest/sap-json
http.request.method=POST
http.request.body.format=json
request.body.json.root=data        # wraps the topic value as {"data": ...}

# Auth — header injection
http.headers=X-API-Key:${secrets:ingest-api-key}|Content-Type:application/json
headers.separator=|

# Retry policy — 5xx + transient errors only
behavior.on.errors=retry
max.retries=10
retry.backoff.ms=5000
```

If the connector does not provide a `request.body.json.root` option,
prepend a Single Message Transform that wraps the payload:

```properties
transforms=Wrap
transforms.Wrap.type=org.apache.kafka.connect.transforms.HoistField$Value
transforms.Wrap.field=data
```

### Aiven HTTP Sink

```properties
name=ask-ingest-sap-json
connector.class=io.aiven.kafka.connect.http.HttpSinkConnector
topics=sap.metadata.dumps

http.url=https://admin.ask.example.com/v1/ingest/sap-json
http.headers.additional=X-API-Key:${ingest-api-key};Content-Type:application/json
http.authorization.type=NONE
```

### Watson X (Key Value Pair custom headers)

Watson X webhook/HTTP action settings expose a **"Custom Headers"** or
**"Key Value Pair"** form. Add:

| Key         | Value                                |
|-------------|--------------------------------------|
| `X-API-Key` | `<paste the openssl-generated key>`  |
| `Content-Type` | `application/json`                |

Method: `POST`. URL: `https://admin.ask.example.com/v1/ingest/sap-json`.
Body template: the SAP JSON wrapped inside `{"data": ...}`.

## Smoke test with curl

```bash
# Local docker-compose default key
curl -X POST http://localhost:8081/v1/ingest/sap-json \
  -H "X-API-Key: dev-local-key-change-me" \
  -H "Content-Type: application/json" \
  -d @sap_metadata.json
```

Negative path (wrong key):

```bash
curl -i -X POST http://localhost:8081/v1/ingest/sap-json \
  -H "X-API-Key: bogus" \
  -H "Content-Type: application/json" \
  -d '{"data": {}}'
# HTTP/1.1 401 Unauthorized
```

## Operational notes

- **TLS in production.** API key auth is only safe over HTTPS. Terminate
  TLS at your ingress / reverse proxy — never expose the endpoint over
  plain HTTP outside `localhost`.
- **Rotation.** Update the Kubernetes Secret + restart the deployment, then
  switch the consumer-side credential. Two-step rollover is not yet
  supported (`ASK_INGEST_API_KEYS` plural list is a future enhancement).
- **Auditing.** Every request to `/v1/ingest/*` is logged with
  `auth_method=api_key` and `principal=kafka-connect`. Filter your log
  aggregator by these fields to separate machine traffic from human
  admin traffic.
- **Rate limits.** None enforced today. If a connector misbehaves and
  bursts, throttle at the ingress until proper rate limiting is added.
