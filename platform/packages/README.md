<!--
SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
Copyright (c) 2026 Onibex, LLC. All rights reserved.
-->

# Python packages

The platform's backend, split into packages with enforced boundaries, the contracts in
`.importlinter` fail the build rather than merely advising. Each package installs on its own
and is tested with its own suite (`cd packages/<name> && pytest`).

| Package | What it does |
|---|---|
| `ask-orchestrator` | The FastAPI entry point. Every user request arrives here and is routed by macro intent. |
| `ask-intent-resolution` | Turns a question into a resolved plan. Three strategies behind one `IntentResolver` protocol, the Flash / Precise / Smart engines. |
| `ask-sql-generation` | Writes the SQL, with scope validation and one retry. |
| `ask-sql-executor` | Runs it and formats the result. One adapter per database engine. |
| `ask-knowledge-graph` | Read and write over the four `ask-*` OpenSearch indices, the semantic layer as the agent sees it. |
| `ask-llm-gateway` | The single door to every model provider, plus embeddings and token accounting. |
| `ask-admin-api` | The API behind ASK Studio: authoring, enrichment and ingestion. A separate pod from the orchestrator, and a separate audience. |
| `ask-schema-service` | Answers schema questions, *what columns does VBAK have*, without running a query. |
| `ask-docs-service` | Answers documentation questions from the ingested corpus. |
| `ask-action-execution` | Performs write-back actions through MCP. |

How these fit together, in prose and diagrams:
[Concepts and architecture](../docs/02-concepts.md). How the three engines differ:
[The three chat engines](../docs/explain/engines.md).
