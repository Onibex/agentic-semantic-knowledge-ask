# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

from dataclasses import dataclass
from enum import Enum


class JoinType(str, Enum):
    """Edge-registry join type.

    NOTE: this is a DIFFERENT key from `JoinCondition.join_type` on
    `join_graph[]` (nodes.py), which the origin spec defines in Sec 6.4 as
    INNER | LEFT OUTER | RIGHT OUTER | CROSS. The spec defines no join_type on
    `relationships[]` at all — Sec 6.5 edges carry only `join_condition` — so
    this enum is an ASK-local extension. `CROSS` is included so that the two
    same-named keys cannot diverge, and `FULL OUTER` is kept for the documents
    already written with it; in practice the writer only ever emits LEFT OUTER
    (forward) and RIGHT OUTER (reverse).
    """

    INNER = "INNER"
    LEFT_OUTER = "LEFT OUTER"
    RIGHT_OUTER = "RIGHT OUTER"
    FULL_OUTER = "FULL OUTER"
    CROSS = "CROSS"


class Cardinality(str, Enum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"


@dataclass
class JoinCondition:
    left_field: str
    right_field: str
    operator: str = "="


@dataclass
class RelationEdge:
    """
    Representa una arista (JOIN) en nuestro Edge Registry.
    """

    source_node: str
    target_node: str
    join_type: JoinType
    conditions: list[JoinCondition]
    cardinality: Cardinality
    traversal_cost: float = 1.0  # El peso para el algoritmo de Dijkstra
    is_reverse: bool = False  # Flag para los ejes inversos autogenerados

    # ─── Fields below were indexed by the writer but had no slot here ───────────
    # Everything above was all `get_all_edges` could reconstruct, so the rest was
    # dropped on read even when present in the document.

    # Physical table of each side (`db_table_name`). Carried so consumers never have
    # to infer that `gold_s4h_inventory_situation` and `GOLD_INVENTORY_SITUATION`
    # denote the same table — the id and the physical name differ by more than case.
    source_table: str = ""
    target_table: str = ""

    # The authored SQL predicate, verbatim. AUTHORITATIVE whenever `conditions` is
    # empty, which is the case for every predicate that is not a single simple
    # comparison (multi-key `AND`, `IN (...)`, `BETWEEN`, ...).
    join_predicate: str = ""

    # Closed set: safe | requires_dedup | unsafe. Authored on the forward edge,
    # derived from the reverse cardinality on the auto-generated reverse edge.
    aggregation_safety: str = "safe"

    # The curator's business meaning + the grain/dedup caveat that the standard
    # (SILVER §7.4 / GOLD §6.5) instructs them to write here.
    description: str | None = None

    semantic_label: str | None = None
    cross_module: bool = False
