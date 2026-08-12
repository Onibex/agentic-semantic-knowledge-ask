"""DDL → YAML mapping — deterministic skeleton path + legacy full-LLM path.

Routing contract pinned here: a CREATE TABLE with a typed column list is built
by the skeleton (the LLM only annotates, via structured output); views / CTAS /
column-less statements run the legacy prompt-then-parse loop; every silver/gold
doc passes the module backstop. Legacy-path fixtures therefore use VIEWs — a
bare typed table can no longer reach that path."""

from __future__ import annotations

import pytest

from ask_admin_api.application.ddl_import_service import (
    DdlImportService,
    _ensure_module,
    _normalize_flat_entity,
    count_create_tables,
    extract_yaml_payload,
    split_yaml_docs,
    strip_code_fences,
    validate_ddl_input,
)
from ask_admin_api.application.ddl_skeleton import EntityAnnotation, FieldAnnotation


def test_strip_code_fences():
    assert strip_code_fences("```yaml\nx: 1\n```") == "x: 1"
    assert strip_code_fences("```\nx: 1\n```") == "x: 1"
    assert strip_code_fences("x: 1") == "x: 1"


def test_split_yaml_docs():
    assert split_yaml_docs("a: 1\n---\nb: 2") == ["a: 1", "b: 2"]
    assert split_yaml_docs("a: 1") == ["a: 1"]
    assert split_yaml_docs("") == []
    # blank docs between separators are dropped
    assert split_yaml_docs("a: 1\n---\n\n---\nb: 2") == ["a: 1", "b: 2"]


# ── §7.1 pre-validator ────────────────────────────────────────────────────────


def test_validate_ddl_input_ok():
    validate_ddl_input("CREATE TABLE VBAK (VBELN VARCHAR(10));")  # no raise


def test_validate_ddl_input_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        validate_ddl_input("   ")


def test_validate_ddl_input_rejects_non_ddl():
    with pytest.raises(ValueError, match="CREATE TABLE"):
        validate_ddl_input("what is the weather today?")


def test_validate_ddl_input_rejects_oversized():
    big = "CREATE TABLE X (\n" + ("col VARCHAR(1),\n" * 5000) + ");"
    with pytest.raises(ValueError, match="too large"):
        validate_ddl_input(big, max_chars=1000)


def test_validate_ddl_input_accepts_temp_and_if_not_exists():
    validate_ddl_input("CREATE GLOBAL TEMPORARY TABLE T (a INT);")
    validate_ddl_input("create table if not exists t (a int);")  # case-insensitive


def test_validate_ddl_input_accepts_views_and_materialized_views():
    # A Gold entity is a physical queryable relation — views + materialized
    # views (e.g. Databricks SHOW CREATE TABLE output) must be accepted.
    validate_ddl_input("CREATE VIEW v (a INT) AS SELECT 1;")
    validate_ddl_input("CREATE OR REPLACE VIEW v AS SELECT 1;")
    validate_ddl_input(
        "CREATE MATERIALIZED VIEW `c`.`s`.`t` (a STRING COLLATE UTF8_BINARY) AS SELECT 1"
    )


def test_validate_ddl_input_accepts_snowflake_dynamic_and_transient_tables():
    # Snowflake GET_DDL on a dynamic table returns CREATE OR REPLACE DYNAMIC TABLE ...
    validate_ddl_input(
        "create or replace dynamic table MYDB.MYSCHEMA.T (A NUMBER(38,0)) "
        "TARGET_LAG = '1 hour' WAREHOUSE = WH AS SELECT 1 AS A"
    )
    validate_ddl_input("CREATE TRANSIENT TABLE t (a int);")
    validate_ddl_input("CREATE OR REPLACE SECURE VIEW v AS SELECT 1;")
    # names-only column list (no types) — Snowflake dynamic-table GET_DDL form
    validate_ddl_input(
        'create or replace dynamic table SILVER_X("a_vbak","b_vbap") '
        "target_lag='DOWNSTREAM' warehouse=WH AS "
        'SELECT COALESCE("vbak"."a",\'\') AS "a_vbak", "vbap"."b" AS "b_vbap" '
        'FROM T1 AS "vbak" JOIN T2 AS "vbap" ON 1=1'
    )


