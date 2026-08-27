# ASK — Agentic Semantic Knowledge Platform

> The complete user manual for the **Onibex ASK Platform** — install it, author a semantic layer, publish it dev → prod, and let business users query enterprise data in plain language.

**New here? Start with [Getting Started](GETTING_STARTED.md)** — one guided path from an
empty machine to a real answer, in about 45 minutes. Everything below is the reference you
come back to afterwards, when you need one specific thing.

> Part of the [Agentic Semantic Knowledge repository](../README.md) — see the root overview for the ASK concepts and the open ASK standard under `definition/`.

Most walkthroughs use one consistent, **illustrative** example — **SAP Production Planning
(Production Orders)**; the **ASK Chat** flows use a **Sales & Distribution** example. Both are
demonstration datasets: substitute your own Data Products, and expect the sample questions to
return results only against matching data.

---

## Start here

**[Getting Started](GETTING_STARTED.md)** walks the platform's one journey —
**Configure → Author → Publish → Ask** — end to end, on a single table. It is the only page
that needs to be read in a particular order.

## Every page, by area

### Foundations
- [Install and run the platform](01-installation.md)
- [Concepts and architecture](02-concepts.md)

### [Understanding how it works](explain/README.md)
- [The three chat engines](explain/engines.md) — Flash / Precise / Smart: what each computes rather than guesses, and how to choose
- [ASK specification](../../definition/README.md) — the normative Bronze / Silver / Gold contract

### [Everyday tasks](guides/README.md)
- [Sign in to ASK](guides/sign-in.md) — the three authentication modes, the role model, and what 401 / 403 mean

### [Configure the platform first · ASK Setup](ask-setup/README.md)

**Nothing in ASK Studio or ASK Chat works until this section is done.** ASK Setup is a
prerequisite, not a third product: the platform needs a database connection and a model
provider before there is anything to author against or answer from. The first two pages are
required; the rest are optional or read-only.

- [Connect a database](ask-setup/02-database-connections.md) — multi-engine registry, one active per environment
- [Connect an LLM provider](ask-setup/03-llm-providers.md) — the LLM registry and the shared embedder
- [Connect to SAP](ask-setup/05-sap-connection.md) — S/4HANA URL, credentials, OAuth endpoint
- [Enable the MCP server](ask-setup/06-mcp-server.md) — the endpoint for write-back actions
- [Register an OpenAPI contract](ask-setup/07-contracts.md) — turn a spec into MCP tools
- [Review the identity provider](ask-setup/04-identity-provider.md) — read-only: the active provider and your session
- [Check the search index](ask-setup/01-setup.md) — read-only: the OpenSearch connection
- [Find your way around ASK Setup](ask-setup/00-overview.md) — the dashboard and the storage model

### [Author the semantic layer · ASK Studio](ask-studio/README.md)
- [Create workspaces and business domains](ask-studio/01-workspaces-domains.md) — the containers everything else lives in
- [Add Data Products](ask-studio/02-add-data-products.md) — manual, upload, DDL + AI, or OneConnect
- [Edit and enrich Data Products](ask-studio/03-edit-enrich.md) — fields, relationships, AI-drafted descriptions
- [Inspect a domain as a graph](ask-studio/04-domain-canvas.md) — see the join paths the agent will use
- [Publish and deploy](ask-studio/05-publish-deploy.md) — dev first, then prod
- [Resolve conflicts on a OneConnect merge](ask-studio/07-conflicts-merge.md)
- [Audit, compare and restore versions](ask-studio/06-history.md)
- [Set the organization profile](ask-studio/08-organization.md) — defaults that pre-fill authoring
- [Check the embedder and search index](ask-studio/09-check-providers.md) — the one provider you edit here
- [Ingest documents the agent can cite](ask-studio/10-ingest-documents.md) — a corpus separate from the semantic layer
- [Find your way around ASK Studio](ask-studio/00-overview.md) — the sidebar and the page chrome

### [Ask questions · ASK Chat](ask-chat/README.md)
- [Scope a question](ask-chat/01-workspace-environment-mode.md) — workspace, environment and mode
- [Using the Chat](ask-chat/02-chat.md) — ask, read the answer, see the SQL
- [Generate a report or brief](ask-chat/03-artifacts.md) — shareable documents, no SQL required
- [Find your way around ASK Chat](ask-chat/00-overview.md) — the sidebar and the home dashboard

### [Operating the platform](runbooks/README.md)
- [Local development](runbooks/local-development.md) — running the services natively instead of in Docker
- [Orchestrator troubleshooting](runbooks/orchestrator-troubleshooting.md) — on-call diagnosis for the chat backend

### [Reference](reference/README.md)
- [Glossary](reference/glossary.md)
- [Troubleshooting & FAQ](reference/troubleshooting.md)


---

## License

The Onibex ASK Platform is source-available under the
**PolyForm Strict License 1.0.0** — see [`LICENSE.md`](../LICENSE.md). Noncommercial use,
research, evaluation, and personal study are permitted; commercial or production use
requires a commercial license from [Onibex](https://onibex.com).
