# Why not just point an LLM at the schema?

[Manual](../README.md) › [Understanding how it works](../README.md#understanding-how-it-works) › **Why not just point an LLM at the schema?**

> **Explanation.** Why ASK compiles against a curated semantic layer instead of the database
> schema, and what that changes about the answers. No procedure here, to author a layer see
> [Author the semantic layer · ASK Studio](../ask-studio/README.md).

| | |
|---|---|
| **Who** | Anyone evaluating ASK against a text-to-SQL tool that reads the schema directly |
| **Time** | ~5 minutes to read |
| **You'll end with** | A concrete account of which decisions are computed and which are conceded to the model |

---

## A schema does not say what anything means

It does not know that `MATNR` is a material number, that an *open order* means four status
fields agreeing, or which of six join paths between two tables is the correct one for a revenue
question.

An LLM given raw schema fills those gaps by guessing. It is confident, it is fluent, and it is
wrong in ways nobody catches until the number reaches a board deck. The failure is not that the
SQL is invalid: it runs, it returns rows, and the rows are plausible. That is what makes it
expensive.

## What changes, in four lines

| | Most text-to-SQL tools | **ASK** |
|---|---|---|
| **The table and column names** | Shown to the model, which may invent one | Never shown. The model picks from resolved Data Products |
| **The join between two tables** | Written by the model, by plausibility | **Computed**: the shortest declared path, by cost |
| **What "open order" means** | Whatever the model infers today | A definition you wrote, versioned in your git |
| **What one question can reach** | The whole schema | Only what a workspace allows |

Each of those is a decision the product makes rather than a claim it asserts:

- **The LLM chooses among resolved Data Products.** It never names a table.
- **Join paths are computed, not written.** Dijkstra runs over a declared relationship graph.
- **Retrieval is hybrid and ranked.** kNN plus BM25 plus RRF, over a curated vocabulary.
- **Everything is scoped.** A workspace allowlist decides what any question can reach.

## The graph the guessing has to replace

![The domain canvas: the Data Products of one business domain across Gold, Silver and Bronze, and the labelled relationships declared between them](../images/studio-canvas-domain.png)

That is one business domain: thirty-one Data Products, and every line between them a
relationship somebody declared. Each carries a join predicate, a cardinality, a traversal cost
and an aggregation-safety hint, which is what lets a path be **computed** rather than chosen.
Point an LLM at the raw schema and this graph does not exist; it has to guess its way across.

Inspecting that graph is a task rather than an argument:
[Inspect a domain as a graph](../ask-studio/04-domain-canvas.md).

## The condition this rests on

**ASK's determinism comes from the contract.** If nobody is going to author a semantic layer,
there is nothing for it to compile against. Importing a `CREATE TABLE` and letting AI draft the
layer is a fifteen-minute start, but somebody has to review what it drafted.

The scope itself is a workspace, and the definitions are yours: vendor-neutral YAML you
version, review and diff, not a modelling layer you rent.

---

## What's next

→ **[The three chat engines](engines.md)**, how much each engine computes rather than
concedes to the model.
→ **[Create workspaces and business domains](../ask-studio/01-workspaces-domains.md)**, the
scope that decides what a question can reach.
→ **[Onibex Agentic Semantic Knowledge Definition](../../../definition/README.md)**,
the normative contract the layer is written against.

---

[← Back to the manual](../README.md)
