<!--
SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
Copyright (c) 2026 Onibex, LLC. All rights reserved.
-->

# ASK Studio SPA

The surface where the semantic layer is written: workspaces, business domains and Data
Products, the domain canvas that shows the join paths the agent will use, and the publish step
that makes any of it queryable.

React, Vite and TypeScript with Tailwind CSS, served by Nginx in the Docker stack and on
`http://localhost:5173` either way. Two libraries do the distinctive work: **React Flow** with
dagre draws the domain canvas, and **Monaco** edits the YAML.

```bash
npm install
npm run dev
```

It talks to `ask-admin-api` only, never to a database and never to the orchestrator. Nginx
routes `/api/admin/*` to `/v1/admin/` and everything else under `/api/` to `/v1/viz/`, the
canvas endpoints.

**The API types are generated, not written.** `npm run generate-api` rewrites
`src/api/generated.ts` from the admin API's own OpenAPI document at
`http://localhost:8081/openapi.json`, and `generate-api:file` does the same from a saved
`../openapi-admin.json` when the API is not running.

**`src/tokens.css` and `src/theme.css` are copies.** The authored source is
[`design/`](../design/) at the platform root, and `node scripts/sync-design-tokens.mjs` writes
it into all three SPAs. CI runs that script with `--check`, so editing the copy fails the build
rather than drifting quietly.

**Documentation:** [Author the semantic layer · ASK Studio](../docs/ask-studio/README.md). What
the surface is for and the order to learn it in.
[Inspect a domain as a graph](../docs/ask-studio/04-domain-canvas.md). What the canvas shows.
[Publish and deploy](../docs/ask-studio/05-publish-deploy.md). Why nothing authored here is
queryable until that step.
