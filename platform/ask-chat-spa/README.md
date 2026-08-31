<!--
SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
Copyright (c) 2026 Onibex, LLC. All rights reserved.
-->

# ASK Chat SPA

The surface business users see: ask a question in plain language, read the answer with its
table, its chart and the SQL behind it.

React, Vite and TypeScript with Tailwind CSS, served by Nginx in the Docker stack and on
`http://localhost:5174` either way.

```bash
npm install
npm run dev
```

It talks to `ask-orchestrator` only. Nothing here reaches a database directly, and the mode
selector (Flash / Precise / Smart) is forwarded on every `/query` and `/artifact` call.

**`src/tokens.css` and `src/theme.css` are copies.** The authored source is
[`design/`](../design/) at the platform root, and `node scripts/sync-design-tokens.mjs` writes
it into all three SPAs. CI runs that script with `--check`, so editing the copy fails the build
rather than drifting quietly.

**Documentation:** [Ask questions · ASK Chat](../docs/ask-chat/README.md). How the surface is
used. [The three chat engines](../docs/explain/engines.md). What the mode selector changes.
