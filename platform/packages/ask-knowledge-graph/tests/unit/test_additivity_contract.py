"""The two-axis aggregation contract (REQ_ADDITIVITY_CONTRACT.md).

``aggregation_behavior`` answers WHICH function; ``additivity`` answers over
WHICH grain dimensions applying it is valid. Before the split, one key carried
both facts and two of its values meant two different things each:

  * ``none`` meant "not a number" on an identifier and "is a number, do NOT sum
    it" on a measure. The overload was not academic — tooling that read it as a
    no-op default silently dropped it, turning running totals into summable
    measures (see ``test_structural_replace_preserves_explicit_none_aggregation``
    in ask-admin-api).
  * ``MAX`` meant "the maximum is the answer" and "every value in this group is
    identical, take any one".

The gap the split exposes: most measures tagged ``none`` are not non-additive
but SEMI-additive — summable across ``plant_id``, not across ``future_date``.
"""

import pytest
from pydantic import ValidationError

from ask_knowledge_graph.domain.nodes import Grain, SilverField, _additivity_scope_problems


def _field(**over):
    """A minimal valid measure."""
    raw = {
        "name": "on_hand",
        "field_role": "measure",
        "type": "DECIMAL(15,2)",
        "description": "Stock on hand.",
    }
    raw.update(over)
    return raw


# ── Axis 1: the function enum ───────────────────────────────────────────────


@pytest.mark.parametrize("value", ["SUM", "AVG", "MIN", "MAX", "COUNT", "COUNT_DISTINCT", "none"])
def test_aggregation_behavior_accepts_the_canonical_enum(value):
    """The enum is the union of the three vocabularies that had forked: the
    public spec contributed COUNT_DISTINCT, the internal standard contributed
    COUNT. Both are legitimate functions once the key carries no semantics, so
    the fork is closed by union rather than by arbitration."""
    extra = {"additivity": "non_additive"} if value == "none" else {}
    assert SilverField(**_field(aggregation_behavior=value, **extra)).aggregation_behavior == value


def test_aggregation_behavior_rejects_anything_outside_the_enum():
    """It used to be ``str | None``, so ``"banana"`` validated cleanly."""
    with pytest.raises(ValidationError, match="COUNT_DISTINCT"):
        SilverField(**_field(aggregation_behavior="banana"))


def test_absent_aggregation_behavior_is_still_allowed():
    """Absent means "not curated" — the SQL prompt assumes additive and sums.
    The SAP parser emits exactly this for every uncurated measure."""
    f = SilverField(**_field())
    assert f.aggregation_behavior is None
    assert f.additivity is None


# ── Axis 2: the legacy-encoding shim ────────────────────────────────────────


def test_legacy_measure_with_explicit_none_reads_as_non_additive():
    """THE migration-safety hinge (§4.5).

    Under the new contract an absent ``additivity`` means ADDITIVE. Reading a
    pre-split YAML literally would therefore flip every running total into a
    summable measure — the exact double-count the contract exists to prevent.
    """
    f = SilverField(
        **_field(
            name="cumulative_sales_order",
            description="Cumulative outbound demand — running total.",
            aggregation_behavior="none",
        )
    )
    assert f.additivity == "non_additive"


def test_shim_is_enforced_at_the_model_boundary_not_in_one_writer():
    """Coverage must not depend on which code path built the field.

    A path-dependent assumption about what ``none`` means is what produced the
    original defect, so the guarantee lives on the model: SAP parser, YAML
    ingestion, admin save and direct construction all read it the same way.
    """
    from_dict = SilverField.model_validate(_field(name="future_stock", aggregation_behavior="none"))
    from_kwargs = SilverField(**_field(name="future_stock", aggregation_behavior="none"))
    assert from_dict.additivity == from_kwargs.additivity == "non_additive"


def test_shim_does_not_touch_non_measures():
    """``none`` on an identifier is a genuine no-op — there was never anything
    to aggregate. Only the measure reading was overloaded."""
    f = SilverField(
        name="material_id",
        field_role="identifier",
        type="STRING(18)",
        description="Material number.",
        aggregation_behavior="none",
    )
    assert f.additivity is None


def test_shim_never_writes_additive_explicitly():
    """Absence already means additive; stamping it on every measure would churn
    every YAML in the catalog for no information gain."""
    assert SilverField(**_field(aggregation_behavior="SUM")).additivity is None


# ── Axis 2: the field-local validators ──────────────────────────────────────


def test_additivity_is_rejected_on_a_non_measure():
    """Additivity is a property of measures. Asking "additive over what?" of a
    status flag has no answer — which is how the contract exposes a measure
    that was mis-typed in the first place."""
    with pytest.raises(ValidationError, match="only to field_role 'measure'"):
        SilverField(
            name="order_status",
            field_role="status_flag",
            type="TEXT",
            description="OPEN/CLOSE.",
            additivity="additive",
        )


