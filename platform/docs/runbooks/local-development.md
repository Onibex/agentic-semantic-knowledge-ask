# Local development

[Manual](../README.md) › [Operating the platform](../README.md#operating-the-platform) › **Local development**

> **How to.** Run the services natively instead of in Docker, on Windows and PowerShell.
> **Source of truth:** [`docker-compose.yml`](../../docker-compose.yml). This guide reproduces the same multi-service topology (2 Python services + 3 React SPAs + OpenSearch + optional Keycloak), but with each service booted natively instead of in a container.
> **Linux/macOS:** bash equivalents at the end. **Docker fallback:** `docker compose up -d` if you'd rather skip the venv setup (see [`docker-compose.yml`](../../docker-compose.yml)).

---

## Architecture summary

The platform runs as 2 Python services + 3 React SPAs, backed by OpenSearch + SAP HANA Cloud + SAP AI Core:

```
                        ┌────────────────────────────────────────┐
                        │ External backends                      │
                        │  - OpenSearch        (local, 9200)     │
                        │  - SAP HANA Cloud    (cloud)           │
                        │  - SAP AI Core       (cloud, via SDK)  │
                        │  - Keycloak (optional, local, 8180)    │
                        └───────────┬────────────────────────────┘
                                    │
                 ┌──────────────────┴───────────────────┐
        ┌────────┴─────────┐                   ┌────────┴─────────┐
        │ ask-orchestrator │                   │ ask-admin-api    │
        │ FastAPI :8080    │                   │ FastAPI :8081    │
        │ /v1/health       │                   │ /v1/health       │
        │ /v1/query        │                   │ /v1/admin/*      │
        │ /v1/profile      │                   │ /v1/viz/*        │
        │ /external/*      │                   └──┬────────────┬──┘
        └────────┬─────────┘                      │            │
                 │ HTTP                      HTTP │            │ HTTP
        ┌────────┴─────────┐          ┌───────────┴────┐  ┌────┴───────────┐
        │ ask-chat-spa     │          │ ask-studio-spa  │  │ ask-setup-spa  │
        │ React + Nginx    │          │ React + Nginx  │  │ React + Nginx  │
        │ :5174            │          │ :5173          │  │ :5175          │
        │ chat + artifacts │          │ semantic layer │  │ technical setup│
        └──────────────────┘          └────────────────┘  └────────────────┘
             (the chat SPA also calls the admin API for the workspace list)
```

**10 typed packages** live under `packages/` (installed editable into the venv); all pipeline code lives there and the SPAs are thin REST clients. The **Studio SPA** is the write path for Workspaces / Organization / Data Products / AI Enrichment; the **setup SPA** owns the technical configuration plane (DB connections, LLM + embedder providers, identity provider, encrypted secrets).

| Service | Module | Port | What it does |
|---|---|---|---|
| `opensearch` | external | 9200 | Vector + KG store; also hosts `ask-system-settings-v1` (encrypted secrets) and `ask-workspaces-v1` |
| `keycloak` | external (optional) | 8180 | Local IdP for the SPAs when `VITE_AUTH_MODE=keycloak`. Skip in pure dev. |
| `ask-orchestrator` | `ask_orchestrator.main:app` | 8080 | Chat backend (intent → SQL → exec) |
| `ask-admin-api` | `ask_admin_api.main:app` | 8081 | Admin backend (dictionary, KG ingestion, embeddings, secrets, prompts, enrichment, workspaces, organization) |
| `ask-studio-spa` | `ask-studio-spa/` (Vite dev or Nginx) | 5173 | ASK Studio. Workspaces, Organization, YAML editor + AI Assist, docs ingestion |
| `ask-chat-spa` | `ask-chat-spa/` (Vite dev or Nginx) | 5174 | React chat UI. Chat (streaming), Artifacts gallery + creator |
| `ask-setup-spa` | `ask-setup-spa/` (Vite dev or Nginx) | 5175 | React setup UI: database connections, LLM/embedder providers, identity provider, SAP connection, MCP, contracts |

---

## Pre-requisites

### Backends running locally

- **OpenSearch** at `localhost:9200`. Verify:
  ```powershell
  curl.exe -s http://localhost:9200/_cluster/health
  ```
  Expected: `{"cluster_name":"...","status":"green"|"yellow",...}`
- **SAP HANA Cloud** reachable (or PostgreSQL if `db_type` is `postgresql` in `config/settings.json`).
- **SAP AI Core** credentials at the path declared by `sap_ai_core.config_path` in `config/settings.json` (typically `config/aicore_config.json`).

### Paths in this runbook

Every command below runs from `platform/`, so set this once per shell and the
rest copy-pastes unchanged:

```powershell
# The platform/ directory of YOUR checkout — adjust to wherever you cloned it.
$PLATFORM = "C:\src\agentic-semantic-knowledge-ask\platform"
```

```bash
# Git Bash / WSL equivalent
PLATFORM=/c/src/agentic-semantic-knowledge-ask/platform
```

One more path is yours to choose: the **semantic-layer git repo** the platform reads
and commits to. It is a separate repository from this one, create it wherever you
like and refer to it as `$SEMANTIC_LAYER` below.

```powershell
$SEMANTIC_LAYER = "C:/src/semantic-layer-s4h"   # forward slashes: it also goes into .env
```

### Local environment

- Python 3.12 venv at `$PLATFORM\venv` (see **Paths in this runbook** below)
- `uv` installed (used by the project for fast pip operations)
- Windows Terminal (`wt`) recommended for managing 4+ tabs

### `config/settings.json`

The repo's `config/settings.json` is committed with cluster DNS hostnames. For local dev, override `opensearch.host` to `localhost`:

```json
{
  "opensearch": { "host": "localhost", "port": 9200, ... },
  ...
}
```

> Do **not** commit your local override.

### Semantic-layer repo (required for `ask-admin-api`)

The semantic-layer YAMLs (Bronze / Silver / Gold) live in a **separate git
repository** from this codebase, so YAML history never mixes with feature
commits. The admin-api fail-closes at boot if `REPO_ROOT` / `WORKSPACE_PATH`
aren't set, so you must wire them to the on-disk path of that repo.

#### 1. Create the external repo once

```powershell
mkdir $SEMANTIC_LAYER
cd $SEMANTIC_LAYER
git init
git config user.email "viz-bot@onibex.com"
git config user.name  "viz-bot"
# (optional) seed with your existing YAMLs:
#   Copy-Item -Recurse <your-existing-workspace>\ask\* .
git add .
git commit -m "initial semantic-layer import"
```

The repo holds:

```
semantic-layer-s4h/
├── .git/                  ← own history, independent of agentic-ai/
├── .sap_baseline/         ← SAP-baseline + conflict + enrichment sidecars
├── bronze/
├── silver/{sd,mm,pp,fi}/
└── gold/
```

> One repo per SAP system. If you also work on ECC, repeat with a second checkout
> (`semantic-layer-ecc`) and point `$SEMANTIC_LAYER` at whichever one you are using.

#### 2. Set the env vars in `.env` (or per terminal)

```
REPO_ROOT=$SEMANTIC_LAYER
WORKSPACE_PATH=$SEMANTIC_LAYER
```

Forward slashes work on Windows under Python. Both vars usually point at the
same directory; they're kept separate so you can put non-YAML files
(`README.md`, `scripts/`, etc.) in the repo without the YAML glob picking
them up.

> The admin-api **refuses to boot** if `REPO_ROOT` or `WORKSPACE_PATH` is
> empty (`SEMANTIC_LAYER_PATHS_MISSING`). If the directory has no `.git`,
> it warns and continues, commits become no-ops.
>
> **Pending decisions** around this manual step (auto-`git init` on a from-zero
> docker-compose? + clarifying that commit authorship comes from the logged-in
> Keycloak user, not the `git config user.*` above) are tracked in an internal
> design doc (SEMANTIC_LAYER_GIT_PENDING).

#### 3. Docker users

`docker-compose.yml` reads `SEMANTIC_LAYER_HOST_PATH` from your `.env` and
bind-mounts that directory into `/app/semantic-layer` inside the admin-api
container. Inside the container, `REPO_ROOT` / `WORKSPACE_PATH` are wired to
`/app/semantic-layer`.

Add to your host `.env`:

```
SEMANTIC_LAYER_HOST_PATH=$SEMANTIC_LAYER
```

`docker compose up` fails fast with a helpful error if the variable is
missing, so a forgotten `.env` line surfaces immediately instead of
silently mounting an empty volume.

### Encrypted-secrets master key (required)

Both `ask-orchestrator` and `ask-admin-api` fail-closed at boot if `ONIBEX_ENCRYPTION_KEY` is missing or malformed, the new Fernet-encrypted secrets store (`ask-system-settings-v1` in OpenSearch) is the canonical home for LLM + Embedder credentials.

Generate it once:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Output: 32-byte urlsafe-base64 string, e.g. vNqLqVz7K8x4Hj_pUe6CzWtRgsT1mF9bN0kQrSvU8wE=
```

Two options for making the value visible to uvicorn:

**Option A. Per-terminal env var (matches the rest of this runbook):**
Export `$env:ONIBEX_ENCRYPTION_KEY` in every terminal that boots orchestrator or admin-api (see terminals 1 and 2 below).

**Option B, the `.env` file in `platform/`:**
Add the line to your local `.env`:

```
ONIBEX_ENCRYPTION_KEY=<paste-the-generated-value-here>
```

Then load it before uvicorn (PowerShell):

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#=]+?)\s*=\s*(.+?)\s*$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
    }
}
```

> **Save the key somewhere safe.** If you lose it, every encrypted api_key in OpenSearch becomes unrecoverable and you have to re-enter every provider's credentials via the SPA. `.env` is gitignored, don't commit it.

### (Optional) Migrate existing `settings.json` secrets

If your current `config/settings.json` has `llm` / `embedder` sections with provider credentials, run the one-shot migration to move them into the encrypted OpenSearch doc (skip this on a fresh dev machine. You can configure everything via the SPA's Setup page instead):

```powershell
python scripts\migrate_secrets_to_opensearch.py
```

Idempotent, re-runs are no-ops once the doc exists.

---

## 1. Setup once (fresh venv)

```powershell
cd $PLATFORM

# Point uv at the project's venv (uv requires this hint when no .venv is auto-detected).
$env:VIRTUAL_ENV = "$PLATFORM\venv"

# Install third-party deps shared across the platform.
uv pip install -r requirements.txt

# Install all 10 typed packages editable. Order: leaf-first (matches Dockerfiles).
foreach ($pkg in 'ask-llm-gateway','ask-knowledge-graph',
                  'ask-intent-resolution','ask-sql-generation','ask-sql-executor',
                  'ask-schema-service','ask-docs-service','ask-action-execution',
                  'ask-admin-api','ask-orchestrator') {
    uv pip install -e "packages/$pkg"
}
```

### Verify all 10 packages import cleanly

```powershell
python -c @"
import ask_orchestrator, ask_admin_api, ask_intent_resolution, ask_sql_generation
import ask_sql_executor, ask_knowledge_graph, ask_schema_service, ask_docs_service
import ask_llm_gateway, ask_action_execution
print('10/10 packages importable')
"@
```

### One-time PowerShell execution policy (if scripts are blocked)

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

---

## 2. Boot the Orchestrator (chat backend, FastAPI :8080)

**Terminal 1:**

```powershell
cd $PLATFORM
.\venv\Scripts\Activate.ps1

# Auth bypass (only honoured when ENVIRONMENT == "local").
$env:ENVIRONMENT = "local"
$env:DEV_BYPASS_AUTH = "true"

# Required — Fernet master key. The orchestrator aborts at boot if missing/malformed.
$env:ONIBEX_ENCRYPTION_KEY = "<paste-the-generated-value-here>"

# Windows-safe stdout. Without this, prints with emojis crash on cp1252.
$env:PYTHONIOENCODING = "utf-8"

python -m uvicorn ask_orchestrator.main:app --host 127.0.0.1 --port 8080 --reload
```

### Verify

```powershell
curl.exe http://127.0.0.1:8080/v1/health
# Expected: {"status":"ok"}
```

OpenAPI docs: **http://127.0.0.1:8080/docs**

---

## 3. Boot the Admin API (admin backend, FastAPI :8081)

**Terminal 2:**

```powershell
cd $PLATFORM
.\venv\Scripts\Activate.ps1

$env:ENVIRONMENT = "local"
$env:DEV_BYPASS_AUTH = "true"
$env:ONIBEX_ENCRYPTION_KEY = "<paste-the-generated-value-here>"
$env:PYTHONIOENCODING = "utf-8"

# Required — semantic-layer repo (admin-api fail-closes if either is empty).
$env:REPO_ROOT      = "$SEMANTIC_LAYER"
$env:WORKSPACE_PATH = "$SEMANTIC_LAYER"

python -m uvicorn ask_admin_api.main:app --host 127.0.0.1 --port 8081 --reload
```

### Verify

```powershell
curl.exe http://127.0.0.1:8081/v1/health
# Expected: {"status":"ok"}
```

OpenAPI docs: **http://127.0.0.1:8081/docs**

The admin-api owns dictionary CRUD, YAML ingestion, embeddings management, and the internal `/v1/internal/reload` endpoint the setup SPA triggers after every configuration save.

---

## 4. Boot the Chat SPA (`ask-chat-spa`, :5174)

**Terminal 3:**

```powershell
cd $PLATFORM\ask-chat-spa

# One-time install of npm deps.
npm install

# Dev server with HMR.
# The Vite proxy rewrites:
#   /api/orchestrator/* → http://localhost:8080/v1/*   (orchestrator — required)
#   /api/admin/*        → http://localhost:8081/v1/admin/*  (admin-api — needed for workspace list)
npm run dev
```

→ Browser: **http://localhost:5174**

**Dependencies:**
- Orchestrator (Terminal 1, port 8080) **must** be running, the chat page and artifact generator both call `/v1/query` and `/v1/artifact`.
- Admin API (Terminal 2, port 8081) is needed for the workspace dropdown in the sidebar (fetches `/v1/admin/workspaces`). The app still loads without it, but workspace selection will fail.

**No `.env.local` needed** in pure dev, the Vite proxy handles all API routing and there is no auth mode to configure for the chat SPA.

Pages available:

| Route | What it does |
|---|---|
| `/` | Home: orchestrator health, active workspace/env/mode status, navigation |
| `/chat` | Chat: streaming responses, auto-charts, per-workspace conversation history (persisted in `localStorage`) |
| `/artifacts` | Artifacts: chat-based creator (name → purpose → data focus → format), gallery, viewer with inline edit panel + SQL override |

**TypeScript check (no build needed):**

```powershell
npm run typecheck
# Expected: no output (zero errors)
```

**Production build (static assets, output to `dist/`):**

```powershell
npm run build
# Preview the build locally:
npm run preview   # → http://localhost:4173
```

---

## 5. Boot the Admin SPA (`ask-studio-spa`, :5173)

**Terminal 4:**

```powershell
cd $PLATFORM\ask-studio-spa

# One-time install of npm deps (only the first time).
npm install --legacy-peer-deps

# Dev server with HMR. The Vite proxy points /api → http://127.0.0.1:8081 (admin-api),
# so the SPA and admin-api must be co-running.
npm run dev
```

→ Browser: **http://localhost:5173**

**Auth mode:** default `dev` (no Keycloak). Set `VITE_AUTH_MODE=keycloak` in `ask-studio-spa/.env.local` if you want the real login flow + a local Keycloak (see `docker-compose.yml` for the `keycloak` service on port 8180).

Pages available:

| Route | What it does |
|---|---|
| `/getting-started` | In-product on-ramp for a fresh install |
| `/workspaces` | Workspaces + Business Domains + Data Products (rail + cards home) |
| `/workspaces/:slug/domains/:bdSlug` | Domain canvas, the per-Business-Domain graph |
| `/semantic-knowledge` | Global Data Product catalog with **AI Assist** enrichment (per-entity diff preview) |
| `/organization` | Singleton Organization profile (company name, SAP version, core modules) |
| `/history` | Git history per YAML (Monaco DiffEditor) |
| `/graph` | Lineage graph (global fallback view) |
| `/health` | Backend health panel |
| `/admin/docs` | Documentation ingestion into the RAG index |
| `/admin/setup` | Read-only effective config (LLM / Embedder / OpenSearch) |

> Regenerating the OpenAPI-typed client: `cd ask-studio-spa && npm run generate-api:file`, reads `http://127.0.0.1:8081/openapi.json` and writes `src/api/generated.ts`.

---

## 6. Boot the Setup SPA (`ask-setup-spa`, :5175)

**Terminal 5:**

```powershell
cd $PLATFORM\ask-setup-spa

# One-time install of npm deps (only the first time).
npm install

# Dev server with HMR. The Vite proxy points /api/admin → http://127.0.0.1:8081 (admin-api),
# so the SPA and admin-api must be co-running.
npm run dev
```

→ Browser: **http://localhost:5175**

This is the technical-configuration plane: it writes the encrypted secrets store and the
DB / LLM / identity configuration the two backends read.

Pages available:

| Route | What it does |
|---|---|
| `/setup` | Effective configuration overview (env-sourced OpenSearch + active providers) |
| `/database` | Database connection registry (N connections, one active per environment) |
| `/llm-providers` | LLM + embedder providers (one active), encrypted-credentials write path |
| `/identity` | Identity-provider settings |
| `/sap-connection` | S/4HANA connection wizard |
| `/mcp-server` | MCP server config |
| `/contracts` | OpenAPI contract → MCP tools registry |

---

## URL summary

| Service | URL | Terminal |
|---|---|---|
| Orchestrator API | http://127.0.0.1:8080 | 1 |
| Orchestrator OpenAPI | http://127.0.0.1:8080/docs | 1 |
| Orchestrator health | http://127.0.0.1:8080/v1/health | 1 |
| Admin API | http://127.0.0.1:8081 | 2 |
| Admin OpenAPI | http://127.0.0.1:8081/docs | 2 |
| Admin health | http://127.0.0.1:8081/v1/health | 2 |
| Chat SPA | http://localhost:5174 | 3 |
| Admin SPA | http://localhost:5173 | 4 |
| Setup SPA | http://localhost:5175 | 5 |

---

## Smoke (with both backends running)

```powershell
cd $PLATFORM
.\venv\Scripts\Activate.ps1

$env:ASK_ORCHESTRATOR_URL = "http://127.0.0.1:8080"
$env:ASK_ORCHESTRATOR_TIMEOUT = "300"

python -m pytest tests\e2e\test_smoke.py -v
```

Expected: **5 passed in ~56s** (health + openapi + 3 modes against HANA).

---

## Per-package unit tests (no backends needed)

```powershell
cd $PLATFORM
.\venv\Scripts\Activate.ps1

foreach ($pkg in 'ask-orchestrator','ask-admin-api','ask-intent-resolution',
                  'ask-sql-generation','ask-sql-executor','ask-knowledge-graph',
                  'ask-schema-service','ask-docs-service','ask-llm-gateway',
                  'ask-action-execution') {
    Write-Host "=== $pkg ===" -ForegroundColor Cyan
    Push-Location "packages\$pkg"
    python -m pytest tests\unit -q --no-header 2>&1 | Select-Object -Last 2
    Pop-Location
}
```

```powershell
# Boundary tests (no imports of modules removed by earlier refactors)
python -m pytest tests\boundary -v

# import-linter (architectural contracts)
.\venv\Scripts\lint-imports.exe
```

---

## Stop / cleanup

Each terminal: `Ctrl+C` (uvicorn / Vite) or close the window.

If a process is hung on a port:

```powershell
# Find PID listening on a given port
Get-NetTCPConnection -LocalPort 8080 -State Listen | Select-Object OwningProcess

# Kill it
Stop-Process -Id <PID> -Force

# Or one-liner that kills whatever is on a port:
Get-NetTCPConnection -LocalPort 8081 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

---

## Gotchas

| Problem | Fix |
|---|---|
| `ENCRYPTION_KEY_MISSING: set ONIBEX_ENCRYPTION_KEY in the environment` at boot | Set `$env:ONIBEX_ENCRYPTION_KEY` BEFORE uvicorn. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. The same key MUST be exported in every terminal that boots orchestrator or admin-api. They share the encrypted store. |
| `ENCRYPTION_KEY_INVALID_FORMAT` at boot | The value isn't a Fernet key (32-byte urlsafe-b64). Regenerate with the one-liner above and re-export. |
| `ENCRYPTION_KEY_MISMATCH` on `/v1/query` | The OpenSearch doc was encrypted with a different master key than the current one. Either restore the previous key, or wipe the `ask-system-settings-v1` index and re-enter credentials via the SPA. |
| `SEMANTIC_LAYER_PATHS_MISSING` at admin-api boot | Set `REPO_ROOT` and `WORKSPACE_PATH` in the admin-api terminal (typically the same value. See §Pre-requisites → Semantic-layer repo). |
| `SEMANTIC_LAYER_PATHS_INVALID` at admin-api boot | The path is set but doesn't exist or isn't a directory. Verify it on disk; remember forward slashes are fine on Windows. |
| `SEMANTIC_LAYER_NO_GIT` warning + commits look no-op | `git init` inside the directory `REPO_ROOT` points to. Until then YAML writes still persist to disk but no history is recorded. |
| Docker fails with `SEMANTIC_LAYER_HOST_PATH variable is not set` | Add `SEMANTIC_LAYER_HOST_PATH=$SEMANTIC_LAYER` to host `.env` before `docker compose up`. |
| `'charmap' codec can't encode ...` in logs | `$env:PYTHONIOENCODING = "utf-8"` BEFORE starting uvicorn |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | One-time: `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` |
| `lint-imports.exe` not found | Make sure the venv is active (`.\venv\Scripts\Activate.ps1`) |
| `config/settings.json not found` on uvicorn boot | Run `uvicorn` from **`platform/`**, NOT from `packages\<pkg>\`. Same applies to the integration tests inside each package. |
| Chat hangs waiting for a response | Verify the orchestrator (T1) is up at `:8080` and that the chat SPA's Vite proxy is running |
| OpenSearch connection refused | `Test-NetConnection localhost -Port 9200` to confirm it's listening |
| Setup save doesn't refresh the orchestrator's cached config | The admin-api broadcasts `/v1/internal/reload`; make sure `ASK_ORCHESTRATOR_URL` is exported in the **admin-api** terminal so the broadcast reaches the chat backend |
| Port already in use after killed run | Use the `Get-NetTCPConnection` one-liner above to free 8080/8081/5173/5174/5175 |
| SPA shows `Network Error` on every call | The Vite proxy needs admin-api up; check terminal 2 + that `VITE_API_BASE_URL` (if set in `.env.local`) matches `http://127.0.0.1:8081` |
| SPA login redirects to Keycloak but you don't have it running | Either start the `keycloak` docker-compose service (`docker compose up -d keycloak`) or set `VITE_AUTH_MODE=dev` in `ask-studio-spa/.env.local` |
| Chat SPA (`ask-chat-spa`) shows blank page or 502 on `/api/orchestrator/*` | Orchestrator (T1) must be up at `:8080`. The Vite proxy for the chat SPA only works while `npm run dev` is running. The proxy is not active in the production build. |
| Chat SPA workspace dropdown is empty | Admin API (T2) at `:8081` is needed to fetch `/v1/admin/workspaces`. Start it or create a workspace first via ASK Studio at `:5173`. |
| Port 5174 already in use | `Get-NetTCPConnection -LocalPort 5174 -State Listen \| ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }` |
| `npm install` fails in `ask-chat-spa` with peer-dep errors | Run `npm install --legacy-peer-deps` instead of plain `npm install`. |
| `&&` doesn't work in PowerShell 5.1 | Use `;` for unconditional chain or `if ($?) { ... }` for conditional |
| `uv pip install` complains "no virtualenv" | Set `$env:VIRTUAL_ENV` to the venv path before invoking uv |

---

## Tip: launch all services with a single Windows Terminal command

If you have Windows Terminal (`wt.exe`), this opens both backends at once with everything pre-configured (orchestrator + admin-api). Launch the SPAs separately when needed. Each lives in its own working directory (`ask-chat-spa/` at :5174, `ask-studio-spa/` at :5173, `ask-setup-spa/` at :5175).

Set the master key + semantic-layer paths once before running the one-liner:

```powershell
$env:ONIBEX_ENCRYPTION_KEY = "<paste-the-generated-value-here>"
$env:REPO_ROOT      = "$SEMANTIC_LAYER"
$env:WORKSPACE_PATH = "$SEMANTIC_LAYER"
```

Then:

```powershell
wt -w 0 nt -d $PLATFORM pwsh -NoExit -Command ".\venv\Scripts\Activate.ps1; `$env:ENVIRONMENT='local'; `$env:DEV_BYPASS_AUTH='true'; `$env:ONIBEX_ENCRYPTION_KEY='$env:ONIBEX_ENCRYPTION_KEY'; `$env:PYTHONIOENCODING='utf-8'; python -m uvicorn ask_orchestrator.main:app --host 127.0.0.1 --port 8080 --reload" `; nt -d $PLATFORM pwsh -NoExit -Command ".\venv\Scripts\Activate.ps1; `$env:ENVIRONMENT='local'; `$env:DEV_BYPASS_AUTH='true'; `$env:ONIBEX_ENCRYPTION_KEY='$env:ONIBEX_ENCRYPTION_KEY'; `$env:REPO_ROOT='$env:REPO_ROOT'; `$env:WORKSPACE_PATH='$env:WORKSPACE_PATH'; `$env:ASK_ORCHESTRATOR_URL='http://127.0.0.1:8080'; `$env:PYTHONIOENCODING='utf-8'; python -m uvicorn ask_admin_api.main:app --host 127.0.0.1 --port 8081 --reload"
```

One tab per service: Orchestrator (8080), Admin API (8081).

---

## Docker fallback

If you'd rather not manage a venv and five terminals, the same topology runs in containers via [`docker-compose.yml`](../../docker-compose.yml):

```powershell
cd $PLATFORM
docker compose up -d
# Browser: http://localhost:5174 (chat) — http://localhost:5173 (admin) — http://localhost:5175 (setup)
docker compose logs -f ask-orchestrator    # tail any service
docker compose down                         # tear it all down
```

The compose file is the canonical source for local topology: env vars, volumes, healthchecks, and dependencies all match the per-service instructions above.

---

## Optional: local HuggingFace embedder (off by default)

The `huggingface` embedder provider runs **sentence-transformers locally** (offline, no
embedding API). Its dependency, `sentence-transformers`, pulls **`torch` + CUDA wheels (several
GB)**, so it is **not installed by default**. It would dominate every `pip install` and Docker
build. The gateway imports it lazily, only when the embedder provider is `huggingface`, so
nothing breaks when it's absent. Turn it on in **two steps**: (1) install the heavy deps,
(2) point the embedder config at the `huggingface` provider. Both are required, installing the
package alone does nothing until a provider selects it.

### Step 1: install the deps (`[huggingface]` extra)

The deps live in the `ask-llm-gateway` `[huggingface]` optional extra (`langchain-huggingface` +
`sentence-transformers`).

**Local venv:**
```powershell
# Re-install the gateway with the extra (adds torch + sentence-transformers).
uv pip install -e "packages/ask-llm-gateway[huggingface]"
```

**Docker**, pass the `GATEWAY_EXTRAS` build arg (compose forwards it to the orchestrator +
admin-api images; default is empty = no torch):
```powershell
$env:GATEWAY_EXTRAS = "[huggingface]"
docker compose up -d --build         # rebuilds ask-orchestrator + ask-admin-api WITH torch
```
```bash
GATEWAY_EXTRAS="[huggingface]" docker compose up -d --build
```
Leave `GATEWAY_EXTRAS` unset to go back to the slim (no-torch) images on the next build.

### Step 2: select the `huggingface` embedder provider

Installing the package is inert until the embedder config chooses it. Pick ONE:

- **Env vars** (set on the processes that build embeddings, `ask-orchestrator` + `ask-admin-api`):
  ```
  EMBEDDER_PROVIDER=huggingface
  EMBEDDER_MODEL=sentence-transformers/all-mpnet-base-v2   # optional; this is the default
  EMBEDDER_API_KEY=<hf_hub_token>                          # optional; only for private/gated models
  ```
- **Setup SPA**: *LLM Providers* → set the **embedder** provider to `huggingface` + model.
- **Encrypted secrets**: `POST /v1/admin/secrets/embedder` with `{ "provider": "huggingface",
  "model": "…" }` (canonical store; survives restarts).

Resolution priority is encrypted-secrets → env vars → `config/settings.json` (see
`ask_llm_gateway.application.factory`).

### Verify
```powershell
python -c "from ask_llm_gateway.application.factory import build_embedder; e = build_embedder({'embedder': {'provider': 'huggingface'}}); print('ok:', type(e).__name__, len(e.embed_query('hello')))"
# Expected: ok: HuggingFaceEmbedder 768   (first run downloads the model from the Hub)
```

> ⚠️ **Embedding dimension must match the index.** Switching embedder models changes the vector
> dimension (e.g. `all-mpnet-base-v2` = 768, SAP AI Core text-embedding-3-large = 3072). The
> OpenSearch indices are created for a fixed dimension, so changing the embedder requires
> **re-indexing** the entity/field/docs registries, existing vectors are not comparable across
> dimensions.

---

## Linux / macOS equivalents (bash)

```bash
cd "$PLATFORM"

# Setup once
export VIRTUAL_ENV=$PLATFORM/venv
uv pip install -r requirements.txt
for pkg in ask-llm-gateway ask-knowledge-graph ask-intent-resolution \
          ask-sql-generation ask-sql-executor ask-schema-service \
          ask-docs-service ask-action-execution ask-admin-api ask-orchestrator; do
  uv pip install -e "packages/$pkg"
done

# Encrypted-secrets master key — required by both backends (generate once, save somewhere safe).
export ONIBEX_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Semantic-layer repo paths — required by admin-api (boot fails closed if empty).
export REPO_ROOT="$SEMANTIC_LAYER"
export WORKSPACE_PATH="$SEMANTIC_LAYER"

# Boot orchestrator (terminal 1)
export ENVIRONMENT=local DEV_BYPASS_AUTH=true PYTHONIOENCODING=utf-8
python -m uvicorn ask_orchestrator.main:app --host 127.0.0.1 --port 8080 --reload

# Boot admin-api (terminal 2)
export ENVIRONMENT=local DEV_BYPASS_AUTH=true PYTHONIOENCODING=utf-8
export ASK_ORCHESTRATOR_URL=http://127.0.0.1:8080
python -m uvicorn ask_admin_api.main:app --host 127.0.0.1 --port 8081 --reload

# Boot the Chat SPA (terminal 3)
cd ask-chat-spa
npm install          # first time only
npm run dev          # → http://localhost:5174

# Boot the Admin SPA (terminal 4)
cd ask-studio-spa
npm install --legacy-peer-deps   # first time only
npm run dev                       # → http://localhost:5173

# Boot the Setup SPA (terminal 5)
cd ask-setup-spa
npm install          # first time only
npm run dev          # → http://localhost:5175

# Smoke
ASK_ORCHESTRATOR_URL=http://127.0.0.1:8080 ASK_ORCHESTRATOR_TIMEOUT=300 \
    python -m pytest tests/e2e/test_smoke.py -v
```

---

## Where to go from here

- **Benchmark suite:** `tests/benchmark/test_full_benchmark.py` (run with `ASK_RUN_BENCHMARK=1`).
- **Orchestrator troubleshooting (auth, deployment):** [Orchestrator troubleshooting](orchestrator-troubleshooting.md).
- **Container deploy:** [`docker-compose.yml`](../../docker-compose.yml) (local) and `deploy/` (Kubernetes manifests).

---

[← Back to the manual](../README.md)
