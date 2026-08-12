"""Deterministic DDL parser — the fixture set is anchored on the REAL ClickHouse
DDL that surfaced the module gap (2026-08-12 PoC test), plus one statement per
engine family the DDL + AI feature declares."""

from __future__ import annotations

from ask_admin_api.application.ddl_parser import (
    ParsedRelation,
    parse_relations,
    split_statements,
    strip_sql_comments,
)

# The live PoC table, verbatim shape: backticked lowercase names, wrapped
# Decimal params, Nullable(DateTime('UTC')), MergeTree ORDER BY, SETTINGS tail.
CLICKHOUSE_DDL = """\
-- dbt_qas_bi.gold_md_final definition

CREATE TABLE dbt_qas_bi.gold_md_final
(

    `docventas` String,

    `mandante` String,

    `posicion` Int64,

    `fecha_doc` Date,

    `year` String,

    `month` String,

    `nt_weight_mara` Decimal(76,
 7),

    `valor_neto` Decimal(76,
 7),

    `hora` Nullable(DateTime('UTC')),

    `_version` DateTime64(3)
)
ENGINE = MergeTree
ORDER BY (mandante,
 docventas,
 posicion,
 year,
 month)
SETTINGS index_granularity = 8192;
"""


def _rel(ddl: str) -> ParsedRelation:
    rels = parse_relations(ddl)
    assert len(rels) == 1
    return rels[0]


# ── The live ClickHouse case ─────────────────────────────────────────────────


def test_clickhouse_relation_name_is_unqualified_as_written():
    rel = _rel(CLICKHOUSE_DDL)
    assert rel.name == "gold_md_final"  # lowercase preserved, schema stripped
    assert rel.qualifier == "dbt_qas_bi"
    assert rel.skeleton_eligible


def test_clickhouse_columns_byte_exact_with_raw_types():
    rel = _rel(CLICKHOUSE_DDL)
    by_name = {c.name: c.raw_type for c in rel.columns}
    assert list(by_name) == [
        "docventas",
        "mandante",
        "posicion",
        "fecha_doc",
        "year",
        "month",
        "nt_weight_mara",
        "valor_neto",
        "hora",
        "_version",
    ]
    assert by_name["posicion"] == "Int64"
    assert by_name["nt_weight_mara"] == "Decimal(76, 7)"  # newline collapsed
    assert by_name["hora"] == "Nullable(DateTime('UTC'))"  # wrapper intact
    assert by_name["_version"] == "DateTime64(3)"


def test_clickhouse_order_by_is_the_key():
    rel = _rel(CLICKHOUSE_DDL)
    assert rel.primary_key == ["mandante", "docventas", "posicion", "year", "month"]
    assert rel.key_source == "order_by"


def test_clickhouse_explicit_primary_key_beats_order_by():
    ddl = (
        "CREATE TABLE t (`a` String, `b` Int64, `c` String) "
        "ENGINE = MergeTree PRIMARY KEY (a, b) ORDER BY (a, b, c)"
    )
    rel = _rel(ddl)
    assert rel.primary_key == ["a", "b"]
    assert rel.key_source == "primary_key"


def test_order_by_expressions_are_skipped_never_guessed():
    ddl = (
        "CREATE TABLE t (`d` Date, `id` Int64) ENGINE = MergeTree "
        "ORDER BY (toYYYYMM(d), id)"
    )
    rel = _rel(ddl)
    assert rel.primary_key == ["id"]  # the expression contributes nothing


# ── Other engine families ────────────────────────────────────────────────────


def test_postgres_table_constraint_pk_and_multiword_types():
    ddl = """
    CREATE TABLE public.orders (
        order_id integer NOT NULL,
        item_no integer NOT NULL,
        created_at timestamp with time zone DEFAULT now(),
        amount numeric(15,2),
        note character varying(200),
        CONSTRAINT orders_pk PRIMARY KEY (order_id, item_no)
    );
    """
    rel = _rel(ddl)
    assert rel.name == "orders"
    assert rel.qualifier == "public"
    assert rel.primary_key == ["order_id", "item_no"]
    assert rel.key_source == "primary_key"
    by_name = {c.name: c.raw_type for c in rel.columns}
    assert by_name["created_at"] == "timestamp with time zone"
    assert by_name["note"] == "character varying(200)"
    assert by_name["amount"] == "numeric(15,2)"


