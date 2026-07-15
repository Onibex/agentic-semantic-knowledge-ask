# Installation & Running the Platform

> **Getting started.** Bring the full ASK Platform up on one machine with Docker and
> reach each of its user interfaces — **ASK Admin**, the **Chat**, and **ASK Setup** — plus the
> **Keycloak** admin console. This page keeps install depth light; the full per-service
> procedure is maintained by your platform / ops team.

| | |
|---|---|
| **Who** | Administrator / operator standing up an environment |
| **Time** | ~10 minutes (plus first-build time) |
| **Prerequisites** | **Docker** (with Docker Compose v2) installed and running; a shell at the repo root. |
| **You'll end with** | Every service healthy and each UI reachable in the browser, ready to configure. |

**Where this fits:** **Install — bring the stack up (you are here)** → Configure → Author → Publish → Ask

> This page only needs environment-variable **names**, never their secret values. The rest of
> the manual uses an illustrative **SAP Production Planning** example — substitute your own data.

---

## Concepts (30-second version)

- The platform is a **multi-service stack** started as one unit with **Docker Compose**. The
  compose file (`docker-compose.yml`) is the source of truth for the topology.
- **OpenSearch** and **Keycloak** are the backing services. **OpenSearch** stores both the
  knowledge graph / vectors **and** the encrypted configuration store (database connections and
  LLM providers). **Keycloak** is the identity provider.
- The three interfaces you use are separate **React single-page apps**, each on **its own host
  port**: **ASK Admin** (semantic-layer authoring), the **Chat** (natural-language querying), and
  **ASK Setup** (technical configuration). There is no shared login proxy and no path-routing —
  each app runs its own Keycloak sign-in.
- The SPAs are static bundles served by Nginx. Their auth posture and host address are **baked
  into the bundle at build time**, so changing `AUTH_MODE` or `EXTERNAL_HOST` means **rebuilding
  the SPA image** — a restart alone won't pick it up.
- A small set of **environment variables** in a `.env` file at the repo root parameterizes the
  stack — chiefly the encryption key, the semantic-layer repo path, the OpenSearch connection,
  and the auth posture. You set them once before the first `up`.

---

## 1. Prerequisites

- **Docker** with Docker Compose v2 (the `docker compose` subcommand). Confirm it's running:

  ```bash
  docker compose version
  ```

- A clone of the repository, and a shell opened at its root (the folder that contains
  `docker-compose.yml`).
- Outbound network access for the LLM / embedder provider you configure later (e.g. AWS Bedrock)
  and for your target database (e.g. SAP HANA Cloud). These are configured **after** first boot
  in **ASK Setup**, not here.

> **Tip — Docker vs native.** This page uses the Docker path (one command, everything in
> containers). If you'd rather run each service natively for active development, follow your
> platform's native-development runbook instead — it covers the venv setup and the native ports.

## 2. Create your `.env` file

The stack reads a `.env` file at the repo root. Copy the local template as a starting point and
edit the values in place:

```bash
cp .env.example .env
```

For a remote host (e.g. an EC2 dev box) use `.env.ec2.example` instead, which additionally
documents the host-port remaps.

Set the following variables **by name** — never paste real secret values into the manual or into
version control (`.env` is gitignored). Generate secrets with the one-liners the file documents.