def test_count_create_tables():
    assert count_create_tables("CREATE TABLE a (x int);") == 1
    assert count_create_tables("CREATE TABLE a (x int);\nCREATE TABLE b (y int);") == 2
    assert count_create_tables("no ddl here") == 0
    # relations include views + materialized views
    assert (
        count_create_tables("CREATE TABLE a (x int);\nCREATE MATERIALIZED VIEW b AS SELECT 1;") == 2
    )


# ── §7.1 prose-tolerant extraction ────────────────────────────────────────────


def test_extract_yaml_payload_fenced_with_surrounding_prose():
    text = "Sure! Here is the YAML:\n```yaml\nid: bronze_x\nlayer: bronze\n```\nLet me know!"
    assert extract_yaml_payload(text) == "id: bronze_x\nlayer: bronze"


def test_extract_yaml_payload_bare_fence():
    assert extract_yaml_payload("```\nid: x\n```") == "id: x"


def test_extract_yaml_payload_leading_prose_no_fence():
    text = "Here you go:\nid: bronze_x\nlayer: bronze"
    assert extract_yaml_payload(text) == "id: bronze_x\nlayer: bronze"


def test_extract_yaml_payload_plain():
    assert extract_yaml_payload("id: x\nlayer: bronze") == "id: x\nlayer: bronze"


def test_extract_yaml_payload_multidoc_inside_fence():
    text = "```yaml\nid: a\n---\nid: b\n```"
    assert split_yaml_docs(extract_yaml_payload(text)) == ["id: a", "id: b"]


class _FakeLLM:
    def __init__(self, content):
        self._content = content

    def invoke(self, _messages):
        return type("R", (), {"content": self._content, "usage_metadata": {"total_tokens": 42}})()


def test_generate_yaml_parses_multidoc_and_strips_fences():
    # Views route to the legacy path — the fence/multidoc tolerance lives there.
    llm = _FakeLLM("```yaml\nid: bronze_x\nlayer: bronze\n---\nid: bronze_y\nlayer: bronze\n```")
    svc = DdlImportService(prompts_service=None, llm=llm)
    docs, tokens, warnings = svc.generate_yaml(
        "CREATE VIEW X AS SELECT 1;\nCREATE VIEW Y AS SELECT 2;",
        layer="bronze",
        source_system="s4h",
    )
    assert docs == ["id: bronze_x\nlayer: bronze", "id: bronze_y\nlayer: bronze"]
    assert tokens == 42
    assert warnings == []


def test_generate_yaml_single_doc():
    svc = DdlImportService(prompts_service=None, llm=_FakeLLM("id: bronze_x\nlayer: bronze"))
    docs, _, _ = svc.generate_yaml("CREATE TABLE X", layer="bronze", source_system="s4h")
    assert docs == ["id: bronze_x\nlayer: bronze"]


def test_generate_yaml_content_blocks():
    # Some providers return content as a list of blocks.
    llm = _FakeLLM([{"text": "id: bronze_x\n"}, {"text": "layer: bronze\n"}])
    svc = DdlImportService(prompts_service=None, llm=llm)
    docs, _, _ = svc.generate_yaml("CREATE TABLE X", layer="bronze", source_system="s4h")
    assert docs == ["id: bronze_x\nlayer: bronze"]


def test_generate_yaml_warns_on_multitable_undercount():
    # Legacy path only: input declares 2 relations, the model emits 1 → warning.
    # (Skeleton relations are 1:1 by construction, so views drive this.)
    svc = DdlImportService(prompts_service=None, llm=_FakeLLM("id: bronze_x\nlayer: bronze"))
    ddl = "CREATE VIEW X AS SELECT 1;\nCREATE VIEW Y AS SELECT 2;"
    docs, _, warnings = svc.generate_yaml(ddl, layer="bronze", source_system="s4h")
    assert len(docs) == 1
    assert warnings and any("CREATE TABLE" in w for w in warnings)


