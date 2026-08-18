# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Contract test: `key_fields_summary` covers the whole `field_role` vocabulary.

The summary is the anti-"Lost-in-the-Middle" block (ASK Spec 6.3) written onto
every Silver/Gold entity document. It used to bucket on an allowlist of two roles
(``identifier``, ``dimension``), so three of the six roles ratified on
``SilverField`` — ``timestamp``, ``status_flag``, ``attribute`` — rendered as
nothing at all. That is the same flattening the alignment series already ruled a
defect one branch away, in the Field Registry ("the previous normalisation
collapsed identifier/attribute/status_flag into `dimension`").

It was measurably lossy, not merely latent: the from-zero P7 ingest of
`sales_order` publishes 24 ``timestamp`` fields, every one of which the old
allowlist dropped. Found during the P7 E2E run (2026-08-03); it is also a hard
prerequisite for the deferred ~404-field `status_flag` retag campaign, which
would otherwise have silently stripped all 404 from this block.

The branch is now inverted — everything that is not a ``measure`` is a key field
— so it tracks the role vocabulary automatically instead of needing an edit per
new role.
"""

from __future__ import annotations

from ask_knowledge_graph.infrastructure.opensearch_repository import OpenSearchAskRepository

# Every role ratified on `SilverField.field_role`, plus a roleless field.
_ALL_ROLES = ("identifier", "dimension", "timestamp", "status_flag", "attribute", "measure")


def _repo() -> OpenSearchAskRepository:
    # Bypass __init__ (it reads config/settings.json + builds a real client);
    # _generate_key_fields_summary touches no instance state.
    return OpenSearchAskRepository.__new__(OpenSearchAskRepository)


def _entity(fields: list[dict]) -> dict:
    return {
        "layer": "silver",
        "name": "sales_order",
        "composed_of": ["bronze_s4h_vbak_order_header"],
        "fields": fields,
    }


def test_every_non_measure_role_reaches_key_fields() -> None:
    """No ratified role may be silently dropped from the summary."""
    summary = _repo()._generate_key_fields_summary(
        _entity(
            [{"name": f"f_{r}", "field_role": r, "description": f"desc {r}"} for r in _ALL_ROLES]
        )
    )
    for role in _ALL_ROLES:
        assert f"f_{role}" in summary, f"role {role!r} vanished from key_fields_summary"


def test_measure_is_bucketed_as_a_metric_not_a_key_field() -> None:
    """The inversion must not swallow the measure branch."""
    summary = _repo()._generate_key_fields_summary(
        _entity(
            [
                {"name": "net_value", "field_role": "measure", "source": "VBAK.NETWR"},
                {"name": "vbeln_vbak", "field_role": "identifier", "description": "Sales doc"},
            ]
        )
    )
    # The measure renders through the aggregation-aware metric branch...
    assert "net_value" in summary
    assert "SUM" in summary
    # ...and the identifier through the key-field branch, which never prints SUM.
    key_block = summary.split("net_value")[0]
    assert "vbeln_vbak" in key_block


def test_status_flag_is_a_key_field_not_a_metric() -> None:
    """A status is a legitimate grouping key, never something to aggregate.

    Mirrors the SQL prompt's own rule ("`status_flag` -> GROUP BY and WHERE
    too"), so the retrieval summary and the generation prompt agree.
    """
    summary = _repo()._generate_key_fields_summary(
        _entity(
            [
                {
                    "name": "gbstk_vbak",
                    "field_role": "status_flag",
                    "description": "A = open, B = partial, C = complete",
                }
            ]
        )
    )
    assert "gbstk_vbak: A = open, B = partial, C = complete" in summary
    assert "SUM" not in summary


def test_timestamp_fields_are_not_dropped() -> None:
    """The regression that made this test necessary: 24 live fields, all lost."""
    summary = _repo()._generate_key_fields_summary(
        _entity([{"name": "erdat_vbak", "field_role": "timestamp", "description": "Created on"}])
    )
    assert "erdat_vbak" in summary
