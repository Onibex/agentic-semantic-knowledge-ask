# Configuration App (Technical Setup)

> **The technical-setup half of the platform.** The **Configuration App** is where an
> administrator wires the plumbing — database connections, LLM & embedding providers,
> OpenSearch, SAP AI Core, Cloud Identity, knowledge ingestion, the SAP S/4HANA link, MCP and
> the semantic dictionary — so the semantic-layer authoring done in **ASK Admin** and the chat
> both have something to run against.

| | |
|---|---|
| **Who** | Administrator / platform operator |
| **Time** | ~15 minutes for a first-time end-to-end setup |
| **Prerequisites** | You can sign in to the **Configuration App**; you have the credentials for your database, LLM provider, OpenSearch, and (optionally) SAP AI Core / IAS / S/4HANA. |
| **You'll end with** | A saved `config/settings.json` — database (dev/prod), a provider stack, OpenSearch, and (optionally) IAS — so the chat and ASK Admin are ready to use. |

**Where this fits:** **Configure — Technical setup (you are here)** → Author → Publish → Ask

> The screenshots and sample values below use an illustrative **SAP Production Planning** example (Production Orders). Substitute your own Data Products — the exact demo names and questions won't exist in your system.

> **Scope note.** The Configuration App owns **technical infrastructure config** (database,
> providers, connections). The **semantic layer** (workspaces, domains, Data Products) lives in
> the separate [ASK Admin](../ask-admin/01-workspaces-domains.md) app. The two never overlap.

---

## Initial setup sequence

Configuration areas depend on each other, so do them in this order the first time:

| # | Area | Why it comes here |
|---|---|---|
| 1 | **LLM & Embeddings providers** | Everything downstream (ingestion embeddings, chat, DDL+AI) needs a working LLM + embedder. Set the **stack mode** and provider first. |
| 2 | **OpenSearch** | The vector store for all semantic-layer retrieval (RAG). Ingestion and chat both need it reachable. |
| 3 | **SAP AI Core** *(managed stack only)* | Upload the service key, then pick the LLM + embedding **deployments**. Skip if you chose the Direct (LiteLLM) stack. |
| 4 | **Database (dev / prod)** | The SQL engine the chat queries. `dev` is required; `prod` is optional but blocks prod chat until set. |
| 5 | **Cloud Identity (IAS)** *(optional)* | Only if you gate access by IAS groups. |
| 6 | **Save** | The **Setup — Summary** tab (and the Database / LLM Providers pages) persist everything to `settings.json` and hot-reload the live services. |

Once the plumbing is saved, feed the semantic layer via **Knowledge** ingestion, then connect
**SAP S/4HANA**, **MCP** and **API Contracts** as those capabilities are needed.

---

## The Home dashboard

The landing page shows two module cards — **System Setup** and **Knowledge Management** — plus,
once a configuration exists, a green *Configuration active* banner and an **Active Configuration**
summary (database host/port, SAP AI Core model + deployments, OpenSearch host/port, IAS status).

![Configuration App home: System Setup and Knowledge Management cards with the active-configuration summary](../images/config-home.png)

Use **Open Setup →** for the System Setup wizard and **Open Knowledge →** for ingestion. All the
other areas below are reached from the left sidebar.

---

## System Setup (the wizard)

Open **Setup** from the sidebar (or the **Open Setup →** button). It is a tabbed wizard:
**Database**, **OpenSearch**, **SAP AI Core**, **Deployments** (labelled *LLM & Embeddings*),
**Cloud Identity (IAS)**, and **Summary**.

![System Setup wizard tab strip: Database · OpenSearch · SAP AI Core · Deployments · Cloud Identity (IAS) · Summary](../images/config-setup-tabs.png)

> **The Database tab here is a pointer.** It shows an info note only — DB connections moved to
> the dedicated **Database** page (below). Everything else — OpenSearch, SAP AI Core, LLM &
> Embeddings, IAS — is configured on its Setup tab and committed together from **Summary**.

### OpenSearch

OpenSearch is used exclusively for **embeddings and vector search** (RAG); your SQL database
handles transactional queries. On the **OpenSearch** tab fill:

