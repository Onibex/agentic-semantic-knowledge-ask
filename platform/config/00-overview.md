# ASK Setup · Overview

> **The configuration home of the Onibex ASK Platform.** **ASK Setup** is where an
> administrator points the platform at its infrastructure — the OpenSearch store, the databases
> the agent queries, the language models it uses, the identity provider, and the SAP write-back
> endpoints — from a single dashboard.

| | |
|---|---|
| **Who** | Administrator (**ask-admin** role) |
| **Time** | ~10 minutes for a first pass; most sections are set once |
| **Prerequisites** | The platform is installed and running (see [Installation](../01-installation.md)) and you can sign in to **ASK Setup**. |
| **You'll end with** | Every configuration section reviewed and green — a platform ready to author in ASK Admin and answer in the chat. |

**Where this fits:** **Configure — Overview (you are here)** → Author → Publish → Ask

> The screenshots and sample values below use the illustrative demo environment: an **SAP HANA**
> target (port `443`), OpenSearch at `opensearch:9200`, and a Bedrock model. Substitute your own
> hosts and credentials — never screenshot a real API key, client secret, or database password.

---

## Concepts (30-second version)

- **ASK Setup is one of three apps.** The platform ships three separate front-ends: **ASK Setup**
  (this configuration app), **ASK Admin** (authoring the semantic layer), and the **chat** (asking
  questions). This section of the manual documents ASK Setup only.
- **Two kinds of section.** Some sections are **read-only** mirrors of what the environment already
  provides (**Setup** / OpenSearch, **Identity Provider**). Others are **editable registries**
  (**Database**, **LLM Providers**) or small credential forms (**SAP Connection**, **MCP Server**,
  **Contracts**).
- **Secrets live in an encrypted store, not on disk.** Connection credentials are encrypted at rest
  inside OpenSearch and never written to `settings.json`. See [Where configuration is stored](#where-configuration-is-stored).
- **The Semantic Dictionary and Documents are not here.** Business-term mappings and document
  ingestion moved to **ASK Admin**. See [What lives in ASK Admin, not here](#what-lives-in-ask-admin-not-here).

---

## 1. The Home dashboard

Signing in lands you on **Home**. The page opens with a hero — the app title and an **Onibex
platform administration** subtitle — and a **Refresh** button that re-reads live status from the
server.

Below the hero, a **Setup progress** bar reports how many sections are configured, as
**`X / 7`**. When every section is green it shows the **All sections configured** badge. Under that
sits a grid of **seven cards**, one per configuration section, each with a short description and a
**status strip** at its foot:

- A green strip with a check means the section is configured (for example **Active connection set**
  or **Model configured**).
- A grey strip with an alert means it still needs attention (for example **No active connection**
  or **OpenSearch not set**).

Click any card to open its section. At the very bottom, when a language model is active, an
**Active model** badge shows the model id in use.

![ASK Setup Home: hero, Setup progress bar, the seven section cards with status strips, and the active-model badge](../images/config-home.png)

> **Tip — the cards are a checklist.** The status strips make the dashboard a live checklist:
> work top to bottom until the progress bar reads **`7 / 7`**. Status is derived from the server,
> so **Refresh** after a change made elsewhere (for example an environment variable update).

## 2. The seven sections

The left sidebar and the Home grid list the same seven sections, in order. Each has its own page in
this manual:

| # | Section | What you set there |
|---|---|---|
| 1 | **Setup** | [Infrastructure (OpenSearch)](01-setup.md) — the read-only, environment-sourced OpenSearch connection, plus a health check. |
| 2 | **Database** | [Database Connections](02-database-connections.md) — the registry of databases the agent queries; one active per environment. |
| 3 | **LLM Providers** | [LLM Providers](03-llm-providers.md) — the language models the agent can use, plus the shared embedder. |
| 4 | **Identity Provider** | [Identity Provider](04-identity-provider.md) — the read-only active sign-in provider and your session. |
| 5 | **SAP Connection** | [SAP Connection](05-sap-connection.md) — S/4HANA URL, client credentials and OAuth token endpoint. |
| 6 | **MCP Server** | [MCP Server](06-mcp-server.md) — the Model Context Protocol endpoint for write-back actions to SAP. |
| 7 | **Contracts** | [Contracts](07-contracts.md) — OpenAPI specs registered as MCP tool contracts for the agent. |

## 3. Recommended order of operations

The Home page footer, **How it works**, states the recommended order. Follow it for a clean
first-time setup:

1. Point the platform at **OpenSearch** via environment variables (shown read-only under **Setup**).
2. Register **database connections** and set one active per environment under **Database**.
3. Choose your **LLM provider** and run the connection test.
4. Register **S/4HANA** and **MCP** credentials to enable write-back actions.
5. Import **OpenAPI specs** under **Contracts** to expose SAP APIs to the agent.

> Steps 1–3 are required before the chat can answer a data question. Steps 4–5 are only needed if
> you use SAP write-back actions.

---

## Where configuration is stored

ASK Setup uses a layered storage model. Understanding it explains why some pages are editable and
others are read-only:

- **Encrypted store in OpenSearch.** Database and LLM connections are kept as encrypted documents
  inside OpenSearch — database connections under `dbconn:*` with a `db_active` pointer per
  environment, and language models under `llmconn:*` with an `llm_active` pointer. Sensitive fields
  (passwords, tokens, keys) are encrypted at rest and never returned to the UI in clear text.
- **Environment variables take precedence.** Where a value can come from more than one place, an
  environment variable overrides the stored configuration. The **Setup** page tags each field with
  a source chip — **env**, **file**, **encrypted**, **config** or **default** — so you can see where
  a live value actually came from.
- **OpenSearch credentials come from the environment.** OpenSearch hosts the encrypted secret store
  itself, so its own connection details cannot live inside that store. They are supplied by
  `OPENSEARCH_*` environment variables and shown read-only under **Setup**.
- **`settings.json` is pruned.** The on-disk config file now holds only a handful of non-secret
  keys. It is no longer the home of database or LLM credentials.

## What lives in ASK Admin, not here

Two capabilities that older versions of the platform placed under configuration now belong to
**ASK Admin**:

- **The Semantic Dictionary** — business-term and phrase mappings. Managed on the ASK Admin
  dictionary page, not in ASK Setup.
- **Document ingestion** — uploading PDFs, Word, text and Markdown for documentation answers.
  Managed on the ASK Admin Docs page.

If you are looking for either, switch to ASK Admin.

---

## What's next

→ **[Infrastructure (OpenSearch)](01-setup.md)** — confirm the store the whole platform runs on.
→ **[Database Connections](02-database-connections.md)** — register the databases the agent queries.
→ **[Installation](../01-installation.md)** — the environment variables and services behind these pages.
