"""Unit tests for YAMLFileService and GitService."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ask_admin_api.application.yaml_file_service import YAMLFileService, YAMLNotFoundError
from ask_admin_api.models.viz_models import VizLayer, VizYAMLUpdateRequest

# ── Fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_BRONZE_YAML = textwrap.dedent("""\
    id: bronze_s4h_vbak_order_header
    layer: bronze
    source_system: s4h
    name: VBAK
    alias: ORDER_HEADER
    description: SAP Sales Order Header
    primary_key: [VBELN]
    fields:
      VBELN:
        type: C10
        alias: sales_doc
        key_field: true
        description: Sales document number
      NETWR:
        type: P15
        alias: net_value
        key_field: false
        description: Net order value
""")

SAMPLE_SILVER_YAML = textwrap.dedent("""\
    id: silver_s4h_sd_sales_order
    layer: silver
    source_system: s4h
    module: sd
    name: sales_order
    classification: T
    description: Sales order Silver entity
    entity_role: fact
    composed_of: [VBAK, VBAP]
    join_graph:
      - left_table: VBAK
        right_table: VBAP
        join_type: INNER
        condition: "VBAK.VBELN = VBAP.VBELN"
        sequence: 1
    fields:
      - name: net_value
        source: VBAK.NETWR
        field_role: measure
        type: P15
        description: Net order value
        aggregation_behavior: SUM
      - name: sales_doc
        source: VBAK.VBELN
        field_role: identifier
        type: C10
        description: Sales document ID
