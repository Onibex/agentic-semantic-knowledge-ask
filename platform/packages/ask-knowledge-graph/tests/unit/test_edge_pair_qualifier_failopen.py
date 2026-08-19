# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Contract test: `target_table` must not FAIL OPEN when the qualifier contract is broken.

`_build_edge_pair` derives the target side's physical table by *elimination* from the
predicate's own qualifiers — deliberately, because the target entity may not be indexed
yet when the edge is written, and SILVER §7.3.1 / GOLD §6.3.1 guarantee the predicate
carries it. The function checks that contract and logs a warning when it is violated.

The bug: it then derived `target_table` from the assumption the check had just
disproved. When BOTH qualifiers are entity ids — an AI-suggested relationship authored
while `db_table_name` still held its id default, which is exactly what happened during
the P7 E2E run on 2026-08-03 — neither qualifier matches `source_table`, so `next()`
returned the FIRST one: the source's own id. The consumer
(`freeform_generator._format_edges_hint._qualified`) then rendered
``target_entity (table: <SOURCE's id>)`` into the block the SQL prompt treats as
authoritative — actively wrong rather than merely absent.

Now the derivation is gated on the contract holding, so a violating edge yields `""`
and the consumer degrades to the bare entity id. Absent beats wrong.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

from ask_knowledge_graph.infrastructure.opensearch_repository import _build_edge_pair

_SOURCE = SimpleNamespace(id="silver_s4h_sd_sales_order", db_table_name="SILVER_SD_SALES_ORDER")

# Both sides qualified with entity ids instead of physical tables (the P7 defect).
_VIOLATING = (
    "silver_s4h_sd_sales_order.matnr_vbap = silver_s4h_mm_inv_mov_stock.matnr_marc"
    " AND silver_s4h_sd_sales_order.werks_vbap = silver_s4h_mm_inv_mov_stock.werks_marc"
)
# The same edge authored to contract.
_COMPLIANT = (
    "SILVER_SD_SALES_ORDER.matnr_vbap = SILVER_MM_INVENTORY_MOVEMENT.matnr_mseg"
    " AND SILVER_SD_SALES_ORDER.werks_vbap = SILVER_MM_INVENTORY_MOVEMENT.werks_mseg"
)


def _rel(predicate: str) -> SimpleNamespace:
    return SimpleNamespace(
        join_condition=predicate,
        target_entity="silver_s4h_mm_inv_mov_stock",
        relationship_type="many_to_many",
        traversal_cost=3.0,
        semantic_label="demands_stock_from",
        aggregation_safety="requires_dedup",
        description=None,
        cross_module=True,
    )


def _forward(predicate: str) -> dict:
    return _build_edge_pair(_SOURCE, _rel(predicate))[0][1]


def test_violating_predicate_yields_empty_target_table_not_the_source_id() -> None:
    """The regression: `target_table` must never echo the SOURCE's identifier."""
    fwd = _forward(_VIOLATING)
    assert fwd["target_table"] == ""
    # The precise old failure, asserted so it cannot come back by another route.
    assert fwd["target_table"] != _SOURCE.id
    assert fwd["target_table"].upper() != _SOURCE.db_table_name.upper()


def test_compliant_predicate_still_resolves_the_target_table() -> None:
    """The gate must not cost anything on a correctly authored edge."""
    fwd = _forward(_COMPLIANT)
    assert fwd["source_table"] == "SILVER_SD_SALES_ORDER"
    assert fwd["target_table"] == "SILVER_MM_INVENTORY_MOVEMENT"


def test_violation_is_logged_but_never_fatal() -> None:
    """A bad qualifier must not stop an ingestion — only warn."""
    logger_name = "ask_knowledge_graph.infrastructure.opensearch_repository"
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger(logger_name)
    handler = _Capture()
    logger.addHandler(handler)
    try:
        pairs = _build_edge_pair(_SOURCE, _rel(_VIOLATING))
    finally:
        logger.removeHandler(handler)

    assert len(pairs) == 2  # forward + auto-generated reverse, ingestion continued
    assert any("does not qualify its own side" in r.getMessage() for r in records)


def test_reverse_edge_also_carries_no_fabricated_table() -> None:
    """The reverse edge swaps the sides, so it must not inherit the bad value either."""
    reverse = _build_edge_pair(_SOURCE, _rel(_VIOLATING))[1][1]
    for key in ("source_table", "target_table"):
        assert reverse[key] != _SOURCE.id