def test_normalize_flat_entity_flattens_bare_table_silver():
    # Legacy-doc guardrail (pinned directly — bare typed tables now take the
    # skeleton path, but legacy docs from odd statements still pass through it):
    # a bare CREATE TABLE has no JOIN → a Silver the model wrongly split into two
    # bronze tables (from `_mara`/`_makt` column suffixes) must be flattened.
    yaml_out = (
        "id: silver_s4h_gen_trading_goods\n"
        "layer: silver\n"
        "db_table_name: NEWECC_DEV_SILVER_TRADING_GOODS\n"
        "name: trading_goods\n"
        "composed_of:\n  - MARA\n  - MAKT\n"
        "join_graph: []\n"
        "fields:\n  - name: matnr_mara\n    source: MARA.MATNR\n"
    )
    ddl = 'CREATE TABLE ZS.NEWECC_DEV_SILVER_TRADING_GOODS ("matnr_mara" VARCHAR(40), "maktx_makt" VARCHAR(80));'
    docs, warnings = _normalize_flat_entity([yaml_out], ddl, "silver")
    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    parsed = load_yaml_text(docs[0])
    assert parsed["composed_of"] == ["NEWECC_DEV_SILVER_TRADING_GOODS"]
    assert "join_graph" not in parsed
    assert warnings and any("flattened" in w for w in warnings)


def test_normalize_flat_entity_restores_physical_field_name_from_self_source():
    # Flat table: the model stripped the suffix onto `name` and hid the physical
    # column in a self-referencing `source`. `name` MUST be the physical column
    # (what SQL SELECTs), so it is restored from source's column part.
    yaml_out = (
        "id: silver_s4h_sd_sales_order\n"
        "layer: silver\n"
        "db_table_name: NEWECC_DEV_SILVER_SD_SALES_ORDER_TB\n"
        "name: sales_order\n"
        "composed_of:\n  - NEWECC_DEV_SILVER_SD_SALES_ORDER_TB\n"
        "fields:\n"
        "  - name: mandt\n"
        '    source: "NEWECC_DEV_SILVER_SD_SALES_ORDER_TB.mandt_vbak"\n'
        "  - name: posnr\n"
        '    source: "NEWECC_DEV_SILVER_SD_SALES_ORDER_TB.posnr_vbap"\n'
    )
    ddl = 'CREATE TABLE ZS.NEWECC_DEV_SILVER_SD_SALES_ORDER_TB ("mandt_vbak" VARCHAR(6), "posnr_vbap" INT);'
    docs, warnings = _normalize_flat_entity([yaml_out], ddl, "silver")
    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    parsed = load_yaml_text(docs[0])
    names = [f["name"] for f in parsed["fields"]]
    assert names == ["mandt_vbak", "posnr_vbap"]
    # self-referencing source is redundant → dropped entirely (not kept, not self-ref)
    assert all("source" not in f for f in parsed["fields"])
    assert warnings and any("physical SQL column" in w for w in warnings)
    assert any("self-referencing" in w for w in warnings)


def test_normalize_flat_entity_normalizes_gold_fields_too():
    # Gold reuses SilverField and is always a flat physical table: the same
    # name-recovery + self-ref source drop must apply (source is not auto-filled).
    yaml_out = (
        "id: gold_s4h_sales_by_material\n"
        "layer: gold\n"
        "db_table_name: GOLD_SALES_BY_MATERIAL\n"
        "name: sales_by_material\n"
        "fields:\n"
        "  - name: material\n"
        '    source: "GOLD_SALES_BY_MATERIAL.material_id"\n'
        "    field_role: identifier\n"
        "    type: STRING(40)\n"
    )
    ddl = 'CREATE TABLE GOLD_SALES_BY_MATERIAL ("material_id" VARCHAR(40));'
    docs, warnings = _normalize_flat_entity([yaml_out], ddl, "gold")
    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    parsed = load_yaml_text(docs[0])
    assert parsed["fields"][0]["name"] == "material_id"
    assert "source" not in parsed["fields"][0]
    assert warnings and any("Gold" in w for w in warnings)