| Variable | Required | What it is |
|---|---|---|
| **`ONIBEX_ENCRYPTION_KEY`** | Yes | Fernet master key (32-byte urlsafe-base64) that encrypts the **configuration store** in OpenSearch — database connections and LLM-provider credentials. Both backends **fail-closed at boot** if it's missing or malformed. Keep it **stable** — rotating it makes previously-stored secrets undecryptable. |
| **`SEMANTIC_LAYER_HOST_PATH`** | Yes | Absolute host path to your semantic-layer git repo. It is bind-mounted into `ask-admin-api` at `/app/semantic-layer`. **The directory must contain a `.git`** — without it, YAML commits become silent no-ops and publish-to-environment can't work. |
| **`AUTH_MODE`** | Yes | Auth backend: `keycloak` (local IdP), `xsuaa` (SAP BTP), or `none` (open dev). **Baked into the SPA bundles at build time** — changing it requires a SPA rebuild (see Step 6). |
| **`DEV_BYPASS_AUTH`** | Yes | `true` disables authentication (local convenience, honored only when `ENVIRONMENT=local`); `false` enforces `AUTH_MODE`. |
| **`OPENSEARCH_HOST`** | Yes | Host of the OpenSearch cluster. **Env-first** (the store's own connection can't live inside the store it holds). Inside the compose network this is the service name **`opensearch`** (the default) — no `settings.json` edit needed. It is shown **read-only** in ASK Setup. |
| **`OPENSEARCH_PORT`** | Yes | OpenSearch port — default `9200`. |
| **`OPENSEARCH_USE_SSL`** | Yes | `false` for the single-node dev cluster (its security plugin is disabled). |
| **`OPENSEARCH_USER` / `OPENSEARCH_PASSWORD`** | If secured | Credentials for a secured cluster; leave blank for the dev cluster. |
| **`EXTERNAL_HOST`** | For remote hosts | The host address the **browser** uses to reach the stack (no scheme, no port). Baked into the SPAs (their Keycloak URL and cross-app links) at build time; **defaults to `localhost`**. Set it — and rebuild the SPAs — when serving from a remote box. |
| **`EXECUTOR_EXTRAS`** | No (has default) | Which SQL drivers are baked into the `ask-orchestrator` and `ask-admin-api` images for multi-database support. Default `[snowflake,databricks,clickhouse,bigquery]`. Add `sqlserver` / `db2` only if the images carry the system ODBC/CLI libs. **Must match** across both services so a green connection Test means chat can actually connect. |
| `ASK_INGEST_API_KEY` | For M2M ingest | API key for the machine ingest endpoint (`POST /v1/ingest/*`). |
| `KC_ADMIN_USER` / `KC_ADMIN_PASSWORD` | If Keycloak | Keycloak admin-console login. |
| `OAUTH2_PROXY_COOKIE_SECRET` / `OAUTH2_PROXY_CLIENT_SECRET` | — | **Vestigial.** The old login proxy no longer exists in this stack; the SPAs authenticate against Keycloak directly (PKCE). These keys may linger in older `.env` templates — leave them blank and ignore them. |

> **Warning — the encryption key is not recoverable.** If you lose `ONIBEX_ENCRYPTION_KEY`, every
> encrypted credential in OpenSearch becomes unreadable and you must re-enter every provider and
> database secret. Save it somewhere safe the moment you generate it.