""")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    bronze_dir = tmp_path / "workspace" / "ask" / "s4h" / "bronze"
    silver_dir = tmp_path / "workspace" / "ask" / "s4h" / "silver" / "sd"
    bronze_dir.mkdir(parents=True)
    silver_dir.mkdir(parents=True)
    (bronze_dir / "vbak.yaml").write_text(SAMPLE_BRONZE_YAML, encoding="utf-8")
    (silver_dir / "sales_order.yaml").write_text(SAMPLE_SILVER_YAML, encoding="utf-8")
    return tmp_path


@pytest.fixture
def svc(workspace: Path) -> YAMLFileService:
    return YAMLFileService(
        workspace_path=str(workspace / "workspace" / "ask"),
        repo_root=str(workspace),
    )


# ── list_yamls ────────────────────────────────────────────────────────────────


def test_list_yamls_returns_all(svc):
    nodes = svc.list_yamls()
    assert len(nodes) == 2
    ids = {n.id for n in nodes}
    assert "bronze_s4h_vbak_order_header" in ids
    assert "silver_s4h_sd_sales_order" in ids


def test_list_yamls_filter_by_layer(svc):
    silvers = svc.list_yamls(layer=VizLayer.silver)
    assert len(silvers) == 1
    assert silvers[0].layer == VizLayer.silver

    bronzes = svc.list_yamls(layer=VizLayer.bronze)
    assert len(bronzes) == 1
    assert bronzes[0].layer == VizLayer.bronze


# ── get_yaml ──────────────────────────────────────────────────────────────────


def test_get_yaml_bronze_fields(svc):
    node = svc.get_yaml("bronze_s4h_vbak_order_header")
    assert node.layer == VizLayer.bronze
    assert len(node.fields) == 2
    vbeln = next(f for f in node.fields if f.name == "VBELN")
    assert vbeln.alias == "sales_doc"
    assert vbeln.key_field is True


def test_get_yaml_silver_fields(svc):
    node = svc.get_yaml("silver_s4h_sd_sales_order")
    assert node.layer == VizLayer.silver
    assert node.module == "sd"
    assert len(node.fields) == 2
    net_val = next(f for f in node.fields if f.name == "net_value")
    assert net_val.field_role == "measure"
    assert net_val.aggregation_behavior == "SUM"


# ── get_yamls_by_ids (single-pass scoped fetch for the canvas) ──────────────────


def test_get_yamls_by_ids_returns_full_nodes(svc):
    """One pass returns the full nodes (with fields + edges) for the requested ids."""
    nodes = svc.get_yamls_by_ids({"bronze_s4h_vbak_order_header", "silver_s4h_sd_sales_order"})
    assert {n.id for n in nodes} == {"bronze_s4h_vbak_order_header", "silver_s4h_sd_sales_order"}
    silver = next(n for n in nodes if n.id == "silver_s4h_sd_sales_order")
    assert len(silver.fields) == 2  # full node, not a render-light projection
    assert silver.composed_of == ["VBAK", "VBAP"]  # edges available for the graph


def test_get_yamls_by_ids_ignores_unknown_and_empty(svc):
    nodes = svc.get_yamls_by_ids({"silver_s4h_sd_sales_order", "does_not_exist"})
    assert {n.id for n in nodes} == {"silver_s4h_sd_sales_order"}
    assert svc.get_yamls_by_ids(set()) == []


def test_get_yaml_silver_join_graph(svc):
    node = svc.get_yaml("silver_s4h_sd_sales_order")
    assert len(node.join_graph) == 1
    assert node.join_graph[0].left_table == "VBAK"
    assert node.join_graph[0].join_type == "INNER"


def test_get_yaml_not_found(svc):
    with pytest.raises(YAMLNotFoundError):
        svc.get_yaml("nonexistent_id")


def test_loads_gold_with_yml_extension(svc, workspace):
    """Gold data products use the .yml extension; they must be visible too."""
    gold_dir = workspace / "workspace" / "ask" / "s4h" / "gold"
    gold_dir.mkdir(parents=True)
    (gold_dir / "sales_performance.yml").write_text(
        textwrap.dedent("""\
            id: gold_s4h_sd_sales_performance
            layer: gold
            module: [SD]
            name: sales_performance
            relationships:
              - target_entity: silver_s4h_sd_sales_order
                relationship_type: one_to_many
                semantic_label: aggregates_orders
        """),
        encoding="utf-8",
    )

    ids = {n.id for n in svc.list_yamls()}
    assert "gold_s4h_sd_sales_performance" in ids

    node = svc.get_yaml("gold_s4h_sd_sales_performance")
    assert node.layer == VizLayer.gold
    assert node.relationships[0].target_entity == "silver_s4h_sd_sales_order"


# ── update_yaml ───────────────────────────────────────────────────────────────


def test_update_yaml_bronze_alias(svc, workspace):
    from ask_admin_api.models.viz_models import VizFieldUpdate

    mock_git = MagicMock()

    req = VizYAMLUpdateRequest(
        author_name="Test User",
        author_email="test@onibex.com",
        fields=[VizFieldUpdate(name="NETWR", alias="net_revenue")],
    )

    # Use the real round-trip serializer — tests would otherwise need to
    # replicate ruamel's CommentedMap handling.
    with patch("ask_admin_api.application.yaml_file_service.AskYamlSerializer") as MockSerializer:
        from ask_knowledge_graph.infrastructure.yaml_serializer import (
            AskYamlSerializer as RealSerializer,
        )

        MockSerializer.return_value.to_yaml.side_effect = lambda d: RealSerializer().to_yaml(d)

        updated = svc.update_yaml("bronze_s4h_vbak_order_header", req, git_service=mock_git)

    netwr = next(f for f in updated.fields if f.name == "NETWR")
    assert netwr.alias == "net_revenue"
    mock_git.commit.assert_called_once()
    call_args = mock_git.commit.call_args
    assert "test@onibex.com" in call_args.args or "test@onibex.com" in str(call_args)


def test_update_yaml_silver_field_role(svc, workspace):
    from ask_admin_api.models.viz_models import VizFieldUpdate

    mock_git = MagicMock()

    # Patch the measure (net_value), NOT the lone identifier — a Silver must keep
    # at least one identifier field (it defines the grain), so flipping sales_doc
    # would now correctly raise.
    req = VizYAMLUpdateRequest(
        author_name="Test User",
        author_email="test@onibex.com",
        fields=[VizFieldUpdate(name="net_value", field_role="attribute")],
    )

    # Use the real round-trip serializer — tests would otherwise need to
    # replicate ruamel's CommentedMap handling.
    with patch("ask_admin_api.application.yaml_file_service.AskYamlSerializer") as MockSerializer:
        from ask_knowledge_graph.infrastructure.yaml_serializer import (
            AskYamlSerializer as RealSerializer,
        )

        MockSerializer.return_value.to_yaml.side_effect = lambda d: RealSerializer().to_yaml(d)

        updated = svc.update_yaml("silver_s4h_sd_sales_order", req, git_service=mock_git)

    net_value = next(f for f in updated.fields if f.name == "net_value")
    assert net_value.field_role == "attribute"


def test_update_yaml_top_level_description(svc, workspace):
    mock_git = MagicMock()

    req = VizYAMLUpdateRequest(
        author_name="Test User",
        author_email="test@onibex.com",
        description="Updated description for test",
    )

    # Use the real round-trip serializer — tests would otherwise need to
    # replicate ruamel's CommentedMap handling.
    with patch("ask_admin_api.application.yaml_file_service.AskYamlSerializer") as MockSerializer:
        from ask_knowledge_graph.infrastructure.yaml_serializer import (
            AskYamlSerializer as RealSerializer,
        )

        MockSerializer.return_value.to_yaml.side_effect = lambda d: RealSerializer().to_yaml(d)

        updated = svc.update_yaml("bronze_s4h_vbak_order_header", req, git_service=mock_git)

    assert updated.description == "Updated description for test"


def test_update_yaml_structural_fields_silver(svc, workspace):
    """db_table_name / classification are editable (standards §4.1/§4.2) and
    persist. entity_role is NOT client-set: it is auto-derived from classification
    (§5.1) and recomputed on save — a bogus entity_role in the request is ignored."""
    mock_git = MagicMock()

    req = VizYAMLUpdateRequest(
        author_name="Test User",
        author_email="test@onibex.com",
        db_table_name="GOLD_SD_SALES_PERFORMANCE",
        entity_role="fact",  # bogus — must be overridden by the derivation
        classification="M",  # M → dimension (§5.1)
    )

    with patch("ask_admin_api.application.yaml_file_service.AskYamlSerializer") as MockSerializer:
        from ask_knowledge_graph.infrastructure.yaml_serializer import (
            AskYamlSerializer as RealSerializer,
        )

        MockSerializer.return_value.to_yaml.side_effect = lambda d: RealSerializer().to_yaml(d)

        svc.update_yaml("silver_s4h_sd_sales_order", req, git_service=mock_git)

    raw = svc.load_raw_by_id("silver_s4h_sd_sales_order")
    assert raw["db_table_name"] == "GOLD_SD_SALES_PERFORMANCE"
    assert raw["entity_role"] == "dimension"  # derived from classification=M, not the sent "fact"
    assert raw["classification"] == "M"
    # grain.entity_grain is recomputed from the identifier field(s).
    assert raw["grain"]["entity_grain"] == ["sales_doc"]


def test_update_yaml_silver_grain_recomputed_from_identifiers(svc, workspace):
    """grain.entity_grain is derived: the names of the identifier-role fields, in
    order. A structural replace that marks two identifiers yields a 2-key grain."""
    from ask_admin_api.models.viz_models import VizFieldFull

    mock_git = MagicMock()
    req = VizYAMLUpdateRequest(
        author_email="test@onibex.com",
        fields_full=[
            VizFieldFull(name="order_id", source="VBAK.VBELN", field_role="identifier", type="C10"),
            VizFieldFull(name="item_id", source="VBAP.POSNR", field_role="identifier", type="N6"),
            VizFieldFull(name="amount", source="VBAK.NETWR", field_role="measure", type="P15"),
        ],
    )
    ctx = _real_serializer_patch()
    try:
        svc.update_yaml("silver_s4h_sd_sales_order", req, git_service=mock_git)
    finally:
        ctx.__exit__(None, None, None)

    raw = svc.load_raw_by_id("silver_s4h_sd_sales_order")
    assert raw["grain"]["entity_grain"] == ["order_id", "item_id"]  # identifier fields, in order
    assert raw["entity_role"] == "fact"  # T (fixture) + has a measure → fact


def test_update_yaml_silver_requires_identifier(svc, workspace):
    """Flipping the lone identifier to a non-key role leaves the Silver with no
    grain → must raise (the router maps it to 422), not write an invalid YAML."""
    from ask_admin_api.models.viz_models import VizFieldUpdate

    mock_git = MagicMock()
    req = VizYAMLUpdateRequest(
        author_email="test@onibex.com",
        fields=[VizFieldUpdate(name="sales_doc", field_role="dimension")],
    )
    ctx = _real_serializer_patch()
    try:
        with pytest.raises(ValueError, match="identifier"):
            svc.update_yaml("silver_s4h_sd_sales_order", req, git_service=mock_git)
    finally:
        ctx.__exit__(None, None, None)


def test_update_yaml_entity_role_not_written_on_bronze(svc, workspace):
    """entity_role is a Silver/Gold body field (§5.1) — there is no entity_role
    on Bronze. db_table_name / classification still apply (common header)."""
    mock_git = MagicMock()

    req = VizYAMLUpdateRequest(
        author_name="Test User",
        author_email="test@onibex.com",
        entity_role="fact",  # must be ignored on Bronze
        db_table_name="VBAK",  # header field — must persist
        classification="T",  # header field — must persist
    )

    with patch("ask_admin_api.application.yaml_file_service.AskYamlSerializer") as MockSerializer:
        from ask_knowledge_graph.infrastructure.yaml_serializer import (
            AskYamlSerializer as RealSerializer,
        )

        MockSerializer.return_value.to_yaml.side_effect = lambda d: RealSerializer().to_yaml(d)

        svc.update_yaml("bronze_s4h_vbak_order_header", req, git_service=mock_git)

    raw = svc.load_raw_by_id("bronze_s4h_vbak_order_header")
    assert "entity_role" not in raw  # guarded — never written onto Bronze
    assert raw["db_table_name"] == "VBAK"
    assert raw["classification"] == "T"


def test_update_yaml_preserves_untouched_fields(svc, workspace):
    """Partial update must not erase fields that were not included in the request."""
    mock_git = MagicMock()

    req = VizYAMLUpdateRequest(
        author_name="Test User",
        author_email="test@onibex.com",
        description="New description only",
        # no fields update → VBELN alias must remain 'sales_doc'
    )

    # Use the real round-trip serializer — tests would otherwise need to
    # replicate ruamel's CommentedMap handling.
    with patch("ask_admin_api.application.yaml_file_service.AskYamlSerializer") as MockSerializer:
        from ask_knowledge_graph.infrastructure.yaml_serializer import (
            AskYamlSerializer as RealSerializer,
        )

        MockSerializer.return_value.to_yaml.side_effect = lambda d: RealSerializer().to_yaml(d)

        updated = svc.update_yaml("bronze_s4h_vbak_order_header", req, git_service=mock_git)

    vbeln = next(f for f in updated.fields if f.name == "VBELN")
    assert vbeln.alias == "sales_doc"  # unchanged


# ── update_yaml: full structural replace (edit-in-full) ───────────────────────


def _real_serializer_patch():
    from unittest.mock import patch as _patch

    from ask_knowledge_graph.infrastructure.yaml_serializer import (
        AskYamlSerializer as RealSerializer,
    )

    ctx = _patch("ask_admin_api.application.yaml_file_service.AskYamlSerializer")
    mock = ctx.__enter__()
    mock.return_value.to_yaml.side_effect = lambda d: RealSerializer().to_yaml(d)
    return ctx


def test_update_yaml_structural_replace_silver_add_and_remove_field(svc, workspace):
    from ask_admin_api.models.viz_models import VizFieldFull

    mock_git = MagicMock()
    # Seed silver has net_value + sales_doc. Replace wholesale: drop net_value,
    # keep sales_doc, add a brand-new measure (role + canonical type derived).
    req = VizYAMLUpdateRequest(
        author_email="test@onibex.com",
        fields_full=[
            VizFieldFull(
                name="sales_doc",
                source="VBAK.VBELN",
                field_role="identifier",
                type="C10",
                description="doc",
            ),
            VizFieldFull(name="brand_new", source="VBAK.NEW", type="P15", description="added"),
        ],
    )
    ctx = _real_serializer_patch()
    try:
        updated = svc.update_yaml("silver_s4h_sd_sales_order", req, git_service=mock_git)
    finally:
        ctx.__exit__(None, None, None)

    names = {f.name for f in updated.fields}
    assert names == {"sales_doc", "brand_new"}  # wholesale replace removed net_value
    new = next(f for f in updated.fields if f.name == "brand_new")
    assert new.type == "DECIMAL(15)"  # canonicalized by the deriver
    assert new.field_role == "measure"  # derived from DECIMAL


def test_update_yaml_structural_replace_bronze_recomputes_primary_key(svc, workspace):
    from ask_admin_api.models.viz_models import VizFieldFull
    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    mock_git = MagicMock()
    req = VizYAMLUpdateRequest(
        author_email="test@onibex.com",
        fields_full=[
            VizFieldFull(
                name="VBELN", type="C10", alias="sales_doc", key_field=False, description="doc"
            ),
            VizFieldFull(name="POSNR", type="N6", alias="item", key_field=True, description="item"),
        ],
    )
    ctx = _real_serializer_patch()
    try:
        svc.update_yaml("bronze_s4h_vbak_order_header", req, git_service=mock_git)
    finally:
        ctx.__exit__(None, None, None)

    raw = load_yaml_text(
        (workspace / "workspace" / "ask" / "s4h" / "bronze" / "vbak.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert raw["primary_key"] == ["POSNR"]  # recomputed from key_field flags
    assert raw["fields"]["VBELN"]["type"] == "STRING(10)"  # canonicalized
    assert raw["fields"]["POSNR"]["type"] == "STRING(6)"


def test_structural_replace_records_field_enrichment_for_conflict_protection(svc, workspace):
    """Regression (aufpl_afko bug): an edit-in-full (fields_full) that changes a
    field's enrichable prop MUST record provenance in the enrichments sidecar.
    The SPA routes EVERY field edit through fields_full, so without this the SAP
    merge never sees the field as enriched and silently auto-applies over the
    curated value instead of raising a conflict."""
    from ask_admin_api.models.viz_models import VizFieldFull

    mock_git = MagicMock()
    # Re-send the whole field list (what the SPA does for ANY field edit),
    # changing ONLY net_value's description — a pure enrichment. sales_doc is
    # re-sent verbatim, so it must NOT be flagged as enriched.
    req = VizYAMLUpdateRequest(
        author_email="test@onibex.com",
        fields_full=[
            VizFieldFull(
                name="net_value",
                source="VBAK.NETWR",
                field_role="measure",
                type="P15",
                description="Curated net revenue",  # changed from "Net order value"
                aggregation_behavior="SUM",
            ),
            VizFieldFull(
                name="sales_doc",
                source="VBAK.VBELN",
                field_role="identifier",
                type="C10",
                description="Sales document ID",  # unchanged
            ),
        ],
    )
    ctx = _real_serializer_patch()
    try:
        svc.update_yaml("silver_s4h_sd_sales_order", req, git_service=mock_git)
    finally:
        ctx.__exit__(None, None, None)

    _entity_enr, field_enr = svc._enrichments_store.read("silver_s4h_sd_sales_order")
    # net_value's description changed → recorded as enriched (conflict-protected).
    assert "description" in field_enr.get("net_value", [])
    # sales_doc was re-sent unchanged → not spuriously marked enriched.
    assert "sales_doc" not in field_enr


def test_structural_replace_preserves_explicit_none_aggregation(svc, workspace):
    """An explicit ``aggregation_behavior: none`` on a measure MUST survive an
    edit-in-full. On a measure it is not a no-op default — it is the NON-ADDITIVE
    signal (already-cumulative total / projected balance) that SQL-generation
    rule 8 reads as "never SUM this". Dropping it leaves the key ABSENT, which
    rule 8 reads as "assume additive", silently double-counting running totals.

    The SPA routes EVERY field edit through ``fields_full``, so a plain
    description tweak on an inventory Gold used to be enough to trigger it.
    """
    from ask_admin_api.models.viz_models import VizFieldFull

    mock_git = MagicMock()
    req = VizYAMLUpdateRequest(
        author_email="test@onibex.com",
        fields_full=[
            VizFieldFull(
                name="cumulative_sales_order",
                source="VBAK.NETWR",
                field_role="measure",
                type="P15",
                description="Cumulative outbound demand — running total, do NOT SUM.",
                aggregation_behavior="none",
            ),
            VizFieldFull(
                name="sales_doc",
                source="VBAK.VBELN",
                field_role="identifier",
                type="C10",
                description="Sales document ID",
                aggregation_behavior="none",
            ),
        ],
    )
    ctx = _real_serializer_patch()
    try:
        updated = svc.update_yaml("silver_s4h_sd_sales_order", req, git_service=mock_git)
    finally:
        ctx.__exit__(None, None, None)

    cumulative = next(f for f in updated.fields if f.name == "cumulative_sales_order")
    assert cumulative.aggregation_behavior == "none", (
        "explicit none dropped on a measure — rule 8 will now SUM a running total"
    )
    # A caller-omitted value stays omitted; only the explicit string is preserved.
    identifier = next(f for f in updated.fields if f.name == "sales_doc")
    assert identifier.aggregation_behavior == "none"


def test_structural_replace_round_trips_the_additivity_contract(svc, workspace):
    """Axis 2 (REQ_ADDITIVITY_CONTRACT) survives an edit-in-full unchanged.

    Both halves matter: a curator-set ``semi_additive`` + ``non_additive_over``
    must persist verbatim, and the legacy ``measure`` + ``none`` shape must come
    back as ``non_additive`` rather than as the additive default.
    """
    from ask_admin_api.models.viz_models import VizFieldFull, VizGrainSpec

    mock_git = MagicMock()
    req = VizYAMLUpdateRequest(
        author_email="test@onibex.com",
        grain=VizGrainSpec(
            entity_grain=["sales_doc", "booked_on"], business_grain="daily_sales_doc"
        ),
        fields_full=[
            VizFieldFull(
                name="sales_doc",
                source="VBAK.VBELN",
                field_role="identifier",
                type="C10",
                description="Sales document ID",
            ),
            VizFieldFull(
                name="booked_on",
                source="VBAK.ERDAT",
                field_role="timestamp",
                type="D8",
                description="Booking date",
            ),
            # Curator-set: additive across documents, not across dates.
            VizFieldFull(
                name="open_value",
                source="VBAK.NETWR",
                field_role="measure",
                type="P15",
                description="Open order value, restated on every booking date.",
                aggregation_behavior="SUM",
                additivity="semi_additive",
                non_additive_over=["booked_on"],
            ),
            # Legacy shape: no additivity authored, only the explicit `none`.
            VizFieldFull(
                name="cumulative_value",
                source="VBAK.NETWR",
                field_role="measure",
                type="P15",
                description="Cumulative booked value — running total.",
                aggregation_behavior="none",
            ),
        ],
    )
    ctx = _real_serializer_patch()
    try:
        updated = svc.update_yaml("silver_s4h_sd_sales_order", req, git_service=mock_git)
    finally:
        ctx.__exit__(None, None, None)

    by_name = {f.name: f for f in updated.fields}
    semi = by_name["open_value"]
    assert semi.additivity == "semi_additive"
    assert semi.non_additive_over == ["booked_on"]
    assert semi.aggregation_behavior == "SUM"
    # The legacy encoding is materialized, not silently defaulted to additive.
    assert by_name["cumulative_value"].additivity == "non_additive"
    # Absence still means additive: nothing is stamped on the non-measures.
    assert by_name["sales_doc"].additivity is None


def test_structural_replace_accepts_a_semi_additive_over_a_non_timestamp(svc, workspace):
    """v2 (2026-08-03) — a NON-temporal collapse dimension is legal on the admin path.

    This test previously asserted the opposite: v1 rejected anything that was not a
    `timestamp`, on the reasoning that "collapse to the LATEST row" is undefined
    otherwise. That conflated ACCUMULATION along an ordered dimension (which does
    need the latest row) with structural REPETITION from a join fan-out (where every
    row of the group carries the same value, so any one of them is exact). The second
    case is the ordinary shape of a denormalised Silver and v1 could not express it,
    which is exactly why the instruction ended up in prose that the SQL generator
    repeatedly misread. `EntityDeriver.fanout_dims_by_table` now derives these
    dimensions mechanically.

    What must STILL be rejected — grain membership and column resolvability — is
    covered by `test_additivity_contract.py`; here we only assert the role gate is
    gone from the admin write path.
    """
    from ask_admin_api.models.viz_models import VizFieldFull, VizGrainSpec

    mock_git = MagicMock()
    req = VizYAMLUpdateRequest(
        author_email="test@onibex.com",
        grain=VizGrainSpec(entity_grain=["sales_doc"], business_grain="sales_doc"),
        fields_full=[
            VizFieldFull(
                name="sales_doc",
                source="VBAK.VBELN",
                field_role="identifier",
                type="C10",
                description="Sales document ID",
            ),
            VizFieldFull(
                name="net_value",
                source="VBAK.NETWR",
                field_role="measure",
                type="P15",
                description="Net value.",
                aggregation_behavior="SUM",
                additivity="semi_additive",
                non_additive_over=["sales_doc"],  # an identifier — legal since v2
            ),
        ],
    )
    ctx = _real_serializer_patch()
    try:
        svc.update_yaml("silver_s4h_sd_sales_order", req, git_service=mock_git)
    finally:
        ctx.__exit__(None, None, None)


def test_structural_replace_prunes_provenance_for_removed_field(svc, workspace):
    """A structural edit that drops a previously-enriched field must also drop
    its stale entry from the enrichments sidecar."""
    from ask_admin_api.models.viz_models import VizFieldFull

    mock_git = MagicMock()
    # Pre-seed provenance for net_value as if it had been enriched earlier.
    svc._enrichments_store.write(
        "silver_s4h_sd_sales_order",
        field_enrichments={"net_value": ["description"]},
    )
    # Structural replace that removes net_value entirely (keep only the identifier).
    req = VizYAMLUpdateRequest(
        author_email="test@onibex.com",
        fields_full=[
            VizFieldFull(
                name="sales_doc",
                source="VBAK.VBELN",
                field_role="identifier",
                type="C10",
                description="Sales document ID",
            ),
        ],
    )
    ctx = _real_serializer_patch()
    try:
        svc.update_yaml("silver_s4h_sd_sales_order", req, git_service=mock_git)
    finally:
        ctx.__exit__(None, None, None)

    _entity_enr, field_enr = svc._enrichments_store.read("silver_s4h_sd_sales_order")
    assert "net_value" not in field_enr  # pruned — field no longer exists


# ── field `source`: optional lineage, never minted, never round-tripped blank ──

SAMPLE_GOLD_YAML = textwrap.dedent("""\
    id: gold_s4h_inventory_situation
    layer: gold
    source_system: s4h
    module: MM
    name: inventory_situation
    db_table_name: GOLD_INVENTORY_SITUATION
    description: Forward-looking stock projection per material, plant and date.
    entity_role: fact
    grain:
      entity_grain: [plant_id, future_date]
      business_grain: daily_inventory_projection
    fields:
      - name: plant_id
        type: STRING(8)
        description: Plant ID
        field_role: dimension
      - name: future_date
        type: DATE
        description: Projection date
        field_role: timestamp
      - name: future_stock
        type: DECIMAL(38,6)
        description: Projected stock at future_date
        field_role: measure
        aggregation_behavior: SUM