def test_normalize_flat_entity_keeps_field_name_when_source_points_to_real_origin():
    # If the model identified a bronze origin (source points at a DIFFERENT table),
    # trust its `name` — do NOT rewrite it from source.
    yaml_out = (
        "id: silver_s4h_sd_x\n"
        "layer: silver\n"
        "db_table_name: SILVER_X\n"
        "composed_of:\n  - SILVER_X\n"
        "fields:\n"
        "  - name: mandt_vbak\n"
        "    source: VBAK.MANDT\n"
    )
    ddl = 'CREATE TABLE SILVER_X ("mandt_vbak" VARCHAR(6));'
    docs, _ = _normalize_flat_entity([yaml_out], ddl, "silver")
    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    parsed = load_yaml_text(docs[0])
    assert parsed["fields"][0]["name"] == "mandt_vbak"
    assert parsed["fields"][0]["source"] == "VBAK.MANDT"


def test_generate_yaml_keeps_join_view_multi_bronze():
    # A view whose body JOINs tables genuinely composes them → NOT flattened.
    yaml_out = (
        "id: silver_s4h_sd_order\n"
        "layer: silver\n"
        "db_table_name: V_ORDER\n"
        "composed_of:\n  - VBAK\n  - VBAP\n"
        "join_graph:\n  - left_table: VBAK\n    right_table: VBAP\n"
        "    join_type: INNER\n    condition: VBAK.VBELN = VBAP.VBELN\n    sequence: 2\n"
    )
    svc = DdlImportService(prompts_service=None, llm=_FakeLLM(yaml_out))
    ddl = "CREATE VIEW V_ORDER AS SELECT a.vbeln, b.posnr FROM VBAK a INNER JOIN VBAP b ON a.vbeln=b.vbeln;"
    docs, _, warnings = svc.generate_yaml(ddl, layer="silver", source_system="s4h")
    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    parsed = load_yaml_text(docs[0])
    assert parsed["composed_of"] == ["VBAK", "VBAP"]
    assert parsed["join_graph"]  # preserved
    assert not any("flattened" in w for w in warnings)


class _CapturingLLM:
    """Captures the system + user messages so we can assert prompt composition."""

    def __init__(self):
        self.system = None
        self.user = None

    def invoke(self, messages):
        self.system = messages[0].content
        self.user = messages[1].content if len(messages) > 1 else None
        return type("R", (), {"content": "id: bronze_x\nlayer: bronze", "usage_metadata": {}})()


_VIEW_DDL = "CREATE VIEW X AS SELECT 1;"  # routes to the legacy prompt path


def test_generate_yaml_injects_source_profile_fragment():
    llm = _CapturingLLM()
    svc = DdlImportService(prompts_service=None, llm=llm)
    svc.generate_yaml(_VIEW_DDL, layer="bronze", source_system="s4h")
    assert "SOURCE SYSTEM GUIDANCE" in llm.system
    assert "SAP S/4HANA" in llm.system  # the s4h profile's prompt_fragment


def test_generate_yaml_injects_business_context():
    llm = _CapturingLLM()
    svc = DdlImportService(prompts_service=None, llm=llm)
    svc.generate_yaml(
        _VIEW_DDL,
        layer="bronze",
        source_system="s4h",
        context="These are production order confirmations from SAP PP.",
    )
    assert "BUSINESS CONTEXT" in llm.user
    assert "production order confirmations" in llm.user


def test_generate_yaml_injects_module_line():
    llm = _CapturingLLM()
    svc = DdlImportService(prompts_service=None, llm=llm)
    svc.generate_yaml(_VIEW_DDL, layer="silver", source_system="s4h", module="sd")
    assert "MODULE: sd" in llm.user


def test_generate_yaml_omits_context_block_when_empty():
    llm = _CapturingLLM()
    svc = DdlImportService(prompts_service=None, llm=llm)
    svc.generate_yaml(_VIEW_DDL, layer="bronze", source_system="s4h", context="  ")
    assert "BUSINESS CONTEXT" not in (llm.user or "")


def test_generate_yaml_injects_fragment_for_human_label():
    llm = _CapturingLLM()
    svc = DdlImportService(prompts_service=None, llm=llm)
    # A human Org label still resolves to the s4h profile (alias).
    svc.generate_yaml(_VIEW_DDL, layer="bronze", source_system="SAP S/4HANA 2023")
    assert "SAP S/4HANA" in llm.system


