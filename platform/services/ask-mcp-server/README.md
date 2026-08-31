<!--
SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
Copyright (c) 2026 Onibex, LLC. All rights reserved.
-->

# ASK MCP server

The write half of ASK. Everything else in this repository reads: this service is what turns
*"create a sales order for customer 4711"* from a sentence the agent understands into a call
SAP actually performs.

It is a **Model Context Protocol** server in front of SAP S/4HANA OData services. Each entity
set declared in `api-config.json` becomes a set of MCP tools: list, get, create, update. That
the agent may call once an administrator has enabled them.

## What is here

| File | Role |
|---|---|
| `api-config.json` | The contract: which OData services, which entity sets, and which operations are permitted on each. The shipped default covers Sales Order header, items and partners. |
| `patch.js` | Patches `odata-mcp-proxy` for Basic Auth and readable OData V4 errors. Runs on `postinstall`, and is safe to re-run. |
| `start.sh` | Reads `api-config.json` from the mounted config volume if one is there, otherwise seeds the default. SAP credentials come from the environment; `settings.json` only fills the gaps. |

The proxy itself is the `odata-mcp-proxy` dependency. This service is the configuration,
the patches and the startup contract around it, not a reimplementation.

## Running it

It is an **opt-in Compose profile**, not part of the default stack. Bring it up only when
write-back is wanted, and never with credentials that can write to a system you are not
prepared to have written to.

```bash
npm install     # runs patch.js
npm start
```

`delete` is `false` on every shipped entity set. Turning it on is a deliberate act, in
`api-config.json`, and it is worth being deliberate about.

## Documentation

- [Enable the MCP server](../../docs/ask-setup/06-mcp-server.md). Pointing the platform at
  this endpoint.
- [Register an OpenAPI contract](../../docs/ask-setup/07-contracts.md). Turning a spec into
  the tools the agent sees.
- [Connect to SAP](../../docs/ask-setup/05-sap-connection.md). The credentials this service
  authenticates with.

---

[← Back to the services](../README.md)
