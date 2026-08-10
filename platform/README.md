# Onibex ASK Platform

Turn natural-language questions into **governed SQL** over your SAP data. Ask
*"total net sales by region last quarter"* in plain language; the platform resolves your
business terms against a curated **semantic layer**, builds the correct SQL (with the right
joins), runs it against SAP HANA or PostgreSQL, and returns a written answer plus a table
and an automatic chart.

The agent never invents columns or guesses joins — it can only use Data Products an
administrator has defined and **published**. That is what makes answers reproducible and
trustworthy.

> **New here? Start with the [Getting Started guide](docs/GETTING_STARTED.md)** — it takes
> you from zero to your first answered question, for both administrators and business users.

## Surfaces

| Surface | Audience | Purpose |
|---|---|---|
| **ASK Studio** (React) | Administrator / data steward | Author & publish the semantic layer: workspaces, business domains, Data Products. |
| **ASK Setup** (React) | Administrator | Technical setup: database connections, LLM/embeddings provider, identity. |
| **ASK Chat** (React) | Business user | Ask questions in natural language and read the answers. |

## Quick start (local, Docker)

The platform runs as a multi-service stack via Docker Compose. See the install runbook for
prerequisites (environment variables, encryption key, semantic-layer repo):

```bash
docker compose up -d
```

Then open:

| Surface | Default local URL |
|---|---|
| ASK Studio (admin) | http://localhost:5173 |
| ASK Chat | http://localhost:5174 |
| ASK Setup | http://localhost:5175 |
| Login (Keycloak) | http://localhost:8180 |

Full setup and environment variables are in
[`docs/runbooks/local-development.md`](docs/runbooks/local-development.md).

## Documentation

| For… | Read |
|---|---|
| **Getting started (everyone)** | [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md) |
| **Authoring the semantic layer** | [`docs/semantic-layer/`](docs/semantic-layer/) |
| **How the SQL engines work** | [`docs/FLASH.md`](docs/FLASH.md) · [`docs/PRECISE.md`](docs/PRECISE.md) · [`docs/SMART.md`](docs/SMART.md) |
| **Architecture & developer overview** | [`CLAUDE.md`](CLAUDE.md) |
| **Install & deploy** | [`docs/runbooks/`](docs/runbooks/) |

## Technology

- **Orchestration:** LangGraph (intent resolution → SQL generation → execution).
- **LLM & embeddings:** pluggable — SAP AI Core (managed) or any LiteLLM provider
  (Anthropic, OpenAI, AWS Bedrock, Databricks, …) via the Setup SPA.
- **Semantic search:** OpenSearch (hybrid kNN + BM25).
- **Target databases:** SAP HANA Cloud or PostgreSQL.
- **UIs:** three React SPAs (admin, chat, setup) served by Nginx.

See [`CLAUDE.md`](CLAUDE.md) for the authoritative architecture and package layout.

## License

The Onibex ASK Platform is source-available under the
**PolyForm Strict License 1.0.0** — see [`LICENSE.md`](LICENSE.md). Noncommercial use,
research, evaluation, and personal study are permitted; commercial or production use
requires a commercial license from [Onibex](https://onibex.com).

"Onibex", "ASK", and the Onibex logos are trademarks of Onibex, Inc. and are excluded
from the license.

## Support

Found something inaccurate or confusing in the docs? That's a documentation bug — open an
issue or contact the platform team.