| Field | Notes |
|---|---|
| **Host** | e.g. `opensearch` or `localhost` (demo: `opensearch`). |
| **Port** | Defaults to `9200`. |
| **Username (optional)** / **Password (optional)** | Basic auth if your cluster requires it. |
| **Use SSL (HTTPS)** / **Verify SSL certificates** | Toggle for TLS; disable cert verification for self-signed instances. |

Click **Test OpenSearch Connection**. On failure a **Troubleshooting** expander lists the common
causes (missing `opensearch-py`, unreachable host/port, self-signed certs).

### SAP AI Core

Used only on the **Managed** stack. Click **SAP AI Core Service Key (JSON)** and upload the
service key you download from the SAP BTP Cockpit. The app validates it, extracts the credentials
into a `.env` file, and offers **View extracted configuration** (secrets masked). Then click
**Test SAP AI Core Connection** to confirm.

### LLM & Embeddings (Deployments tab)

On the **managed** path every model runs as a **SAP AI Core deployment**. After the SAP AI Core
test passes, this tab lists the discovered deployments; pick one **LLM (Chatbot)** deployment and
one **Embeddings** deployment.

> On the **direct** stack you do not use this tab — configure the model on the **LLM Providers**
> page instead (see below).

### Cloud Identity (IAS)

Configure an IAS tenant so the app reads the user's **groups** (instead of BTP Role Collections).

| Field | Notes |
|---|---|
| **Tenant URL** | `https://<tenant>.accounts.ondemand.com`. |
| **Client ID** / **Client Secret** | From an IAS Application → **API Authentication** → Client Credentials. |

Click **Test IAS Connection** to verify.

### Summary & Save

The **Summary** tab gates on the OpenSearch, SAP AI Core and Deployments steps being tested. It
recaps OpenSearch, SAP AI Core and LLM & Embeddings, then offers a **Schema Mode** selector —
how the chatbot finds schemas for SQL generation:

| Option | Meaning |
|---|---|
| **Document RAG** | Use manually ingested DDL / schema docs. |
| **YAML Data Products** | Use structured YAML definitions only. |
| **Both** *(recommended)* | Search YAML + documents. |

Click **Save Configuration**. The app writes `settings.json` (merging — it never drops keys it
does not own, and DB config stays owned by the Database page) and broadcasts a reload to the live
services so the new settings take effect without a manual restart. An **Advanced Options**
expander at the bottom offers **Delete Current Configuration**.

---

## Database (dev / prod)

Open the dedicated **Database** page from the sidebar. It configures **per-environment**
connections: the chat targets the **dev** or **prod** database based on its environment picker.

1. Pick the **Database engine (shared by dev & prod)** — **PostgreSQL** or **SAP HANA Cloud**
   (demo: SAP HANA Cloud). A single engine is shared; only host/credentials/schema differ per
   environment.
2. Fill the **Development (dev)** tab, then optionally the **Production (prod)** tab.

**PostgreSQL** fields: **Host**, **Port** (`5432`), **Database**, **User**, **Password**,
**SSL Mode** (`prefer` / `disable` / `require` / `allow`).
**SAP HANA Cloud** fields: **Host (SQL Endpoint)**, **Port** (`443`), **Schema (optional)**,
**User**, **Password**.

Use **Test dev connection** / **Test prod connection**, then **Save database configuration** — it
persists per environment and hot-reloads the live services.

![Database page: engine radio, Development / Production tabs, and the per-environment connection form](../images/config-database.png)

> **Warning — prod does not inherit dev.** If the **prod** connection is left blank, prod chat
> queries are **blocked** with a clear message (there is no silent fallback to dev). Leave prod
> empty only if you are not using a prod environment.

---

## LLM & Embeddings providers

Open the **LLM Providers** page for the multi-provider matrix. It picks the active **stack mode**
and wires the LLM + embedder credentials, writing to the same `settings.json`.

**Stack mode** (radio):

| Mode | What it uses |
|---|---|
| **Managed (SAP AI Core / BTP)** | `gen_ai_hub` + the deployment IDs chosen on the Setup **Deployments** tab. |
| **Direct (LiteLLM)** | LiteLLM against any of 10+ providers — OpenAI, Anthropic, Azure, Azure AI Foundry, Databricks, **AWS Bedrock**, Vertex AI, Gemini, Cohere, Mistral, Groq, DeepSeek, Together AI, and local HuggingFace embeddings. |