class _SeqLLM:
    """Returns a different content per call (the last repeats), to drive retries."""

    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = 0

    def invoke(self, _messages):
        c = self._contents[min(self.calls, len(self._contents) - 1)]
        self.calls += 1
        return type("R", (), {"content": c, "usage_metadata": {"total_tokens": 10}})()


_MALFORMED = "id: x\n\tbad: 1"  # tab indentation → ruamel raises on load


def test_generate_yaml_retries_on_malformed_then_succeeds():
    llm = _SeqLLM([_MALFORMED, "id: bronze_x\nlayer: bronze"])
    svc = DdlImportService(prompts_service=None, llm=llm)
    docs, tokens, warnings = svc.generate_yaml(_VIEW_DDL, layer="bronze", source_system="s4h")
    assert llm.calls == 2  # retried once
    assert docs == ["id: bronze_x\nlayer: bronze"]
    assert tokens == 20  # accumulated across attempts
    assert not any("malformed" in w for w in warnings)


def test_generate_yaml_warns_when_still_malformed_after_retry():
    llm = _SeqLLM([_MALFORMED])  # always malformed
    svc = DdlImportService(prompts_service=None, llm=llm)
    docs, _, warnings = svc.generate_yaml(_VIEW_DDL, layer="bronze", source_system="s4h")
    assert llm.calls == 3  # exhausted max_attempts (default 3)
    assert any("malformed" in w for w in warnings)
    # small malformed doc → "re-run" hint, not the truncation hint
    assert any("re-run" in w for w in warnings)


def test_generate_yaml_warns_truncation_on_large_malformed_doc():
    # A big-but-broken doc (> ~12k chars) reads as an output-truncation case.
    big_broken = "id: x\n\tbad: 1\n" + ("# filler comment line\n" * 1000)
    llm = _SeqLLM([big_broken])
    svc = DdlImportService(prompts_service=None, llm=llm)
    _, _, warnings = svc.generate_yaml(_VIEW_DDL, layer="bronze", source_system="s4h")
    assert any("LLM_MAX_TOKENS" in w for w in warnings)


# ── Skeleton path (typed CREATE TABLE → deterministic build + annotation) ────


class _Msg:
    def __init__(self, tokens: int):
        self.usage_metadata = {"total_tokens": tokens}


class _StructuredRunnable:
    def __init__(self, out):
        self._out = out

    def invoke(self, _messages):
        return self._out


class _StructuredLLM:
    """Honors with_structured_output; raises if the legacy .invoke is used."""

    def __init__(self, annotation: EntityAnnotation | None, tokens: int = 55):
        self._annotation = annotation
        self._tokens = tokens
        self.structured_calls = 0

    def with_structured_output(self, schema, include_raw=False):
        assert include_raw is True
        self.structured_calls += 1
        return _StructuredRunnable(
            {"raw": _Msg(self._tokens), "parsed": self._annotation, "parsing_error": None}
        )

    def invoke(self, _messages):  # pragma: no cover — must never be reached
        raise AssertionError("legacy invoke used for a skeleton-eligible table")


_CLICKHOUSE_GOLD = (
    "CREATE TABLE dbt_qas_bi.gold_md_final (`docventas` String, `mandante` String, "
    "`posicion` Int64, `valor_neto` Decimal(76, 7)) "
    "ENGINE = MergeTree ORDER BY (mandante, docventas, posicion)"
)


def _annotation() -> EntityAnnotation:
    return EntityAnnotation(
        entity_name="ventas_detalle",
        description="Detalle de ventas",
        fields=[
            FieldAnnotation(column="valor_neto", field_role="measure", description="Valor neto")
        ],
    )


def test_generate_yaml_typed_table_goes_through_the_skeleton():
    llm = _StructuredLLM(_annotation())
    svc = DdlImportService(prompts_service=None, llm=llm)
    docs, tokens, warnings = svc.generate_yaml(
        _CLICKHOUSE_GOLD, layer="gold", source_system="s4h", module="sd"
    )
    assert llm.structured_calls == 1  # one annotation call, no legacy call
    assert tokens == 55
    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    parsed = load_yaml_text(docs[0])
    assert parsed["id"] == "gold_s4h_ventas_detalle"
    assert parsed["module"] == "sd"  # the user's module, never a model guess
    assert parsed["db_table_name"] == "gold_md_final"
    assert parsed["grain"]["entity_grain"] == ["mandante", "docventas", "posicion"]
    names = [f["name"] for f in parsed["fields"]]
    assert names == ["docventas", "mandante", "posicion", "valor_neto"]  # byte-exact
    assert any("ORDER BY" in w for w in warnings)  # verify-grain advisory