> **Warning — the semantic-layer path needs a real git repo.** If `SEMANTIC_LAYER_HOST_PATH`
> points at a directory with **no `.git`**, writes still land on disk but no history is recorded
> and publish-to-environment can't work. `git init` the directory first. See
> [Common gotchas](#common-gotchas) below.

## 3. Start the stack

From the repo root:

```bash
docker compose up -d
```

Compose builds the images on first run, then starts every service in the background. It brings
them up **in dependency order** — the backing services first, then the backends, then the SPAs:

1. **`opensearch`** — knowledge-graph / vector store **and** the encrypted config store.
   Everything with data depends on its healthcheck. **`keycloak`** — the identity provider —
   starts alongside it.
2. **`ask-orchestrator`** and **`ask-admin-api`** — the FastAPI backends; each waits for
   OpenSearch to report healthy.
3. **`ask-admin-spa`** (waits on the admin API), **`ask-chat-spa`** (waits on the orchestrator
   and the admin API), and **`ask-setup-spa`** (waits on the admin API) — the three React UIs.
   They are static Nginx bundles and talk to Keycloak from the **browser**, so they do **not**
   gate on Keycloak's healthcheck.
4. **`mcp-server`** — the internal endpoint for SAP write actions (port `4004`). **`teams-bot`**
   is opt-in and only wires a real channel once its Azure Bot credentials are set.

> **Tip — first boot is slow.** The image build and OpenSearch's initial cluster bootstrap take a
> few minutes. Services show `starting` until their healthchecks pass — that's expected.

## 4. Confirm everything is healthy

Check the container status:

```bash
docker compose ps
```

Every service publishes a healthcheck — wait until they report **healthy**. Tail a service's logs
if one stays unhealthy:

```bash
docker compose logs -f ask-orchestrator
```

![Terminal output of docker compose ps showing every ASK service Up and healthy](images/install-compose-ps.png)

The FastAPI backends also publish on host ports for their `/v1/health` endpoints and API traffic:
**`ask-orchestrator`** on `:8083` and **`ask-admin-api`** on `:8081` by default (remap with
`ORCH_HOST_PORT` / `ADMIN_API_HOST_PORT` if those clash with other software).

## 5. Reach each UI

Once the stack is healthy, open each interface in the browser. These URLs match the host-port
mappings in `docker-compose.yml`:

| Interface | URL | Served by | Notes |
|---|---|---|---|
| **ASK Admin** (React SPA) | `http://localhost:5173` | `ask-admin-spa` (Nginx) | Authoring: workspaces, domains, Data Products, dictionary, history. |
| **Chat** (React SPA) | `http://localhost:5174` | `ask-chat-spa` (Nginx) | Natural-language querying. |
| **ASK Setup** (React SPA) | `http://localhost:5175` | `ask-setup-spa` (Nginx) | Technical configuration: OpenSearch, database connections, LLM providers, identity. |
| **Keycloak** (admin console) | `http://localhost:8180` | `keycloak` | Identity-provider admin console (only relevant when auth is on). |

Each SPA runs its own Keycloak sign-in — there is no shared login proxy routing several apps
behind one port. Substitute your `EXTERNAL_HOST` for `localhost` when serving from a remote box.

![ASK Admin landing view in the browser at localhost:5173](images/install-ui-admin.png)

![Chat UI landing at localhost:5174](images/install-ui-chat.png)

![ASK Setup landing at localhost:5175](images/install-ui-setup.png)

If authentication is enabled (`DEV_BYPASS_AUTH=false`), the first visit to any SPA redirects
through the Keycloak login before landing on the UI.

![Keycloak login / admin console at localhost:8180](images/install-ui-keycloak.png)

## 6. Stop / rebuild

- **Stop** the stack (containers only; OpenSearch data and the semantic-layer repo are
  preserved):

  ```bash
  docker compose down
  ```

- **Rebuild** after a change. The backend packages are baked into the images at build time (there
  is no source bind-mount), and the SPAs bake their auth/host config (`AUTH_MODE`, `EXTERNAL_HOST`)
  into the bundle at build time — so a restart alone reuses the old image. Use the helper script:

  ```bash
  ./redeploy.sh
  ```

  It builds the images, force-recreates the containers, and prints `docker compose ps`. It does
  **not** touch volumes — for a destructive wipe run `docker compose down -v` yourself.

> **Tip — rebuild one service.** To rebuild just the SPA whose config you changed, scope the
> script: `ONLY=ask-setup-spa ./redeploy.sh` (or `ask-admin-spa` / `ask-chat-spa`). This is the
> step that makes an `AUTH_MODE` or `EXTERNAL_HOST` change take effect in the browser.

---

## Common gotchas

| Symptom | Cause & fix |
|---|---|
| First query returns nothing / OpenSearch connection refused inside a container | `OPENSEARCH_HOST` is wrong for the runtime. Inside Docker the store is reachable as the service name **`opensearch`** (the default) — not `localhost`. If you set `OPENSEARCH_HOST=localhost` in `.env` while running in containers, revert it to `opensearch` and restart. The value is **read-only** in ASK Setup; change it in `.env` (or a K8s Secret), not in the UI. |
| Backend aborts at boot with an encryption-key error | `ONIBEX_ENCRYPTION_KEY` is missing or malformed. The backends **fail-closed** by design. Generate a valid Fernet key, put it in `.env`, and restart. The **same** key must be used everywhere the encrypted store is read. |
| `docker compose up` fails with `SEMANTIC_LAYER_HOST_PATH variable is not set` | Add `SEMANTIC_LAYER_HOST_PATH=<absolute path>` to your `.env` before `up`. Compose fails fast so the mistake surfaces immediately instead of silently mounting an empty volume. |
| YAML edits save but never appear in history; publish-to-environment fails | The directory `SEMANTIC_LAYER_HOST_PATH` points at has **no `.git`**, or it has no `dev` / `prod` branches yet. On a from-zero deploy the repo isn't auto-initialized: `git init` it, make an initial commit, and ensure the `dev` and `prod` branches exist — publish-to-environment writes to those branches. |
| `AUTH_MODE` change has no effect in the browser | The SPAs bake `AUTH_MODE` (and `EXTERNAL_HOST`) into their bundle at build time. Rebuild the SPA image — `./redeploy.sh` (or `ONLY=<spa> ./redeploy.sh`) — a restart alone reuses the old bundle. |
| A database connection Test is green but chat can't query it | `EXECUTOR_EXTRAS` differs between `ask-admin-api` (which runs the Test) and `ask-orchestrator` (which runs chat), or the engine's driver isn't baked in. Set the **same** `EXECUTOR_EXTRAS` on both and rebuild. |
| Following an older runbook that expects a single shared login port with `/chat` and `/config` sub-paths | That layout belonged to the previous UI generation and its login proxy, both removed. Each React SPA now has its own port — ASK Admin `5173`, Chat `5174`, ASK Setup `5175`. |

> **Warning — first-boot config.** The database connections and provider credentials are **not**
> set by this install step. Configure them after the stack is up, in **ASK Setup**. Until a
> database connection is active and a provider is configured, chat queries won't resolve.

---

## What's next

→ **[ASK Setup](config/00-overview.md)** — set up the database connections, LLM providers, and
identity.
→ **[ASK Admin · Workspaces & Business Domains](ask-admin/01-workspaces-domains.md)** — create the
containers your data lives in.
→ **[ASK Admin · Add Data Products](ask-admin/02-add-data-products.md)** — author the entities the
agent maps questions to.
→ **Deployment runbook** (maintained by your platform / ops team) — the full per-service
procedure (native ports, venv setup, troubleshooting).