Two form sections — **LLM (chat / generation)** and **Embedder (retrieval / vector indexing)** —
each expose a **Provider** dropdown, a **Model** field, and provider-specific fields (**API key**,
**API base URL**, **API version**, **Deployment ID**, or an **Extra env vars (params)** block of
`KEY=VALUE` lines, e.g. for Bedrock / Vertex AI credentials). Leave **API key** blank to keep the
stored one; type a new value to rotate. Each section has a **Test *llm* / *embedder* connection**
button. Finish with **Save provider config** (or **Reload from server** to discard edits).

For the demo, show the **Direct (LiteLLM)** stack with provider **bedrock**, LLM model
`us.amazon.nova-pro-v1:0` and embedder `bedrock` · `amazon.titan-embed-text-v2:0`.

![LLM Providers page: stack-mode radio, LLM and Embedder sections with provider dropdown, model and credential fields](../images/config-llm-providers.png)

> **Warning — secrets in production.** The UI write path for `*_api_key` is for dev / demo only.
> In production inject `*_API_KEY` via a Kubernetes Secret → environment variable; env vars
> override `settings.json`.

---

## Knowledge ingestion & catalog

Open **Knowledge** (the **Open Knowledge →** card, or the sidebar). One page feeds and governs
the ASK semantic layer through three tabs: **About ASK**, **Ingest**, and **Browse Catalog**.

**About ASK** explains the layers (Bronze / Silver / Gold) and shows **Live counters** — total
entities by layer plus RAG chunk counts for `rag_schema` and `rag_data_product_docs`.

**Ingest** offers three modes (top radio):

| Mode | What it does |
|---|---|
| **YAML (Silver / Gold)** | Upload one or more ASK Spec YAMLs. Auto-detects the layer and indexes the entity into **both** the catalog and the `rag_schema` vector store in one round-trip. Set a **Version tag** and keep **Also index in RAG vectorstore** ticked. |
| **SAP Entity (JSON)** | Upload or paste a SAP source-system metadata JSON dump. Produces the Bronze table definitions **and** the curated Silver entity, writing them back and indexing them. |
| **Documentation** | Upload business definitions / KPI catalogs (`.docx`, `.xlsx`, `.pdf`, `.txt`, `.md`). Requires a **Data Product Name** and a **Content Type**; chunks land in `rag_data_product_docs` for the Docs Service. |

![Knowledge page: About / Ingest / Browse Catalog tabs, with the Ingest mode radio (YAML · SAP Entity (JSON) · Documentation)](../images/config-knowledge.png)

**Browse Catalog** has two sub-tabs — **Data Products** and **Documentation**. In **Data Products**
each entry shows the indices it lives in as pills (`ask-entity-registry`, `ask-field-registry`,
`ask-edge-registry`, and `rag_schema · N chunks`); select one to preview its YAML, **Download YAML**,
or (Silver / Gold only) delete it from a confirmed **Danger Zone**. In **Documentation** you select
source files to **Delete selected** or **Delete entire collection**.

> **Deletes cascade.** Removing an entity cleans it out of **every** index it lives in (catalog +
> `rag_schema`) in one step — no orphan chunks. Delete is only offered for **Silver** and **Gold**.

---

## SAP S/4HANA (OData connection)

Open the **SAP Connection** page. These credentials let the MCP server authenticate against your
S/4HANA system; they are stored in the Kubernetes secret `sap-s4hana-secret` and the MCP
`mcp-api-config` ConfigMap.

| Field | Notes |
|---|---|
| **Host / IP** *(required)* | e.g. `https://1.2.3.4:44300`. |
| **OData V4 Path** | Auto-filled with the standard Sales Order OData V4 path; change only if yours differs. |
| **Username** *(required)* / **Password** *(required)* | The S/4HANA service user. |

**Save Connection** upserts the secret, writes `settings.json`, patches the MCP ConfigMap, and
restarts the MCP pod (with a live progress bar). A **Current Stored Values** panel shows the saved
host / username (password kept in the secret).

![SAP Connection page: Host, OData V4 Path, Username and Password fields with Save Connection](../images/config-sap-connection.png)

> **Warning — this page needs Kubernetes.** Saving writes a K8s secret / ConfigMap and restarts a
> pod. Run it where the cluster is reachable; locally the ConfigMap / restart steps report a
> warning but `settings.json` still saves.

---

## MCP Server

