# Installation & Running the Platform

> **Getting started.** Bring the full ASK Platform up on one machine with Docker and
> reach each of its user interfaces — **ASK Admin**, the **Chat**, the **Configuration app**,
> and **Keycloak**. This page keeps install depth light; the full per-service procedure is
> maintained by your platform / ops team.

| | |
|---|---|
| **Who** | Administrator / operator standing up an environment |
| **Time** | ~10 minutes (plus first-build time) |
| **Prerequisites** | **Docker** (with Docker Compose v2) installed and running; a shell at the repo root. |
| **You'll end with** | All services healthy and each UI reachable in the browser, ready to configure. |

**Where this fits:** **Install — bring the stack up (you are here)** → Configure → Author → Publish → Ask

> This page only needs environment-variable **names**, never their secret values. The rest of
> the manual uses an illustrative **SAP Production Planning** example — substitute your own data.

---

## Concepts (30-second version)

- The platform is a **multi-service stack** started as one unit with **Docker Compose**. The
  compose file (`docker-compose.yml`) is the source of truth for the topology.
- **OpenSearch** and **Keycloak** are the backing services; the four you interact with are
  **ASK Admin** (React SPA), the **Chat** UI, the **Configuration** app, and the **Keycloak**
  admin console.
- A small set of **environment variables** in a `.env` file at the repo root parameterizes the
  stack — chiefly the encryption key, the semantic-layer repo path, and the auth posture. You
  set them once before the first `up`.

---

## 1. Prerequisites

- **Docker** with Docker Compose v2 (the `docker compose` subcommand). Confirm it's running:

  ```bash
  docker compose version
  ```

- A clone of the repository, and a shell opened at its root (the folder that contains
  `docker-compose.yml`).
- Outbound network access for the LLM/embedder provider you configure later (e.g. AWS Bedrock)
  and for your target database (e.g. SAP HANA Cloud). These are configured **after** first boot
  via the Configuration app / ASK Admin, not here.

> **Tip — Docker vs native.** This page uses the Docker path (one command, everything in
> containers). If you'd rather run each service natively in its own terminal (for active
> development), follow your platform's native-development runbook instead —
> it covers the venv setup and the native ports.

## 2. Create your `.env` file

The stack reads a `.env` file at the repo root. Copy the EC2 example as a starting point and
edit the values in place:

```bash
cp .env.ec2.example .env
```

Set the following variables **by name** — never paste real secret values into the manual or into
version control (`.env` is gitignored). Generate secrets with the one-liners the file documents.

| Variable | Required | What it is |
|---|---|---|
| **`ONIBEX_ENCRYPTION_KEY`** | Yes | Fernet master key (32-byte urlsafe-base64) that encrypts provider credentials stored in OpenSearch. Both backends **fail-closed at boot** if it's missing or malformed. Keep it **stable** — rotating it makes previously-stored secrets undecryptable. |
| **`SEMANTIC_LAYER_HOST_PATH`** | Yes | Absolute host path to your semantic-layer git repo. It is bind-mounted into `ask-admin-api` at `/app/semantic-layer`. **The directory must contain a `.git`** — without it, YAML commits become silent no-ops. |
| **`AUTH_MODE`** | Yes | Auth backend: `keycloak` (local IdP), `xsuaa` (SAP BTP), or paired with the bypass below for open dev. |
| **`DEV_BYPASS_AUTH`** | Yes | `true` disables authentication (default local convenience); `false` enforces `AUTH_MODE`. |
| `OAUTH2_PROXY_COOKIE_SECRET` | If auth on | Session-cookie encryption key for oauth2-proxy (16/24/32 bytes, base64). |
| `OAUTH2_PROXY_CLIENT_SECRET` | If auth on | Must match the `oauth2-proxy` client secret in the Keycloak realm. |
| `KC_ADMIN_USER` / `KC_ADMIN_PASSWORD` | If Keycloak | Keycloak admin-console login. |
| `ASK_INGEST_API_KEY` | For M2M ingest | API key for the machine ingest endpoint. |

> **Warning — the encryption key is not recoverable.** If you lose `ONIBEX_ENCRYPTION_KEY`,
> every encrypted credential in OpenSearch becomes unreadable and you must re-enter every
> provider's secret. Save it somewhere safe the moment you generate it.

