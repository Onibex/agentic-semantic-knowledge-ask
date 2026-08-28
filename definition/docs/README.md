# The layer specifications

The normative rules for each layer of an ASK semantic layer. These three documents are the
contract; everything else in this repository derives from them.

- [Bronze](BRONZE_LAYER.md). A faithful, mostly-uninterpreted representation of a source
  table. Usually machine-generated, and never agent context.
- [Silver](SILVER_LAYER.md). A curated business entity that **owns the join topology**: how
  its underlying tables connect. The reusable layer.
- [Gold](GOLD_LAYER.md). A business definition, pre-joined and semantically resolved. The
  layer that answers a question the way *your* company asks it.

Read [the specification overview](../README.md) first for the resolution model, which layer
the agent reaches for, and why. For worked YAML, see [the examples](../examples/README.md).

---

[← Back to the ASK specification](../README.md)
