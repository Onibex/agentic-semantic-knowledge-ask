# Agentic Semantic Knowledge (ASK)

> Turn natural-language questions into governed, deterministic SQL over enterprise
> data — grounded in a business-vocabulary semantic layer instead of raw schema.

This repository is the single home for **ASK**. It holds two complementary bodies of
work — an **open standard** and the **product** that implements it. Pick your path:

| If you want to… | Go to | What it is |
|---|---|---|
| **Adopt the open standard** — describe your own AI-ready data products in vendor-neutral YAML | **[`definition/`](definition/README.md)** | The open **ASK specification**: Bronze / Silver / Gold layers, resolution priority, and reference examples. Licensed AGPL-3.0. |
| **Use the Onibex ASK Platform** — install it, author a semantic layer, publish it, and query it from chat | **[`platform/`](platform/README.md)** | The complete, screenshot-driven **product manual**: ASK Admin, the Configuration app, and the Chat. |

---

## What is ASK?

**Agentic Semantic Knowledge (ASK)** is a way to describe enterprise data so that AI
agents can understand it, reason over it, and act on it reliably.

LLMs are good at writing SQL and chaining steps, but bad at knowing *which* table
answers *which* business question, what a cryptic code like `MATNR` means, or which
join path is cheapest. Without that context they hallucinate or refuse. ASK closes the
gap by formalizing the **business semantics** of data — entities, grains, measures,
statuses, relationships, and intent — into a layered contract any agent runtime can
consume.

This repository expresses that idea at two levels:

- **The standard** — [`definition/`](definition/README.md) — the open, runtime-neutral
  YAML contract. It describes *what a data product means*, not how it is built. Any
  vendor or team can adopt it.
- **The platform** — [`platform/`](platform/README.md) — **Onibex ASK Platform**, the
  product that implements the standard end to end: author the semantic layer in **ASK
  Admin**, wire up databases and models in the **Configuration app**, publish
  dev → prod, and let business users query it in plain language through the **Chat**.

---

## Repository layout

```
agentic-semantic-knowledge-ask/
├── README.md                 ← you are here
├── definition/               ← the open ASK specification (the standard) — AGPL-3.0
│   ├── README.md             ← spec overview + quick example
│   ├── docs/                 ← Bronze / Silver / Gold layer specifications
│   ├── examples/             ← reference YAML data products
│   └── LICENSE               ← AGPL-3.0
└── platform/                 ← Onibex ASK Platform user manual (the product)
    ├── README.md             ← manual index (read in order / by area)
    ├── 01-installation.md
    ├── 02-concepts.md
    ├── ask-admin/            ← semantic-layer authoring flows
    ├── config/               ← technical configuration (DB, LLM, OpenSearch, SAP, MCP…)
    ├── chat/                 ← using the chat (end users)
    ├── reference/            ← glossary + troubleshooting
    └── images/               ← manual screenshots
```

---

## Where to start

- **New to the concepts?** Read the standard overview → [`definition/README.md`](definition/README.md).
- **Deploying or using the product?** Start with
  [Installation](platform/01-installation.md), then
  [Concepts & Architecture](platform/02-concepts.md), then the
  [ASK Admin flows](platform/ask-admin/00-overview.md).

---

## Licensing

This repository intentionally carries two different licensing regimes, one per top-level
folder:

- **`definition/` (the specification)** is open source under **AGPL-3.0** — see
  [`definition/LICENSE`](definition/LICENSE). Onibex publishes the YAML contract so any
  vendor, customer, or community member can adopt, extend, or implement it without
  lock-in.
- **`platform/` (the product manual)** is **Onibex product documentation**,
  © Onibex, Inc. It is provided to help you operate the Onibex ASK Platform and is not
  covered by the AGPL-3.0 license above.

---

## Maintainers

ASK is initiated and maintained by **[Onibex, Inc.](https://onibex.com)** — an SAP
Silver Partner and Confluent Gold Partner building real-time SAP data hyperconnectivity
for the enterprise.

> *"Tables don't think. Schemas don't reason. ASK is what an agent reads when it needs
> to know what your data means."*
