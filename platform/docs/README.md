# ASK — Agentic Semantic Knowledge Platform

> The complete user manual for the **Onibex ASK Platform** — install it, author a semantic layer, publish it dev → prod, and let business users query enterprise data in plain language.

If you just want to get going fast, start with [Installation](01-installation.md) then
[Concepts](02-concepts.md); this manual is the in-depth reference that documents **every
flow** across ASK Setup, ASK Studio and the Chat.

> Part of the [Agentic Semantic Knowledge repository](../README.md) — see the root overview for the ASK concepts and the open ASK standard under `definition/`.

Most walkthroughs use one consistent, **illustrative** example — **SAP Production Planning
(Production Orders)**; the **ASK Chat** flows use a **Sales & Distribution** example. Both are
demonstration datasets: substitute your own Data Products, and expect the sample questions to
return results only against matching data.

---

## Read in order (new administrators)

The platform follows one journey — **Configure → Author → Publish → Ask** — and this order
mirrors it:

1. [Installation & Running the Platform](01-installation.md)
2. [Concepts & Architecture](02-concepts.md)
3. [ASK Setup · Overview](ask-setup/00-overview.md) — configure the platform (database, providers, identity)
4. [ASK Studio · Overview & Navigation](ask-studio/00-overview.md)
5. [ASK Studio · Workspaces & Business Domains](ask-studio/01-workspaces-domains.md)
6. [ASK Studio · Add Data Products](ask-studio/02-add-data-products.md)
7. [ASK Studio · Edit & Enrich Data Products](ask-studio/03-edit-enrich.md)
8. [ASK Studio · Domain Canvas (Graph)](ask-studio/04-domain-canvas.md)
9. [ASK Studio · Publish & Deploy (dev → prod)](ask-studio/05-publish-deploy.md)
10. [ASK Chat · Overview & Navigation](ask-chat/00-overview.md)

## By area

### Foundations
- [Installation & Running the Platform](01-installation.md)
- [Concepts & Architecture](02-concepts.md)

### Understanding how it works
- [The three chat engines](explain/engines.md) — Flash / Precise / Smart: what each computes rather than guesses, and how to choose
- [ASK specification](../../definition/README.md) — the normative Bronze / Silver / Gold contract

### Everyday tasks
- [Sign in to ASK](guides/sign-in.md) — the three authentication modes, the role model, and what 401 / 403 mean

### ASK Setup (technical configuration)
- [Overview](ask-setup/00-overview.md) — the ASK Setup home + the config-storage model
- [Infrastructure (OpenSearch)](ask-setup/01-setup.md)
- [Database Connections](ask-setup/02-database-connections.md) — multi-engine registry, one active per environment
- [LLM Providers](ask-setup/03-llm-providers.md) — LLM registry + the shared embedder
- [Identity Provider](ask-setup/04-identity-provider.md)
- [SAP Connection](ask-setup/05-sap-connection.md)
- [MCP Server](ask-setup/06-mcp-server.md)
- [Contracts](ask-setup/07-contracts.md) — OpenAPI → MCP tools

### ASK Studio (semantic-layer authoring)
- [Overview & Navigation](ask-studio/00-overview.md)
- [Workspaces & Business Domains](ask-studio/01-workspaces-domains.md)
- [Add Data Products](ask-studio/02-add-data-products.md) — Manual / Upload / DDL + AI / OneConnect
- [Edit & Enrich Data Products](ask-studio/03-edit-enrich.md)
- [Domain Canvas (Graph)](ask-studio/04-domain-canvas.md)
- [Publish & Deploy (dev → prod)](ask-studio/05-publish-deploy.md)
- [History (Audit, Diff, Restore)](ask-studio/06-history.md)
- [Conflicts & OneConnect Merge](ask-studio/07-conflicts-merge.md)
- [Organization Profile](ask-studio/08-organization.md)
- [System Setup & Document Ingestion](ask-studio/09-providers-docs.md) — read-only providers, shared embedder, RAG docs

### ASK Chat (end users)
- [Overview & Navigation](ask-chat/00-overview.md)
- [Workspace, Environment & Mode](ask-chat/01-workspace-environment-mode.md)
- [Using the Chat](ask-chat/02-chat.md)
- [Artifacts](ask-chat/03-artifacts.md)

### Reference
- [Glossary](reference/glossary.md)
- [Troubleshooting & FAQ](reference/troubleshooting.md)


---

## License

The Onibex ASK Platform is source-available under the
**PolyForm Strict License 1.0.0** — see [`LICENSE.md`](../LICENSE.md). Noncommercial use,
research, evaluation, and personal study are permitted; commercial or production use
requires a commercial license from [Onibex](https://onibex.com).