""")


def _seed_gold(workspace: Path, body: str = SAMPLE_GOLD_YAML) -> None:
    gold_dir = workspace / "workspace" / "ask" / "s4h" / "gold"
    gold_dir.mkdir(parents=True, exist_ok=True)
    (gold_dir / "inventory_situation.yaml").write_text(body, encoding="utf-8")


def test_structural_replace_omits_source_when_the_author_has_none(svc, workspace):
    """A Gold edit-in-full must not mint `source: ''` on every field.

    The Source column is Silver-only in the SPA, so a Gold round-trip carries no
    value — and the write path used to materialize that absence as `source: ''`,
    stating a bronze lineage the author never claimed. The published example sets
    carry no such key, so every save was a diff against them.
    """
    from ask_admin_api.models.viz_models import VizFieldFull

    _seed_gold(workspace)
    svc._invalidate_cache()
    req = VizYAMLUpdateRequest(
        author_email="test@onibex.com",
        fields_full=[
            VizFieldFull(
                name="plant_id", type="STRING(8)", field_role="dimension", description="Plant ID"
            ),
            VizFieldFull(
                name="future_date", type="DATE", field_role="timestamp", description="Proj. date"
            ),
            VizFieldFull(
                name="future_stock",
                type="DECIMAL(38,6)",
                field_role="measure",
                description="Projected stock",
                aggregation_behavior="SUM",
            ),
        ],
    )
    ctx = _real_serializer_patch()
    try:
        updated = svc.update_yaml("gold_s4h_inventory_situation", req, git_service=MagicMock())
    finally:
        ctx.__exit__(None, None, None)

    written = (workspace / updated.file_path).read_text(encoding="utf-8")
    assert "source:" not in written  # `source_system:` does not match this
    assert all(f.source is None for f in updated.fields)
    # A fabricated placeholder here is not inert: `fanout_dims_by_table` reads the
    # table out of `source`, and a self-reference leaves no grain member determined,
    # which stamps every uncurated measure `non_additive` + `none` ("never sum").
    stock = next(f for f in updated.fields if f.name == "future_stock")
    assert stock.aggregation_behavior == "SUM"
    assert stock.additivity is None


def test_save_drops_a_blank_source_already_in_the_file(svc, workspace):
    """An enrichment-only edit HEALS a file that already carries `source: ''`.

    Round-tripping the blank key would keep every file polluted by the previous
    behaviour polluted forever, since the per-field patch path never rewrites
    `source` at all.
    """
    from ask_admin_api.models.viz_models import VizFieldUpdate

    polluted = SAMPLE_GOLD_YAML.replace("    type:", "    source: ''\n    type:")
    assert polluted.count("source: ''") == 3  # the fixture is genuinely polluted
    _seed_gold(workspace, polluted)
    svc._invalidate_cache()

    req = VizYAMLUpdateRequest(
        author_email="test@onibex.com",
        fields=[VizFieldUpdate(name="future_stock", description="Optimistic projected stock.")],
    )
    ctx = _real_serializer_patch()
    try:
        updated = svc.update_yaml("gold_s4h_inventory_situation", req, git_service=MagicMock())
    finally:
        ctx.__exit__(None, None, None)

    written = (workspace / updated.file_path).read_text(encoding="utf-8")
    assert "source: ''" not in written
    assert "source:" not in written
    stock = next(f for f in updated.fields if f.name == "future_stock")
    assert stock.description == "Optimistic projected stock."


def test_structural_replace_keeps_a_real_silver_source(svc, workspace):
    """The other half of the rule: a bronze lineage the author DID supply is
    written verbatim. Only the empty case is dropped."""
    from ask_admin_api.models.viz_models import VizFieldFull

    req = VizYAMLUpdateRequest(
        author_email="test@onibex.com",
        fields_full=[
            VizFieldFull(
                name="sales_doc",
                source="VBAK.VBELN",
                field_role="identifier",
                type="C10",
                description="Sales document ID",
            ),
            # No lineage supplied for this one — the key must simply be absent.
            VizFieldFull(name="head_count", type="I4", field_role="measure", description="Count"),
        ],
    )
    ctx = _real_serializer_patch()
    try:
        updated = svc.update_yaml("silver_s4h_sd_sales_order", req, git_service=MagicMock())
    finally:
        ctx.__exit__(None, None, None)

    by_name = {f.name: f for f in updated.fields}
    assert by_name["sales_doc"].source == "VBAK.VBELN"
    assert by_name["head_count"].source is None
    written = (workspace / updated.file_path).read_text(encoding="utf-8")
    assert written.count("source:") == 1


# ── list_yamls projects the §3.1 entity header (catalog enrichment) ───────────


def test_list_yamls_projects_the_entity_header(svc, workspace):
    """The catalog row carries the header keys, not just name / layer / module.

    `business_process` is the one the catalog was missing outright: it is required
    by the standard at Silver/Gold and no client could read it, because neither the
    summary nor the full node projected it.
    """
    _seed_gold(
        workspace,
        SAMPLE_GOLD_YAML.replace(
            "layer: gold\n",
            "layer: gold\nversion: '2'\nbusiness_process: INVENTORY SITUATION\n"
            "internal_id: s4h_100_004\ntag1: SCM\ntag2: MM\nclassification: T\n",
        ),
    )
    svc._invalidate_cache()

    rows = {r.id: r for r in svc.list_yamls()}
    gold = rows["gold_s4h_inventory_situation"]
    assert gold.business_process == "INVENTORY SITUATION"
    assert gold.description.startswith("Forward-looking stock projection")
    assert gold.entity_role == "fact"
    assert gold.classification == "T"
    assert gold.db_table_name == "GOLD_INVENTORY_SITUATION"
    assert gold.source_system == "s4h"
    assert (gold.tag1, gold.tag2) == ("SCM", "MM")
    assert gold.version == "2"  # the YAML's spec version, not the lifecycle one
    assert gold.internal_id == "s4h_100_004"
    # Counts + structure feed the expandable detail without a second request.
    assert (gold.field_count, gold.measure_count) == (3, 1)
    assert gold.entity_grain == ["plant_id", "future_date"]
    assert gold.relationship_count == 0
    assert gold.has_normalization is False

    # The seeded Silver: `module` + counts still right on the other field shape.
    silver = rows["silver_s4h_sd_sales_order"]
    assert silver.module == "sd"
    assert (silver.field_count, silver.measure_count) == (2, 1)
    assert (silver.entity_role, silver.classification) == ("fact", "T")


def test_list_yamls_header_is_empty_where_bronze_declares_nothing(svc):
    """Bronze declares only version / source_system / description of the header
    set, and numbers its instance `source_system_id` — normalised onto the same
    `source_system_no` field so the UI never branches on layer."""
    bronze = next(r for r in svc.list_yamls(layer=VizLayer.bronze))
    assert bronze.description == "SAP Sales Order Header"
    assert bronze.source_system == "s4h"
    # Absent at Bronze by contract — None, not "" or a fabricated placeholder.
    assert bronze.business_process is None
    assert bronze.entity_role is None
    assert bronze.classification is None
    assert bronze.tag1 is None
    # Bronze's field shape is a mapping and its columns carry no field_role.
    assert (bronze.field_count, bronze.measure_count) == (2, 0)
    assert bronze.primary_key == ["VBELN"]


def test_get_yaml_exposes_the_same_header_as_the_list(svc, workspace):
    """The opened entity and its catalog row read the same projection, so the
    detail panel and the editor can show what the row shows."""
    _seed_gold(
        workspace,
        SAMPLE_GOLD_YAML.replace("layer: gold\n", "layer: gold\nbusiness_process: SCM FLOW\n"),
    )
    svc._invalidate_cache()

    node = svc.get_yaml("gold_s4h_inventory_situation")
    row = next(r for r in svc.list_yamls() if r.id == "gold_s4h_inventory_situation")
    for key in (
        "description",
        "business_process",
        "entity_role",
        "classification",
        "db_table_name",
        "source_system",
        "version",
        "tag1",
        "tag2",
    ):
        assert getattr(node, key) == getattr(row, key), key