def test_semi_additive_requires_the_dimensions_to_collapse():
    """``semi_additive`` without ``non_additive_over`` is unactionable: the
    agent knows a collapse is needed but not along which axis."""
    with pytest.raises(ValidationError, match="requires a non-empty `non_additive_over`"):
        SilverField(**_field(additivity="semi_additive"))


def test_non_additive_over_requires_semi_additive():
    with pytest.raises(ValidationError, match="only meaningful with"):
        SilverField(**_field(additivity="additive", non_additive_over=["future_date"]))


def test_non_additive_requires_aggregation_behavior_none():
    """A genuinely non-additive measure (a ratio, a score) has no meaningful
    function, so declaring one contradicts the additivity."""
    with pytest.raises(ValidationError, match="requires `aggregation_behavior: none`"):
        SilverField(**_field(additivity="non_additive", aggregation_behavior="SUM"))


def test_validators_accumulate_into_a_single_error():
    """The D3 precedent from the Bronze package: report every problem at once
    instead of making the author fix them one round-trip at a time."""
    with pytest.raises(ValidationError) as exc:
        SilverField(
            name="bad",
            field_role="dimension",
            type="TEXT",
            description="x",
            additivity="semi_additive",
        )
    msg = str(exc.value)
    assert "only to field_role 'measure'" in msg
    assert "requires a non-empty `non_additive_over`" in msg


# ── Axis 2: the node-level scope validators ─────────────────────────────────


def _inventory_fields(measure_over):
    """F1-shaped: a projection grained by plant + material + future_date."""
    return [
        SilverField(name="future_date", field_role="timestamp", type="DATE", description="d"),
        SilverField(name="plant_id", field_role="dimension", type="STRING(4)", description="d"),
        SilverField(
            **_field(
                aggregation_behavior="SUM",
                additivity="semi_additive",
                non_additive_over=measure_over,
            )
        ),
    ]


_GRAIN = Grain(entity_grain=["plant_id", "future_date"], business_grain="daily_plant_material")


def test_semi_additive_over_a_timestamp_grain_dimension_is_valid():
    """The shipped shape: on_hand repeats across future_date, so collapse the
    date first and only then sum across plants."""
    assert _additivity_scope_problems(_inventory_fields(["future_date"]), _GRAIN) == []


def test_non_additive_over_must_name_a_grain_dimension():
    """Collapsing a dimension that is not part of the grain is meaningless —
    it does not multiply rows, so there is nothing to collapse."""
    problems = _additivity_scope_problems(_inventory_fields(["not_in_grain"]), _GRAIN)
    assert len(problems) == 1
    assert "not in grain.entity_grain" in problems[0]


def test_non_temporal_dimension_is_accepted_v2():
    """v2 (2026-08-03) — a NON-temporal grain dimension is legal.

    v1 rejected these on the reasoning that "collapse to the latest one" is
    undefined for, say, a storage location. That conflated the two reasons a value
    needs collapsing: a value that ACCUMULATES along a dimension does need the
    latest row (so the dimension must be ordered, i.e. temporal), but a value that
    merely REPEATS because a join fanned the rows out carries the SAME value on
    every row of the group, so collapsing to ANY one row is exact and no ordering
    is needed.

    The second case is the ordinary shape of a denormalised Silver — a header
    amount restated on every item, a stock level on every movement line — and v1
    could not express it at all, which pushed the instruction into field
    descriptions where the SQL generator had latitude and measurably got it wrong
    three times running (P7 E2E). The prompt now branches on WHY the value repeats
    instead of assuming time. See `EntityDeriver.fanout_dims_by_table`.
    """
    assert _additivity_scope_problems(_inventory_fields(["plant_id"]), _GRAIN) == []


def test_membership_and_resolvability_are_still_enforced():
    """Widening the ROLE rule must not weaken the two structural ones: the
    dimension must be in the grain, and it must resolve to a selectable column."""
    outside = _additivity_scope_problems(_inventory_fields(["not_in_grain"]), _GRAIN)
    assert len(outside) == 1
    assert "not in grain.entity_grain" in outside[0]


def test_grain_dimension_that_resolves_to_no_field_is_reported():
    """Surfaces the known Silver defect where entity_grain carries raw SAP codes
    that match no selectable column, so the grain contract cannot execute."""
    grain = Grain(entity_grain=["plant_id", "VBELN"], business_grain="x")
    fields = _inventory_fields(["VBELN"])
    problems = _additivity_scope_problems(fields, grain)
    assert len(problems) == 1
    assert "matches no field" in problems[0]