> **Warning — the semantic-layer path needs a real git repo.** If `SEMANTIC_LAYER_HOST_PATH`
> points at a directory with **no `.git`**, writes still land on disk but no history is recorded
> (`SEMANTIC_LAYER_NO_GIT`), and publish-to-environment can't work. `git init` the directory
> first. See [Common gotchas](#common-gotchas) below.

## 3. Start the stack

From the repo root:

```bash
docker compose up -d
```

Compose builds the images on first run, then starts every service in the background. It brings
them up **in dependency order** — the backing services first, then the backends, then the UIs and
the auth proxy:

1. **`opensearch`** — vector + knowledge-graph store. Everything else waits for its healthcheck.
2. **`keycloak`** — identity provider (its own healthcheck gates the auth proxy).
3. **`ask-orchestrator`** and **`ask-admin-api`** — the FastAPI backends; each depends on
   OpenSearch being healthy.
4. **`ask-admin-spa`** — the React admin UI (depends on the admin API).
5. **`app-chat`** and **`app-config`** — the Streamlit UIs (depend on the backends).
6. **`oauth2-proxy`** — fronts the two Streamlit UIs behind a single login (depends on Keycloak +
   both UIs).

> **Tip — first boot is slow.** The image build and OpenSearch's initial cluster bootstrap take a
> few minutes. Services will show `starting` until their healthchecks pass — that's expected.

## 4. Confirm everything is healthy

Check the container status:

```bash
docker compose ps
```

Wait until the backing services and backends report **healthy** (they carry healthchecks;
`ask-orchestrator`, `ask-admin-api`, `opensearch`, and `keycloak` all publish one). Tail a
service's logs if one stays unhealthy:

```bash
docker compose logs -f ask-orchestrator
```

![Terminal output of `docker compose ps` showing every ASK service Up and the backends healthy](images/install-compose-ps.png)

## 5. Reach each UI

Once the stack is healthy, open each interface in the browser. These URLs match the host-port
mappings in `docker-compose.yml`:

| Interface | URL | Served by | Notes |
|---|---|---|---|
| **ASK Admin** (React SPA) | `http://localhost:5173` | `ask-admin-spa` (Nginx) | Authoring: workspaces, domains, Data Products, dictionary, history. |
| **Chat** | `http://localhost:8500/chat` | `app-chat` via `oauth2-proxy` | Natural-language querying. Behind the auth proxy — **no direct host port**. |
| **Configuration app** | `http://localhost:8500/config` | `app-config` via `oauth2-proxy` | Technical setup (DB, providers, connections). Same proxy, one login. |
| **Keycloak** (admin console) | `http://localhost:8180` | `keycloak` | Identity provider admin console (only relevant when auth is on). |

> **Note — the Streamlit UIs have no direct port.** `app-chat` and `app-config` only `expose`
> their internal port; they are reached **exclusively** through `oauth2-proxy` on port `8500`
> (path-routed `/chat` and `/config`), so they can't be hit unauthenticated. The ports `:8501`
> and `:8502` you may see in the native-development runbook are the **native**
> (non-Docker) Streamlit ports — they do **not** apply to the Docker stack.

![ASK Admin landing view in the browser at localhost:5173](images/install-ui-admin.png)

![Chat UI landing at localhost:8500/chat](images/install-ui-chat.png)

![Configuration app landing at localhost:8500/config](images/install-ui-config.png)

If authentication is enabled (`DEV_BYPASS_AUTH=false`), the first visit to `/chat` or `/config`
redirects through the Keycloak login before landing on the UI.

![Keycloak login / admin console at localhost:8180](images/install-ui-keycloak.png)

## 6. Stop / rebuild

- **Stop** the stack (containers only; OpenSearch data and the semantic-layer repo are
  preserved):

  ```bash
  docker compose down
  ```

- **Rebuild** after a code change — the backend packages are baked into the images at build
  time (there is no source bind-mount for them), so a restart alone reuses the old image. Use the
  helper script:

  ```bash
  ./redeploy.sh
  ```

  It builds the images, force-recreates the containers, and prints `docker compose ps`. It does
  **not** touch volumes — for a destructive wipe run `docker compose down -v` yourself.

---

## Common gotchas

| Symptom | Cause & fix |
|---|---|
| First query returns nothing / OpenSearch connection refused inside a container | On first boot `config/settings.json` may still say `opensearch.host = "localhost"`. Inside Docker the store is reachable as the service name **`opensearch`**, not `localhost`. Open **Configuration app → Setup** and set the OpenSearch host to `opensearch`, then restart the affected backend so it drops the cached singleton. |
| Backend aborts at boot with an encryption-key error | `ONIBEX_ENCRYPTION_KEY` is missing or malformed. The backends **fail-closed** by design. Generate a valid Fernet key, put it in `.env`, and restart. The **same** key must be used everywhere the encrypted store is read. |
| `docker compose up` fails with `SEMANTIC_LAYER_HOST_PATH variable is not set` | Add `SEMANTIC_LAYER_HOST_PATH=<absolute path>` to your `.env` before `up`. Compose fails fast so the mistake surfaces immediately instead of silently mounting an empty volume. |
| YAML edits save but never appear in history; publish-to-env fails | The directory `SEMANTIC_LAYER_HOST_PATH` points at has **no `.git`**. `git init` it (and make an initial commit) — the platform needs a real git repo to record and publish semantic-layer changes. |
| `/chat` or `/config` won't load / can't be reached directly on a port | Those UIs have no direct host port; reach them only through `http://localhost:8500/chat` and `http://localhost:8500/config`. |

> **Warning — first-boot config.** The `opensearch.host` value and the provider credentials are
> **not** set by this install step. Configure them after the stack is up (Configuration app /
> ASK Admin). Until OpenSearch host is correct and a provider is configured, chat queries won't
> resolve.

---

## What's next

→ **[Configuration app](config/configuration-app.md)** — set up providers, the database, and
the search index.
→ **[ASK Admin · Workspaces & Business Domains](ask-admin/01-workspaces-domains.md)** — create the
containers your data lives in.
→ **[ASK Admin · Add Data Products](ask-admin/02-add-data-products.md)** — author the entities the
agent maps questions to.
→ **Deployment runbook** (maintained by your platform / ops team) — the full per-service
procedure (native ports, venv setup, troubleshooting).
