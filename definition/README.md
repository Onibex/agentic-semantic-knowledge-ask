# ASK — Agentic Semantic Knowledge Definition

> A YAML specification for AI-ready data products. The semantic foundation for Agentic AI on enterprise data.

[![Spec: ask-spec 1.0](https://img.shields.io/badge/spec-ask--spec%201.0-orange.svg)](#specification-version)
[![Maintained by: Onibex](https://img.shields.io/badge/Maintained%20by-Onibex-black.svg)](https://onibex.com)

---

> **New here?** Start with the [repository overview](../README.md) for the big picture and the companion **Onibex ASK Platform** manual. This document is the normative specification.

## What is ASK?

**Agentic Semantic Knowledge (ASK)** is a YAML specification that describes enterprise data in a way AI agents can actually understand, reason over, and act on.

LLMs and agents are good at generating SQL, calling tools, and chaining steps. They are bad at knowing *which* table answers *which* business question, what `MATNR` means, why `VBAK.GBSTK = 'C'` means an order is closed, or which join path is the cheapest one to traverse. Without that context, agents either hallucinate or refuse.

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
│   ┌─────────┐   relationships   ┌─────────┐    composed_of    ┌──┐ │
│   │  GOLD   │ ───────────────►  │ SILVER  │ ◄───────────────  │BR│ │
│   │ Business│                   │  Found. │                   │ON│ │
│   │  Logic  │   (drill / enrich)│  Data   │                   │ZE│ │
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

The YAML keys keep the `entity_` prefix (`entity_role`, `entity_grain`, `target_entity`). That split is deliberate and stable: "Data Product" is the term for humans, `entity_` is the machine vocabulary, and renaming the keys would break every catalog and reference that points at them.

| Layer | Concept | Purpose | Agent visibility |
|-------|---------|---------|------------------|
| **🥇 Gold** | Business Logic Data Product | Encodes a business definition (e.g. "Available-to-Sell Inventory", "Open Sales Order Tracker"). Semantically pre-resolved, denormalized, and ready to answer business questions directly. | **Primary** — agents prefer Gold |
| **🥈 Silver** | Foundational Data Product | Encodes a real-world enterprise artifact (Customer, Product, Sales Order). Composed of one or more Bronze nodes joined into a coherent business entity. Reusable across many Gold products. | **Fallback** — agents use Silver when no Gold matches |
| **🥉 Bronze** | Raw node / table | A faithful, mostly-uninterpreted representation of a source system table or node. | **Avoid** — not recommended as agent context |

### Intent Resolution priority

When an agent receives a natural-language question, the layers are ranked in this order:

```
1. GOLD    → "Is there a Business Logic Data Product that already answers this?"
2. SILVER  → "Is there a Foundational Data Product I can compose an answer from?"
3. BRONZE  → (skipped by default — not good agent context)
```

This is a **priority, not a sequence of passes.** A resolver is free to search the whole catalog at once and then rank what it found — what the contract fixes is the *outcome*: a Gold that answers the question outranks a Silver that could compose one, and Bronze is not an answer surface at all. Expressing the priority as re-ranking rather than a layer-by-layer walk is what makes a single retrieval pass sufficient.

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

Here is the shape of a Gold Business Logic Data Product (full example: [`examples/gold/gold_s4h_open_order_tracker.yaml`](examples/gold/gold_s4h_open_order_tracker.yaml)):

```yaml
id: "gold_s4h_open_order_tracker"
layer: "gold"
name: "open_order_tracker"
business_process: "ORDER TO CASH"
module: ["SD"]
description: "Sales-order-item-level OTC snapshot. Denormalized with customer,
              plant, material, full org hierarchy, delivery context, and derived
              order_status (OPEN/CLOSE). Use for fulfillment and prioritization."
entity_role: "fact"
db_table_name: "GOLD_SD_OPEN_ORDER_TRACKER"
grain:
  entity_grain: ["client", "sales_order", "item"]
  business_grain: "sales_order_item_level"

fields:
  - name: "order_qty"
    field_role: "measure"
    type: "DECIMAL"
    description: "Quantity the customer ordered on this line."
    aggregation_behavior: "SUM"

  - name: "order_status"
    field_role: "status_flag"
    type: "STRING(5)"
    description: "Derived OPEN/CLOSE classification. Rule: GBSTK='C' -> CLOSE,
                  else OPEN. Use this for binary 'is the order still active?'."

relationships:
  - target_entity: "silver_s4h_sd_customer_master"
    relationship_type: "many_to_one"
    join_condition: "GOLD_SD_OPEN_ORDER_TRACKER.customer_id = SILVER_SD_CUSTOMER_MASTER.kunnr_kna1"
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
├── examples/                          ← organised by LAYER, never by module
│   ├── gold/                          ← 4 Business Logic Data Products
│   ├── silver/                        ← 12 Foundational Data Products
│   └── bronze/                        ← 15 raw nodes (the lineage of sales_order, trading_goods, inv_mov_stock and plant)
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

## Specification version

**ask-spec 1.0.**

The specification carries its own version, separate from the release number of
the repository. They answer different questions: the release says which build of
the Onibex ASK Platform you are running, and the specification version says
which contract your YAML is written against. The platform will iterate far more
often than the contract, and a breaking change there should not tell everyone
who adopted the specification that their files need revisiting.

Two digits, no patch level: a contract does not get bugfixes, it gets changes.

| | When it moves |
|---|---|
| **MAJOR** — `2.0` | A document valid under the previous version stops being valid: a required field is removed or renamed, or resolution semantics change. |
| **MINOR** — `1.1` | Additions that leave existing documents valid: a new optional field, a new layer of documentation, clarified wording. |

Not to be confused with the `version:` field inside each data product, which
belongs to that artifact — it tracks the evolution of one entity, not of the
contract that describes it.

---

## Roadmap

- [x] Draft v1 of Bronze, Silver, Gold layer specifications
- [x] Reference SAP ECC examples (SD and MM modules)
- [ ] Refresh the reference examples on S/4HANA, adding PP
- [ ] Examples for non-SAP source systems (Salesforce, Siemens, etc)
- [ ] Conformance test suite

---

## Contributing

ASK is a **published, vendor-neutral specification**: anyone can read it, adopt
it, and describe their data products with it. It is not open source — the text
is source-available under [LICENSE](LICENSE), and Onibex stewards it.
Contributions are welcome on that footing:

- **Specification proposals** — open an issue with `[RFC]` in the title.
- **New examples** — submit a PR adding a YAML under `examples/`.
- **Source-system coverage** — non-SAP examples are especially valuable.
- **Tooling** — validators, generators, linters, IDE plugins. Tooling you build
  around the specification is yours; the licence covers this repository's own
  material, not what you write against the contract.

Please open an issue to discuss substantial changes before submitting a PR.

By submitting a contribution you confirm that it is yours to give, and you grant
Onibex, LLC permission to include it in this repository and distribute it under
the terms of [LICENSE](LICENSE).

---


## Maintainers

ASK is initiated and maintained by **[Onibex, LLC](https://onibex.com)** The specification grew out of production work on **Onibex ASK (Agentic Semantic Knowledge)**, Onibex's three-layer agentic-AI runtime for SAP; Onibex publishes the YAML contract as source-available so it can be studied, evaluated, and discussed in the open. See the [repository overview](../README.md) for how this specification relates to the Onibex ASK Platform.

---

## Citation

If ASK is useful in your research or product, please cite it:

```bibtex
@misc{ask_semantic_model_2026,
  title  = {ASK: Agentic Semantic Knowledge — A YAML Specification for AI-Ready Data Products},
  author = {Onibex, LLC},
  year   = {2026},
  url    = {https://github.com/Onibex/agentic-semantic-knowledge-ask/tree/main/definition}
}
```

---

## License

The ASK specification is source-available and dual-licensed — see
[`LICENSE`](LICENSE): **PolyForm Strict License 1.0.0** (noncommercial use,
research, evaluation, and personal study, indefinitely) or **PolyForm Free
Trial License 1.0.0** (evaluate for your business for up to 32 consecutive
calendar days), at your option. Production or any other commercial use
requires a commercial license from [Onibex](https://onibex.com) — see
[`../COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md).
