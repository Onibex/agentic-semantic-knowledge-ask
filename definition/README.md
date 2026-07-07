# ASK — Agentic Semantic Knowledge Definition

> An open YAML specification for AI-ready data products. The semantic foundation for Agentic AI on enterprise data.

[![Spec: ](https://img.shields.io/badge/Spec-%20v1-orange.svg)]()
[![Maintained by: Onibex](https://img.shields.io/badge/Maintained%20by-Onibex-black.svg)](https://onibex.com)

---

## What is ASK?

**Agentic Semantic Knowledge (ASK)** is an open YAML specification that describes enterprise data in a way AI agents can actually understand, reason over, and act on.

LLMs and agents are good at generating SQL, calling tools, and chaining steps. They are bad at knowing *which* table answers *which* business question, what `MATNR` means, why `VBUK.GBSTK = 'C'` means an order is closed, or which join path is the cheapest one to traverse. Without that context, agents either hallucinate or refuse.

ASK fixes this by formalizing the **business semantics** of data — entities, grains, measures, statuses, relationships, and intent — into a layered specification that any agent runtime can consume.

```
┌────────────────────────────────────────────────────────────────────┐
│                        AGENT / LLM RUNTIME                         │
│              (Claude, GPT, Llama, custom orchestrators)            │
└────────────────────────────────────────────────────────────────────┘
                                  ▲
                                  │ resolves intent against
                                  │
┌────────────────────────────────────────────────────────────────────┐
│                      ASK YAML SPECIFICATION                        │
│                                                                    │
│   ┌─────────┐    composed_of    ┌─────────┐    composed_of    ┌──┐ │
│   │  GOLD   │ ◄───────────────  │ SILVER  │ ◄───────────────  │BR│ │
│   │ Business│                   │  Found. │                   │ON│ │
│   │  Logic  │                   │  Data   │                   │ZE│ │
│   │   DPs   │                   │  Prods  │                   │  │ │
│   └─────────┘                   └─────────┘                   └──┘ │
│   ▲ priority                    ▲ fallback                  ▲ raw  │
│   1st                           2nd                         skip   │
└────────────────────────────────────────────────────────────────────┘
```

ASK is **declarative**, **runtime-agnostic**, and **business-vocabulary-first**. It does not generate the data products — it describes them so agents know what they are.

---

## Why ASK exists

Most enterprises sit on top of decades of OLTP systems (SAP, Oracle, Salesforce, Workday, etc.) where:

- Tables have cryptic names (`VBAK`, `EKKO`, `MARA`).
- Columns are 3–5 letter abbreviations in a foreign language (`MATNR`, `KUNNR`, `WERKS`).
- Business meaning lives in tribal knowledge, not metadata.
- Status fields use single-character codes whose meaning is buried in customizing tables.
- The same business concept (an "open order") is computed differently across teams.

You cannot point an LLM at this and expect it to act reliably. Even Retrieval-Augmented Generation (RAG) over schema descriptions fails, because the model still needs to *resolve a question to the right entity, the right grain, and the right join path*.

ASK exists to provide the missing semantic layer between the agent and the warehouse — encoding not just *what the data is* but *what business question it answers*, *how safe it is to aggregate*, and *which path to traverse first*.

---

## The three layers

ASK organizes data products into three layers. **Entities, Business Objects, and Data Products are equivalent terms** — ASK uses "Data Product" throughout.

| Layer | Concept | Purpose | Agent visibility |
|-------|---------|---------|------------------|
| **🥇 Gold** | Business Logic Data Product | Encodes a business definition (e.g. "Available-to-Sell Inventory", "Open Sales Order Tracker"). Semantically pre-resolved, denormalized, and ready to answer business questions directly. | **Primary** — agents prefer Gold |
| **🥈 Silver** | Foundational Data Product | Encodes a real-world enterprise artifact (Customer, Product, Sales Order). Composed of one or more Bronze nodes joined into a coherent business entity. Reusable across many Gold products. | **Fallback** — agents use Silver when no Gold matches |
| **🥉 Bronze** | Raw node / table | A faithful, mostly-uninterpreted representation of a source system table or node. | **Avoid** — not recommended as agent context |

### Intent Resolution priority

When an agent receives a natural-language question, the resolver walks the catalog in this order:

```
1. GOLD    → "Is there a Business Logic Data Product that already answers this?"
2. SILVER  → "Is there a Foundational Data Product I can compose an answer from?"
3. BRONZE  → (skipped by default — not good agent context)
```

**Why Bronze is skipped:** A raw table like `VBAK` has no notion that `GBSTK='C'` means "closed", that `VDATU` is the *requested* delivery date (not actual), or how it joins to `VBAP`. Giving agents Bronze leaks raw schema noise and almost always produces wrong SQL. Bronze exists to be **lineage** for Silver and Gold — not the agent surface.

---

## What ASK does *not* describe

ASK is the **structural and semantic contract** of a data product, not its **build logic**.

- ❌ ETL / ELT code, Spark jobs, dbt models, SQLMesh transforms
- ❌ Aggregations, deduplication rules, slowly-changing-dimension logic
- ❌ Validations, data-quality checks, business-rule engines
- ✅ The **resulting structure** that those pipelines produce
- ✅ The **business meaning** of that structure
- ✅ The **relationships** between entities

If your Gold "Available-to-Sell" data product is built by a 400-line dbt model, ASK does not care about the 400 lines. ASK cares about the columns, grains, measures, statuses, and joins that come *out* of those 400 lines — because that is what the agent needs to reason about.

---

## Quick example

Here is the shape of a Gold Business Logic Data Product (full example: [`examples/gold/gold_ecc_sd_open_order_tracker.yaml`](examples/gold/gold_ecc_sd_open_order_tracker.yaml)):

```yaml
id: "gold_ecc_open_order_tracker"
layer: "gold"
name: "open_order_tracker"
business_process: "OTC"
module: ["SD", "MM"]
description: "Sales-order-item-level OTC snapshot. Denormalized with customer,
              plant, material, full org hierarchy, delivery context, and derived
              order_status (OPEN/CLOSE). Use for fulfillment and prioritization."
entity_role: "fact"
grain:
  entity_grain: ["client", "sales_order", "item"]
  business_grain: "sales_order_item_level"

composed_of: ["dataproduct.GOLD_SD_OPEN_ORDER_TRACKER"]

fields:
  - name: "order_qty"
    field_role: "measure"
    type: "NUMERIC"
    description: "Quantity ordered by customer / demand quantity"
    aggregation_behavior: "SUM"

  - name: "order_status"
    field_role: "status_flag"
    type: "TEXT"
    description: "Derived OPEN/CLOSE classification. Rule: GBSTK='C' -> CLOSE,
                  else OPEN. Use this for binary 'is the order still active?'."

relationships:
  - target_entity: "silver_ecc_sd_customer_master"
    relationship_type: "many_to_one"
    semantic_label: "ordered_by"
    traversal_cost: 1
    aggregation_safety: "safe"
```

An agent reading this knows:

- This data product answers questions about **open sales orders** in the **OTC** process.
- Its grain is **one row per sales-order item** — safe to count, safe to sum `order_qty`.
- `order_status` is already derived — no need to re-implement the `GBSTK` rule.
- Customer details are one cheap join away (`traversal_cost: 1`, `aggregation_safety: safe`).

That is enough context for a Gold-quality SQL plan. No raw schema needed.

---

## Repository structure

```
definition/               # (this folder inside agentic-semantic-knowledge-ask)
├── README.md                          ← you are here
├── docs/
│   ├── GOLD_LAYER.md                  ← Gold layer specification
│   ├── SILVER_LAYER.md                ← Silver layer specification
│   └── BRONZE_LAYER.md                ← Bronze layer specification
├── examples/
│   ├── gold/
│   │   ├── gold_ecc_sd_open_order_tracker.yaml
│   │   └── gold_ecc_order_tracking_reception.yaml
│   ├── silver/
│   │   ├── sales_order.yaml
│   │   └── trading_goods.yaml
│   └── bronze/
│       ├── mara.yaml
│       └── vbak.yaml
└── LICENSE
```

---

## Layer documentation

Each layer has its own normative specification:

- **[Gold Layer Specification](docs/GOLD_LAYER.md)** — Business Logic Data Products. Pre-joined, semantically resolved, agent-first.
- **[Silver Layer Specification](docs/SILVER_LAYER.md)** — Foundational Data Products. Reusable enterprise artifacts (Customer, Product, Sales Order).
- **[Bronze Layer Specification](docs/BRONZE_LAYER.md)** — Raw nodes and tables. Lineage substrate, not agent context.

---

## Multiple variants per data product

A real enterprise rarely has *one* "Trading Goods" or *one* "Sales Order". A data practitioner may need multiple variants of the same Foundational Data Product to reflect business reality:

- A company with two lines of business may publish `silver_lob_a_trading_goods` and `silver_lob_b_trading_goods` with different attributes per line.
- A multi-region enterprise may publish `silver_emea_sales_order` and `silver_americas_sales_order` with different sales-org constraints.

This is intentional. **A composable AI Data Strategy depends on the data practitioner choosing the right level of variant granularity.** ASK provides the structural language; the catalog topology is a business decision.

---

## How ASK compares to other specs

ASK is influenced by — and complementary to — other open semantic-modeling efforts:

| Project | Focus | Relationship to ASK |
|---------|-------|---------------------|
| [AtScale SML](https://github.com/semanticdatalayer/SML) | Universal semantic-model spec for BI/analytics tools | ASK shares the layered, YAML-first, BI-friendly approach. ASK adds explicit Bronze/Silver/Gold layering and an **agent-resolution priority** for LLMs. |
| [Snowflake Semantic Model Generator](https://github.com/Snowflake-Labs/semantic-model-generator) | YAML semantic model for Snowflake Cortex Analyst (text-to-SQL) | ASK shares the goal of grounding LLM SQL generation in business semantics. ASK is platform-agnostic and adds layered composition, relationship costing, and aggregation safety. |
| [Cube](https://github.com/cube-js/cube) | Headless semantic layer with REST/GraphQL/SQL APIs | Cube is a runtime; ASK is a spec. ASK can describe entities that a Cube schema serves, and vice versa — they are complementary. |

ASK is deliberately **runtime-neutral**. You can serve an ASK catalog from Cube, dbt, Snowflake, Databricks Unity Catalog, SAP HANA, or a custom resolver — the YAML does not care.

---

## Who should adopt ASK?

- **Data platform teams** building agent-native data products on top of warehouses or lakehouses.
- **Enterprise architects** designing semantic layers across SAP, Oracle, Salesforce, and other transactional systems.
- **AI engineers** integrating text-to-SQL, GenBI, or autonomous agents on enterprise data.
- **Data practitioners** wanting a portable, vendor-neutral way to describe Foundational and Business Logic Data Products.

ASK was forged on SAP ECC and S/4HANA workloads, but the spec is source-system agnostic. Examples for Salesforce, Workday, NetSuite, and other systems are welcome via PR.

---

## Roadmap

- [x] Draft v1 of Bronze, Silver, Gold layer specifications
- [x] Reference SAP ECC examples (SD, MM, PP modules)
- [ ] Examples for non-SAP source systems (Salesforce, Siemens, etc)
- [ ] Conformance test suite

---

## Contributing

ASK is an open specification. Contributions are welcome:

- **Specification proposals** — open an issue with `[RFC]` in the title.
- **New examples** — submit a PR adding a YAML under `examples/`.
- **Source-system coverage** — non-SAP examples are especially valuable.
- **Tooling** — validators, generators, linters, IDE plugins.

Please open an issue to discuss substantial changes before submitting a PR.

---


## Maintainers

ASK is initiated and maintained by **[Onibex, Inc.](https://onibex.com)** — an SAP Silver Partner and Confluent Gold Partner building real-time SAP data hyperconnectivity for the enterprise.

The specification grew out of production work on **Onibex ASK (Agentic Semantic Knowledge)**, Onibex's three-layer agentic-AI runtime for SAP. Onibex is open-sourcing the YAML contract so that any vendor, customer, or community member can adopt, extend, or implement it without lock-in.

> *"Tables don't think. Schemas don't reason. ASK is what an agent reads when it needs to know what your data means."*

---

## Citation

If ASK is useful in your research or product, please cite it:

```bibtex
@misc{ask_semantic_model_2026,
  title  = {ASK: Agentic Semantic Knowledge — An Open YAML Specification for AI-Ready Data Products},
  author = {Onibex, Inc.},
  year   = {2026},
  url    = {https://github.com/Onibex/agentic-semantic-knowledge-ask/tree/main/definition}
}
```
