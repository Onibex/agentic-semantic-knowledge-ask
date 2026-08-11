# Agentic Semantic Knowledge (ASK)

> Turn natural-language questions into governed, deterministic SQL over enterprise
> data — grounded in a business-vocabulary semantic layer instead of raw schema.

This repository is the single home for **ASK**. It holds two complementary bodies of
work — the **ASK specification** and the **product** that implements it. Pick your path:

| If you want to… | Go to | What it is |
|---|---|---|
| **Learn the ASK specification** — how AI-ready data products are described in vendor-neutral YAML | **[`definition/`](definition/README.md)** | The **ASK specification**: Bronze / Silver / Gold layers, resolution priority, and reference examples. |
| **Use the Onibex ASK Platform** — install it, author a semantic layer, publish it, and query it from chat | **[`platform/`](platform/README.md)** | The **platform itself** — source code, Docker Compose stack, and the complete manual under [`platform/docs/`](platform/docs/README.md): ASK Studio, ASK Chat, ASK Setup. |

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

- **The specification** — [`definition/`](definition/README.md) — the runtime-neutral
  YAML contract. It describes *what a data product means*, not how it is built. Any
  vendor or team can adopt it.
- **The platform** — [`platform/`](platform/README.md) — **Onibex ASK Platform**, the
  product that implements the standard end to end: author the semantic layer in **ASK
  Studio**, wire up databases and models in **ASK Setup**, publish dev → prod, and let
  business users query it in plain language through **ASK Chat**.

---

## The three layers

Both halves of this repository speak the same vocabulary — a medallion model in which
every data product sits in one of three layers, and an agent resolves a question by
preferring the most business-ready layer first:

| Layer | What it is | Agent visibility |
|-------|------------|------------------|
| **Gold** | A business definition, pre-joined and semantically resolved (e.g. "Open Sales Order Tracker"). | **Primary** — preferred first |
| **Silver** | A reusable enterprise artifact (Customer, Product, Sales Order), composed from Bronze. | **Fallback** — used when no Gold fits |
| **Bronze** | A raw source table, mostly uninterpreted. | **Avoided** — lineage only, not agent context |

The [`definition/`](definition/README.md) folder gives the **normative rules** for each
layer; the [`platform/docs/`](platform/docs/README.md) manual shows how to **author
them** in the product.

---

## Repository layout

```
agentic-semantic-knowledge-ask/
├── README.md                 ← you are here
├── definition/               ← the ASK specification — PolyForm Strict 1.0.0
│   ├── README.md             ← spec overview + quick example
│   ├── docs/                 ← Bronze / Silver / Gold layer specifications
│   ├── examples/             ← reference YAML data products
│   └── LICENSE               ← PolyForm Strict 1.0.0
└── platform/                 ← Onibex ASK Platform (the product) — PolyForm Strict 1.0.0
    ├── README.md             ← product front door + quick start
    ├── LICENSE.md            ← PolyForm Strict 1.0.0
    ├── docker-compose.yml    ← the whole stack (OpenSearch, Keycloak, APIs, 3 SPAs)
    ├── packages/             ← typed Python packages (orchestrator, admin-api, …)
    ├── ask-admin-spa/        ← ASK Studio (React)
    ├── ask-chat-spa/         ← ASK Chat (React)
    ├── ask-setup-spa/        ← ASK Setup (React)
    └── docs/                 ← product manual + engine docs
        ├── README.md         ← manual index (read in order / by area)
        ├── 01-installation.md
        ├── 02-concepts.md
        ├── ask-admin/        ← semantic-layer authoring flows
        ├── ask-chat/         ← using the chat (end users)
        └── reference/        ← glossary + troubleshooting
```

---

## Where to start

- **New to the concepts?** Read the standard overview → [`definition/README.md`](definition/README.md).
- **Deploying or using the product?** Start with
  [Installation](platform/docs/01-installation.md), then
  [Concepts & Architecture](platform/docs/02-concepts.md), then the
  [ASK Studio flows](platform/docs/ask-admin/00-overview.md).

---

## License

The two tracks of this repository are licensed individually — see the
[`LICENSE`](LICENSE) map for the authoritative table:

- **`definition/`** — the ASK specification, under **PolyForm Strict 1.0.0**
  ([`definition/LICENSE`](definition/LICENSE)).
- **`platform/`** — the Onibex ASK Platform, under **PolyForm Strict 1.0.0**
  ([`platform/LICENSE.md`](platform/LICENSE.md)).

Both are **source-available**: noncommercial use, research, evaluation, and personal
study are permitted; commercial or production use requires a commercial license from
[Onibex](https://onibex.com).

"Onibex", "ASK", and the Onibex logos are trademarks of Onibex, Inc. and are excluded
from both licenses.

---

## Maintainers

ASK is initiated and maintained by **[Onibex, Inc.](https://onibex.com)** — an SAP
Silver Partner and Confluent Gold Partner building real-time SAP data hyperconnectivity
for the enterprise.

> *"Tables don't think. Schemas don't reason. ASK is what an agent reads when it needs
> to know what your data means."*
