# Author the semantic layer · ASK Studio

ASK Studio is where the semantic layer is written: the workspaces and business domains that
scope a question, the Data Products that answer it, and the publish step that makes them
queryable.

## If you are starting from nothing, in this order

1. [Create workspaces and business domains](01-workspaces-domains.md) — the containers
   everything else lives in.
2. [Add Data Products](02-add-data-products.md) — manual, upload, DDL + AI, or OneConnect.
3. [Edit and enrich Data Products](03-edit-enrich.md) — fields, relationships, AI-drafted
   descriptions.
4. [Inspect a domain as a graph](04-domain-canvas.md) — see the join paths the agent will use.
5. [Publish and deploy](05-publish-deploy.md) — **nothing you author is queryable until this
   step.** dev first, then prod.

## The rest are occasional tasks, in no order

- [Audit, compare and restore versions](06-history.md) — every change is a commit.
- [Resolve conflicts on a OneConnect merge](07-conflicts-merge.md) — when SAP changes a field
  you enriched.
- [Set the organization profile](08-organization.md) — defaults that pre-fill authoring.
- [Check the embedder and search index](09-check-providers.md) — the one provider you edit here.
- [Ingest documents the agent can cite](10-ingest-documents.md) — a corpus separate from the
  semantic layer.
- [Find your way around ASK Studio](00-overview.md) — the sidebar and the page chrome.

---

[← Back to the manual](../README.md)