def test_hana_quoted_identifiers_and_inline_pk():
    ddl = 'CREATE TABLE "MY_SCHEMA"."VBAK" ("VBELN" NVARCHAR(10) PRIMARY KEY, "NETWR" DECIMAL(15,2))'
    rel = _rel(ddl)
    assert rel.name == "VBAK"
    assert rel.qualifier == "MY_SCHEMA"
    assert rel.primary_key == ["VBELN"]
    assert [c.name for c in rel.columns] == ["VBELN", "NETWR"]


def test_sqlserver_brackets_and_column_comments():
    ddl = (
        "CREATE TABLE [dbo].[Sales] ([Id] INT NOT NULL, "
        "[Amount] MONEY, [Region] NVARCHAR(50))"
    )
    rel = _rel(ddl)
    assert rel.name == "Sales"
    assert [c.name for c in rel.columns] == ["Id", "Amount", "Region"]


def test_comment_literal_captured_and_quote_safe():
    ddl = (
        "CREATE TABLE t (a String COMMENT 'client''s -- code', b Int64) "
        "ENGINE = MergeTree ORDER BY a"
    )
    rel = _rel(ddl)
    assert rel.columns[0].comment == "client's -- code"
    assert rel.columns[1].name == "b"  # the -- inside the literal did not eat the line


def test_bigquery_backticked_full_path():
    ddl = "CREATE TABLE `proj.dataset.events` (id INT64, ts TIMESTAMP)"
    rel = _rel(ddl)
    assert rel.name == "events"
    assert rel.qualifier == "proj.dataset"


# ── Views / CTAS / multi-statement ───────────────────────────────────────────


def test_view_is_not_skeleton_eligible():
    ddl = "CREATE VIEW v AS SELECT a, b FROM t JOIN u ON t.id = u.id"
    rel = _rel(ddl)
    assert rel.is_view
    assert not rel.skeleton_eligible


def test_ctas_is_not_skeleton_eligible():
    ddl = "CREATE TABLE t2 AS SELECT * FROM t1"
    rel = _rel(ddl)
    assert rel.is_view  # AS-query body
    assert not rel.skeleton_eligible


def test_multi_statement_slices_per_relation():
    ddl = CLICKHOUSE_DDL + "\nCREATE TABLE plain (x INT);\n"
    rels = parse_relations(ddl)
    assert [r.name for r in rels] == ["gold_md_final", "plain"]
    assert all(r.skeleton_eligible for r in rels)
    stmts = split_statements(ddl)
    assert len(stmts) == 2 and stmts[1].startswith("CREATE TABLE plain")


def test_column_named_like_keyword_survives_when_quoted():
    ddl = "CREATE TABLE t (`key` String, `index` Int64) ENGINE = MergeTree ORDER BY `key`"
    rel = _rel(ddl)
    assert [c.name for c in rel.columns] == ["key", "index"]
    assert rel.primary_key == ["key"]


def test_key_cliente_is_a_column_not_a_constraint():
    # Unquoted names that merely START with a constraint word are columns.
    ddl = "CREATE TABLE t (key_cliente String, primary_flag String) ENGINE = Log"
    rel = _rel(ddl)
    assert [c.name for c in rel.columns] == ["key_cliente", "primary_flag"]


def test_strip_sql_comments_is_quote_aware():
    sql = "SELECT '-- not a comment' -- real comment\n, '/* keep */'"
    out = strip_sql_comments(sql)
    assert "'-- not a comment'" in out
    assert "real comment" not in out
    assert "'/* keep */'" in out


def test_unparseable_statement_never_raises():
    rels = parse_relations("CREATE TABLE")  # nothing after the keyword
    assert len(rels) == 1
    assert not rels[0].skeleton_eligible
