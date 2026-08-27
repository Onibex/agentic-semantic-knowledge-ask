# Configure the platform · ASK Setup

**Nothing in ASK Studio or ASK Chat works until this section is done.** ASK Setup is the
prerequisite, not a third product: the platform needs a database to query and a model provider
before there is anything to author against or answer from.

## Required, in this order

1. [Connect a database](02-database-connections.md) — the database ASK queries. One active
   connection per environment.
2. [Connect an LLM provider](03-llm-providers.md) — the model that writes SQL, and the embedder
   that powers retrieval.

At that point the platform works. Everything below is optional or read-only.

## When you need them

- [Connect to SAP](05-sap-connection.md) — S/4HANA credentials, for write-back.
- [Enable the MCP server](06-mcp-server.md) — the endpoint that performs those writes.
- [Register an OpenAPI contract](07-contracts.md) — turns an OData spec into MCP tools.

## Read-only

- [Review the identity provider](04-identity-provider.md) — who signs in, and how.
- [Check the search index](01-setup.md) — the OpenSearch connection the whole platform runs on.
- [Find your way around ASK Setup](00-overview.md) — the dashboard and where configuration is
  stored.

---

[← Back to the manual](../README.md)
