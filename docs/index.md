![Onibex ASK, Agentic Semantic Knowledge. Plain-language questions in, governed deterministic SQL out](images/ask-banner.png)

# Onibex Agentic Semantic Knowledge (ASK)

> Ask your enterprise data a question in plain language. Get governed, deterministic
> SQL back, compiled from a business-vocabulary semantic layer and never guessed from
> raw schema.

[Repository](https://github.com/Onibex/agentic-semantic-knowledge-ask) ·
[Getting Started](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/platform/docs/GETTING_STARTED.md) ·
[Manual](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/platform/docs/README.md) ·
[Specification](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/definition/README.md) ·
[llms.txt](llms.txt)

**"Based on open sales orders for material ID TG12, do we have enough stock to cover that
demand?"**

A business user types that into ASK Chat. The question names no table, and answering it takes
two things the business tracks separately: what has been ordered, and what is on the shelf. ASK
resolves *open sales orders*, *material* and *stock* against a curated semantic layer, computes
the join between them deterministically, compiles SQL in your database's own dialect, runs it,
and answers.

![ASK Chat answering a stock-coverage question: the written answer, the key figures, the results table, and the generated SQL joining two Gold Data Products](images/ask-chat-answer.gif)

> The two Data Products are **Open Order Tracker** and **Inventory Position**. The join between
> them was computed, not written, and the SQL is on screen so you can check.

## Built around two halves

| | What it is |
|---|---|
| **[Onibex Agentic Semantic Knowledge Definition](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/definition/README.md)** | The published specification (`ask-spec 1.0`): a vendor-neutral YAML standard for describing AI-ready data products across Bronze, Silver and Gold. Runtime-neutral, so any vendor can adopt it. |
| **[Onibex Agentic Semantic Knowledge Platform](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/platform/README.md)** | The product that implements the standard end to end. Author the semantic layer in **ASK Studio**, then ask questions of it in **ASK Chat**. |

What that changes, next to a tool that reads your database schema directly:

| | Most text-to-SQL tools | **ASK** |
|---|---|---|
| **The table and column names** | Shown to the model, which may invent one | Never shown. The model picks from resolved Data Products |
| **The join between two tables** | Written by the model, by plausibility | **Computed**: the shortest declared path, by cost |
| **What "open order" means** | Whatever the model infers today | A definition you wrote, versioned in your git |
| **What one question can reach** | The whole schema | Only what a workspace allows |

## Quick start

Docker with Compose v2, and a few minutes for the first build.

```bash
git clone https://github.com/Onibex/agentic-semantic-knowledge-ask.git
cd agentic-semantic-knowledge-ask/platform
cp .env.example .env
docker compose up -d
```

Two values in `.env` have to be set before that last command gets you anywhere.
[Getting Started](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/platform/docs/GETTING_STARTED.md)
walks them, and the rest of the path from an empty machine to a real answer, in about 45
minutes.

## Where to go

- [Getting Started](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/platform/docs/GETTING_STARTED.md).
  An empty machine to a real answer, in about 45 minutes
- [The manual](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/platform/docs/README.md).
  Every page, grouped by what you are trying to do
- [Why not just point an LLM at the schema?](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/platform/docs/explain/why-not-raw-schema.md).
  What a curated semantic layer computes that a schema cannot say
- [Onibex Agentic Semantic Knowledge Definition](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/definition/README.md).
  The normative Bronze, Silver and Gold contract
- [llms.txt](llms.txt). Machine-readable summary for AI agents

## Licensing

Source-available, not open source. Both tracks are licensed under
[PolyForm Strict 1.0.0 OR PolyForm Free Trial 1.0.0](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/LICENSE),
at your option. Production or any other commercial use requires a
[commercial license](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/COMMERCIAL-LICENSE.md).
Contact contact@onibex.com.

Maintained by [Onibex, LLC](https://onibex.com), an SAP silver partner and a Confluent gold
partner building real-time SAP data hyperconnectivity for the enterprise.

Copyright (c) 2026 Onibex, LLC. All rights reserved.
