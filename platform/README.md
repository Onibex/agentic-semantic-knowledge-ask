# Onibex ASK Platform

Turn a question in plain language into **governed SQL** over the data you already have. Ask
*"total net sales by region last quarter"*; the platform resolves your business terms against a
curated **semantic layer**, computes the join path deterministically, compiles SQL in your
database's own dialect, runs it, and returns a written answer with a table, an automatic chart
and the query behind it.

The agent never invents a column or guesses a join. It can only use Data Products an author has
defined and **published** — which is what makes an answer reproducible, and what makes it
auditable when someone asks where a number came from.

![ASK Chat answering a stock-coverage question: the written answer, the key figures, the results table, and the generated SQL joining two Gold Data Products](docs/images/ask-chat-answer.gif)

> **New here?** [Getting Started](docs/GETTING_STARTED.md) takes you from an empty machine to a
> real answer in about 45 minutes, and makes every choice for you along the way.

← [Repository overview](../README.md) · 📖 **[The complete manual](docs/README.md)**

---

## The surfaces

Three applications, but not three peers. **ASK Setup is a prerequisite**: until it holds a
database connection and a model provider, Studio has nothing to publish against and Chat has
nothing to answer from. Whoever owns the infrastructure configures it once and then stops
opening it.

| Surface | Audience | Purpose |
|---|---|---|
| **ASK Setup** | Platform engineer | The technical precondition: databases, LLM and embedding providers, identity. Everything encrypted at rest. |
| **ASK Studio** | Data steward / analyst | Author and publish the semantic layer: workspaces, business domains, Data Products. |
| **ASK Chat** | Business user | Ask questions in plain language and read the answers. |

## Quick start

```bash
docker compose up -d
```

| Surface | Default local URL |
|---|---|
| ASK Setup | `http://localhost:5175` |
| ASK Studio | `http://localhost:5173` |
| ASK Chat | `http://localhost:5174` |
| Keycloak (sign-in) | `http://localhost:8180` |

First boot builds images and bootstraps OpenSearch, so give it a few minutes. Two environment
variables must be set before that command gets you anywhere — `ONIBEX_ENCRYPTION_KEY` and
`SEMANTIC_LAYER_HOST_PATH`. Both, and the startup order, are in
[Install and run the platform](docs/01-installation.md).

## Documentation

| You want to… | Read |
|---|---|
| **See everything** | **[The manual](docs/README.md)** — every page, grouped by what you are trying to do |
| **Try it for the first time** | [Getting Started](docs/GETTING_STARTED.md) — one guided path, empty machine to a real answer |
| **Install it** | [Install and run the platform](docs/01-installation.md) — every variable, the startup order, the gotchas |
| **Understand the shape of it** | [Concepts and architecture](docs/02-concepts.md) — the mental model, with diagrams |
| **Configure it** | [Configure the platform first · ASK Setup](docs/ask-setup/README.md) |
| **Author a semantic layer** | [Author the semantic layer · ASK Studio](docs/ask-studio/README.md) |
| **Ask questions** | [Ask questions · ASK Chat](docs/ask-chat/README.md) |
| **Know how governed the answers are** | [The three chat engines](docs/explain/engines.md) — what is computed rather than guessed |
| **Run it in production** | [Operating the platform](docs/runbooks/README.md) |

The normative Bronze / Silver / Gold rules are not here. They are the
[ASK specification](../definition/README.md) — a separate track of this repository, with its own
licence and its own version policy.

## Technology

- **Orchestration:** LangGraph — intent resolution → SQL generation → execution, with three
  engines that differ in what they compute rather than guess.
- **LLM and embeddings:** pluggable. SAP AI Core for managed models, or any LiteLLM provider
  (Anthropic, OpenAI, AWS Bedrock, Databricks and others), chosen in ASK Setup.
- **Semantic search:** OpenSearch, hybrid kNN + BM25 with reciprocal rank fusion.
- **Target databases:** SAP HANA, PostgreSQL, Snowflake, Databricks, Google BigQuery,
  ClickHouse, Microsoft SQL Server, Microsoft Fabric, IBM Db2 and Presto — each with its own SQL
  generator and its own execution adapter, not a generic fallback. Which drivers ship in your
  image is one build variable, `EXECUTOR_EXTRAS`.
- **Backend:** typed Python packages with enforced boundaries — see
  [`packages/`](packages/README.md).
- **Frontends:** three React SPAs served by Nginx.

## License

The Onibex ASK Platform is source-available and dual-licensed — see
[`LICENSE.md`](LICENSE.md): **PolyForm Strict License 1.0.0** (noncommercial use, research,
evaluation, and personal study, indefinitely) or **PolyForm Free Trial License 1.0.0**
(evaluate for your business for up to 32 consecutive calendar days — for example via
`docker compose up`), at your option. Production or any other commercial use requires a
commercial license from [Onibex](https://onibex.com) — see
[`../COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md).

"Onibex", "ASK", and the Onibex logos are trademarks of Onibex, LLC and are excluded from the
license. This platform also references, without redistributing under this license, third-party
software including SAP HANA, SAP BTP, and SAP AI Core (trademarks of SAP SE), OpenSearch (a
registered trademark of Amazon Web Services), and Keycloak (a trademark of Red Hat, Inc.) — see
[`../THIRD-PARTY-NOTICES.md`](../THIRD-PARTY-NOTICES.md).

## Support

Found something inaccurate or confusing in the documentation? That is a bug, and reporting it is
a contribution — [`SUPPORT.md`](../SUPPORT.md) says where each kind of question goes, and
[`CONTRIBUTING.md`](../CONTRIBUTING.md) how a change is reviewed. Vulnerabilities go through
[`SECURITY.md`](../SECURITY.md), never a public issue.