def test_generate_yaml_degrades_to_defaults_when_annotation_unavailable():
    # An LLM without structured-output support (or one whose provider silently
    # dropped the schema): the import still lands, with mechanical defaults.
    llm = _FakeLLM("never used as YAML")  # no with_structured_output attribute
    svc = DdlImportService(prompts_service=None, llm=llm)
    docs, _, warnings = svc.generate_yaml(
        _CLICKHOUSE_GOLD, layer="gold", source_system="s4h", module="gen"
    )
    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    parsed = load_yaml_text(docs[0])
    assert parsed["id"] == "gold_s4h_gold_md_final"  # name defaulted from the table
    assert parsed["module"] == "gen"
    assert any("annotation degraded" in w for w in warnings) or any(
        "annotation unavailable" in w for w in warnings
    )


def test_generate_yaml_mixed_input_routes_each_relation():
    # One typed table (skeleton) + one view (legacy) in the same paste.
    view_yaml = "id: gold_s4h_from_view\nlayer: gold\nmodule: sd\nname: from_view"
    llm = _HybridLLM(_annotation(), view_yaml)
    svc = DdlImportService(prompts_service=None, llm=llm)
    ddl = _CLICKHOUSE_GOLD + ";\nCREATE VIEW v_sales AS SELECT 1;"
    docs, _, _ = svc.generate_yaml(ddl, layer="gold", source_system="s4h", module="sd")
    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    parsed = [load_yaml_text(d) for d in docs]
    ids = {p["id"] for p in parsed}
    assert ids == {"gold_s4h_ventas_detalle", "gold_s4h_from_view"}


class _HybridLLM(_StructuredLLM):
    """Structured output for the skeleton path + plain invoke for the legacy path."""

    def __init__(self, annotation, legacy_yaml: str):
        super().__init__(annotation)
        self._legacy_yaml = legacy_yaml

    def invoke(self, _messages):
        return type(
            "R", (), {"content": self._legacy_yaml, "usage_metadata": {"total_tokens": 7}}
        )()


# ── The module backstop (the 2026-08-12 ClickHouse regression) ───────────────


def test_ensure_module_fills_missing_module_with_warning():
    doc = "id: gold_s4h_x\nlayer: gold\nname: x\n"
    docs, warnings = _ensure_module([doc], layer="gold", module="sd")
    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    assert load_yaml_text(docs[0])["module"] == "sd"
    assert warnings and "module" in warnings[0]


def test_ensure_module_respects_an_existing_module():
    doc = "id: gold_s4h_x\nlayer: gold\nmodule: fi\nname: x\n"
    docs, warnings = _ensure_module([doc], layer="gold", module="sd")
    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    assert load_yaml_text(docs[0])["module"] == "fi"  # model/author value wins
    assert warnings == []


def test_ensure_module_ignores_bronze_and_unparseable_docs():
    docs, warnings = _ensure_module(["id: x\n\tbroken"], layer="gold", module="sd")
    assert docs == ["id: x\n\tbroken"]  # untouched — the import reports it
    assert warnings == []
    docs, _ = _ensure_module(["id: b\nlayer: bronze\n"], layer="bronze", module="sd")
    assert docs == ["id: b\nlayer: bronze\n"]


def test_generate_yaml_backstops_module_on_legacy_docs():
    # The legacy model omitted `module` (the live ClickHouse failure) — the
    # batch module lands deterministically before import.
    view_yaml = "id: gold_s4h_x\nlayer: gold\nname: x\ndb_table_name: t"
    svc = DdlImportService(prompts_service=None, llm=_FakeLLM(view_yaml))
    docs, _, warnings = svc.generate_yaml(
        "CREATE VIEW t AS SELECT 1;", layer="gold", source_system="s4h", module="co"
    )
    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    assert load_yaml_text(docs[0])["module"] == "co"
    assert any("`module` was missing" in w for w in warnings)
