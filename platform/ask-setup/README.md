<!--
SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
Copyright (c) 2026 Onibex, LLC. All rights reserved.
-->

# ASK Setup

The technical-configuration surface: database connections, LLM and embedding providers, the SAP
connection, the MCP server and OpenAPI contracts, plus read-only views of the identity provider
and the search index. Whoever owns the infrastructure fills it in once, and the people who
author and ask never open it.

React, Vite and TypeScript with Tailwind CSS, served by Nginx in the Docker stack and on
`http://localhost:5175` either way.

```bash
npm install
npm run dev
```

It talks to `ask-admin-api` only. Nginx routes `/api/admin/*` to `/v1/admin/`, and nothing here
reaches a database or a model provider directly: every credential entered on these screens is
sent to the API, encrypted there, and stored in OpenSearch rather than in a file.

**Unlike the other two SPAs, this one is on React Router 7 and Zustand 5** rather than 6 and 4.
Worth knowing before lifting a component across.

**`src/tokens.css` and `src/theme.css` are copies.** The authored source is
[`design/`](../design/) at the platform root, and `node scripts/sync-design-tokens.mjs` writes
it into all three SPAs. CI runs that script with `--check`, so editing the copy fails the build
rather than drifting quietly.

**Documentation:** [Configure the platform first · ASK Setup](../docs/ask-setup/README.md).
What has to be filled in, and in what order.
[Connect a database](../docs/ask-setup/02-database-connections.md) and
[Connect an LLM provider](../docs/ask-setup/03-llm-providers.md). The two that are required;
the rest of the section is optional or read-only.

---

[← Back to the platform](../README.md)
