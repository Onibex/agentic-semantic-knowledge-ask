# Reference examples

Thirty-one Data Products drawn from SAP SD and MM. They are **a shape to copy, not a catalog
to deploy** — reading one teaches the contract faster than the specification does.

| Layer | Count | What is here |
|---|---|---|
| [`gold/`](gold/) | 4 | Open Order Tracker, Inventory Position, Inventory Situation, Order Tracking Reception |
| [`silver/`](silver/) | 12 | Sales Order, Customer Master, Plant, Material Group and Hierarchy, Trading Goods, the sales organisation dimensions, Inventory Movement |
| [`bronze/`](bronze/) | 15 | The raw SAP tables the Silvers compose — VBAK, VBAP, MARA, MARC, MSEG and the rest |

## Where to start

**Read one Gold first.** [`gold/gold_s4h_open_order_tracker.yaml`](gold/gold_s4h_open_order_tracker.yaml)
is a business definition end to end: what *open* means, which measures matter, what it joins to.

**Then the Silver underneath it.** [`silver/sales_order.yaml`](silver/sales_order.yaml) shows
the part that is genuinely reusable — declared grain, measures, relationships, and the join
graph that stitches VBAK, VBAP and VBKD into one entity.

**Bronze last, if at all.** [`bronze/vbak.yaml`](bronze/vbak.yaml) is what ingestion generates
for you. Read it when you are modelling ingestion or tracing a number to its source.

Silver is where reuse lives; Gold is yours by definition. Two companies on identical S/4HANA
schemas need different Golds, because they run their business differently.

---

[← Back to the ASK specification](../README.md)