Open the **MCP Server** page to point the platform at its internal MCP service — the bridge that
exposes SAP OData as MCP tools.

- **MCP Server URL (internal K8s)** — the ClusterIP URL, default `http://agenticai-mcp-service:4004`.
- **Port** — default `4004`.

Click **Test MCP Connection** to run a health check + MCP handshake; on success it reports how many
tools are available and lists them in an expander. **Save** persists the settings and restarts the
MCP pod.

![MCP Server page: MCP URL and Port fields with Test MCP Connection and Save](../images/config-mcp-server.png)

---

## Semantic Dictionary

Open the **Semantic Dictionary** page to manage enriched business terms per SAP module — the
mappings that let the agent resolve ambiguous wording via hybrid semantic search. At the top pick
the **SAP Module** (`SD` / `MM` / `PP` / `FI` / `CO`) and the **Source System** (`s4h`). The left
column is the editor (two tabs); the right column lists the current dictionary for that module.

**Field / Metric Mapping** tab — map one column. Using the demo PP entry:

| Field | Value |
|---|---|
| **Canonical Label** | `Confirmed Yield` |
| **Technical Name (SAP Column)** | `LMNGA` |
| **Table** | `AFRU` |
| **Type** | `metric` |
| **Synonyms (comma-separated)** | `good quantity, good output, yield, accepted output` |
| **Description** | `The good (non-defective) quantity confirmed on a production order operation (AFRU.LMNGA). Numerator of the yield-rate KPI (confirmed yield / planned order quantity).` |

Optional **Context Clues**, **Disambiguation Hint** and **Silver Entity ID** refine matching. An
expander — **Value-level enrichments** — adds **Examples**, **Value synonyms** (`user-wording=actual-value`)
and a **Mark as preferred ID column** checkbox, which steer the SQL generator toward the right
column and value. Click **Save Field Mapping**.

**Phrase (Macro) Mapping** tab — map a concept to several fields. Using the demo:

| Field | Value |
|---|---|
| **Phrase / Concept** | `scrap rate` |
| **Semantic Fields / Columns (comma-separated)** | `AFRU.XMNGA (scrap quantity), AFKO.GAMNG (total order quantity), AFRU.LMNGA (confirmed yield)` |
| **Synonyms (comma-separated)** | `scrap percentage, reject rate, waste rate, percent scrapped` |

Click **Save Phrase Mapping**.

![Semantic Dictionary page: module/source filters, the Field-Metric mapping editor, and the current-module table](../images/config-semantic-dictionary.png)

---

## API Contracts

Open the **API Contracts** page to register additional SAP OData APIs as MCP tools from an
**OpenAPI 3.0** spec. Drag & drop a `.yaml` / `.yml` / `.json` file into **Upload New Contract**;
the spec is parsed into entity sets + operations (LIST / GET / POST / PATCH / DELETE) and a fields
preview. Click **Register Contract & Restart MCP** to save and reload the MCP pod.

Under **Registered Contracts** each contract shows its entity-set operations table and a
**Field Behavior** expander where each field's behavior is set to **Optional**, **Default (from SAP)**,
**Recommended**, or **Required (ask user)**; custom contracts can be removed (the built-in
`salesorder` contract cannot).

![API Contracts page: OpenAPI uploader with a parsed entity-set preview and the registered-contracts list](../images/config-contracts.png)

---

## Access Control

Open the **Access Control** page to review the identity setup and verify who can reach the app.
It shows the **Provider Mode** (**BTP / IAS Active** vs **Standalone (no IAS)**), the **IAS
Configuration** (tenant URL / client ID / secret, masked), the **XSUAA / App Router** details, and
the **Current Session** user with their IAS groups / role collections.

The **Verify User Access** form checks whether any **email address** has a registered IAS account,
returning *Access Granted* / *Access Denied* plus the user's IAS groups and the raw API response in
an expander.

![Access Control page: provider-mode and IAS configuration cards, current session, and the Verify User Access form](../images/config-access-control.png)

---

## What's next

→ **[ASK Admin · Add Data Products](../ask-admin/02-add-data-products.md)** — with a provider
configured here, the AI-assisted authoring modes (DDL + AI, OneConnect) are ready.
→ **[ASK Admin · Workspaces & Business Domains](../ask-admin/01-workspaces-domains.md)** — organize
your Data Products into the containers the chat scopes to.
