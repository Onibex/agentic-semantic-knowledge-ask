"""POST /v1/artifact — guided artifact generation.

Flow:
  1. Run `data_focus` through the existing SQL pipeline to retrieve data.
  2. Call LLM a second time to render a formatted Markdown document
     using the retrieved rows + artifact specification.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth.validator import TokenClaims, validate_token
from ..config import SettingsCache
from ..models.requests import ArtifactRequest, QueryRequest
from ..models.responses import ArtifactDataset, ArtifactResponse, ErrorResponse, TokensBreakdown

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["artifact"])


def _execute_sql_direct(sql: str) -> tuple[list[dict[str, Any]], str | None]:
    """Execute a pre-built SQL string using the configured DB adapter.
    Returns (rows, error_message).
    """
    try:
        from ask_llm_gateway.infrastructure.secrets import resolve_db_config
        from ask_sql_executor.domain.models import ExecutionRequest

        from .query import _get_sql_executor

        # Route through the store-backed resolver so any registered backend
        # (not just hana/postgresql) picks up its connection. 2026-07 migration.
        db_type, db_config = resolve_db_config(None)
        result = _get_sql_executor().execute_and_format(
            ExecutionRequest(sql=sql, db_type=db_type, db_config=db_config or {}),
            question="",
        )
        if result.error:
            return [], result.error
        return result.rows_dict or [], None
    except Exception as exc:
        return [], str(exc)[:300]


_SUB_QUERY_COUNT: dict[str, int] = {
    "detailed_report": 3,
    "data_tables": 3,
    "proposal_format": 2,
    "executive_brief": 2,
    "dashboard": 2,
}

# One-line dialect hint per engine for the sub-query prompt. Covers every backend
# the DB registry supports so no engine is silently told to emit PostgreSQL.
_DIALECT_NOTES: dict[str, str] = {
    "hana": "SAP HANA SQL: double-quoted identifiers, ADD_DAYS() for dates, no NULLS LAST.",
    "postgresql": 'PostgreSQL: double-quoted identifiers, public."TABLE" format.',
    "snowflake": "Snowflake SQL: double-quoted identifiers, DATEADD() for dates.",
    "databricks": "Databricks/Spark SQL: backtick identifiers, date_add() for dates.",
    "bigquery": "BigQuery Standard SQL: backtick-quoted identifiers, DATE_ADD()/DATE_SUB().",
    "clickhouse": "ClickHouse SQL: backtick identifiers, addDays() for dates.",
    "sqlserver": "SQL Server T-SQL: [bracket] identifiers, DATEADD(), TOP n (no LIMIT).",
    "db2": "IBM Db2 SQL: double-quoted identifiers, FETCH FIRST n ROWS ONLY (no LIMIT).",
    "fabric": "Microsoft Fabric (T-SQL): [bracket] identifiers, DATEADD(), TOP n.",
}


def _generate_sub_sqls(
    main_sql: str,
    db_type: str,
    hana_schema: str,
    artifact_type: str,
    data_focus: str,
) -> list[dict[str, str]]:
    """Ask the LLM to derive N analytical sub-queries from the main SQL.
    Returns list of {name, sql} dicts; empty list on failure.
    """
    import json as _json

    from langchain_core.messages import HumanMessage, SystemMessage

    from ask_llm_gateway.application.factory import build_llm

    n = _SUB_QUERY_COUNT.get(artifact_type, 2)
    cfg = SettingsCache.get()
    llm = build_llm(cfg)

    schema_note = (
        f'MANDATORY: every table must be qualified as "{hana_schema}"."TABLE_NAME"\n'
        if hana_schema and db_type == "hana"
        else ""
    )
    # Per-engine dialect hint. Do NOT fall back to PostgreSQL for non-hana
    # engines (that was a latent multi-DB bug — a Snowflake/Databricks chat would
    # get PG sub-SQL). Unknown engines get a neutral generic note.
    dialect = _DIALECT_NOTES.get(
        db_type, f"{db_type.upper()} SQL: standard SQL with double-quoted identifiers."
    )

    system = (
        f"You are a {db_type.upper()} SQL expert. "
        f"Generate exactly {n} analytical sub-queries derived from the main query below. "
        f"Each sub-query uses the SAME tables/schema but provides a DIFFERENT analytical view: "
        f"aggregation by dimension, top-N ranking, time trend, or cross-dimension comparison. "
        f"{dialect} "
        f"Return ONLY a valid JSON array — no markdown fences, no explanation."
    )
    user = (
        f"Artifact type: {artifact_type}\n"
        f"Data focus: {data_focus}\n\n"
        f"Main SQL:\n{main_sql}\n\n"
        f"{schema_note}"
        f"Return JSON array with exactly {n} objects:\n"
        f'[{{"name": "Short Dataset Name", "sql": "SELECT ..."}}]'
    )

    try:
        response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        text = response.content.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        result = _json.loads(text)
        return [r for r in result if isinstance(r, dict) and r.get("sql", "").strip()]
    except Exception as exc:
        logger.warning("sub-SQL generation failed: %s", exc)
        return []


# ── Format instructions keyed by format slug ─────────────────────────────────
_FORMAT_GUIDES: dict[str, str] = {
    "executive_brief": (
        "Format: Executive Brief. Keep it concise (300-500 words). "
        "Structure: one bold headline statement with the most important metric or finding, "
        "## Key Metrics (4-6 bold figures with context sentences), "
        "## Insights (5-7 bullet points — most important patterns, outliers, and trends), "
        "one summary Markdown table with top data rows, "
        "## Recommendation (2-3 sentences — one clear, specific action). "
        "Lead with the most critical number. Be direct and decisive."
    ),
    "detailed_report": (
        "Format: Comprehensive Detailed Report. Write a thorough, professional document of 500-900 words. "
        "Structure: "
        "## Executive Summary (2-3 paragraphs: main findings, key metrics with exact numbers, business significance); "
        "## Data Analysis (1-3 subsections with ### subheadings, each with a Markdown table "
        "and 1-2 paragraphs of narrative explaining patterns, outliers, and business implications); "
        "## Key Findings (numbered list of 5-7 specific, quantified findings); "
        "## Recommendations (numbered list of 4-6 concrete, actionable items with rationale and next step). "
        "Bold every key metric. Use real numbers from the data. Be specific and analytical. "
        "End with: 'Document prepared by AgenticAI Analytics'."
    ),
    "data_tables": (
        "Format: Data-First. Lead with one or more well-structured Markdown tables. "
        "After each table, write 2 paragraphs: one identifying the most important pattern or outlier, "
        "one explaining the business implication. "
        "End with ## Summary containing 5-7 bullet points of the most actionable takeaways."
    ),
    "proposal_format": (
        "Format: Business Proposal. Write a persuasive, evidence-backed proposal document. Structure: "
        "## Problem Statement (2 paragraphs: quantify the issue with data, explain business impact); "
        "## Context and Background (why this matters now, what has changed); "
        "## Supporting Evidence (Markdown table with data + 2-paragraph narrative analysis); "
        "## Proposed Solution (concrete, specific recommendation with implementation steps); "
        "## Expected Impact (quantified benefits: cost savings, efficiency gains, revenue potential); "
        "## Next Steps (numbered action plan with suggested owners and timelines). "
        "Lead with the problem's business cost. Write persuasively and back every claim with data."
    ),
    "dashboard": (
        "Format: Dashboard Insights. Be very concise (under 200 words). "
        "Structure: one bold headline KPI as the first line, then ## Key Insights with 4-6 bullet points "
        "highlighting the most important patterns, outliers, or trends visible in the data. "
        "Do NOT reproduce the full data table — the chart will display it visually."
    ),
}

_DEFAULT_FORMAT_GUIDE = _FORMAT_GUIDES["detailed_report"]


def _rows_to_markdown_table(rows: list[dict[str, Any]], max_rows: int = 50) -> str:
    if not rows:
        return ""
    headers = list(rows[0].keys())
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:max_rows]:
        cells = [str(row.get(h, "")).replace("|", "/") for h in headers]
        lines.append("| " + " | ".join(cells) + " |")
    if len(rows) > max_rows:
        lines.append(f"*... and {len(rows) - max_rows} more rows (truncated)*")
    return "\n".join(lines)


def _generate_document(
    req: ArtifactRequest,
    datasets: list[dict[str, Any]],
    sql: str | None,
    trace_id: str,
    data_error: str | None = None,
) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage

    from ask_llm_gateway.application.factory import build_llm

    cfg = SettingsCache.get()
    llm = build_llm(cfg)

    format_guide = _FORMAT_GUIDES.get(req.format, _DEFAULT_FORMAT_GUIDE)

    # Build multi-dataset data section
    data_parts: list[str] = []
    for ds in datasets or []:
        tbl = _rows_to_markdown_table(ds.get("rows") or [])
        if tbl:
            data_parts.append(f"### {ds.get('name', 'Dataset')}\n\n{tbl}")

    if data_parts:
        data_section = "## Retrieved Data\n\n" + "\n\n".join(data_parts)
    else:
        reason = ""
        if data_error:
            reason = f" (query could not be executed: {data_error[:150]})"
        elif sql:
            reason = " (query returned no rows)"
        data_section = (
            f"*Note: No live data was retrieved from the system{reason}. "
            f"Generate a professional, complete analytical document based on the artifact type, "
            f"name, and purpose described below. Use industry-standard SAP S/4HANA business context "
            f"and realistic benchmarks where specific figures are unavailable. "
            f"If relevant, briefly acknowledge in the Executive Summary that live data is pending and "
            f"the figures shown are indicative estimates. "
            f"NEVER use placeholder tokens like [VALUE], [Amount], [Customer], [DATE] — "
            f"write realistic numbers or prose instead.*"
        )

    system = (
        f"You are a professional business analyst and document writer for an SAP S/4HANA analytics platform. "
        f"Generate a polished, professional document entirely in Markdown. "
        f"CRITICAL: NEVER use placeholder tokens like [VALUE], [Customer Name], [DATE], [AMOUNT], "
        f"[INSERT], or any bracket-enclosed placeholders. "
        f"If live data is unavailable, use realistic business estimates or write 'N/A' — "
        f"but always produce a complete, ready-to-use document, never a fill-in template.\n\n"
        f"{format_guide}\n\n"
        f"Writing rules: use active voice, lead with the most important number, "
        f"bold key metrics, keep tables aligned."
    )

    user = (
        f"Generate a **{req.artifact_type}** document.\n\n"
        f"**Name:** {req.name}\n"
        f"**Purpose / audience:** {req.purpose}\n"
        f"**Data requested:** {req.data_focus}\n\n"
        f"{data_section}"
    )

    try:
        from ask_llm_gateway.infrastructure.token_tracker import track_phase

        with track_phase("artifact_generation"):
            response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        return response.content
    except Exception as exc:
        logger.exception("artifact LLM generation failed", extra={"trace_id": trace_id})
        return f"# {req.name}\n\n*Document generation error: {exc}*"


@router.post(
    "/artifact",
    response_model=ArtifactResponse,
    responses={500: {"model": ErrorResponse}},
)
def create_artifact(
    req: ArtifactRequest,
    claims: TokenClaims = Depends(validate_token),
) -> ArtifactResponse:
    """Guided artifact creation: retrieve data via SQL then render a document."""
    from ask_llm_gateway.infrastructure.token_tracker import (
        TokenTracker,
        clear_active_tracker,
        set_active_tracker,
    )

    from .query import run_query_pipeline

    trace_id = uuid.uuid4().hex
    # Same multi-issuer JWT (Keycloak/XSUAA) + dev-bypass path as /v1/query — the
    # artifact endpoint must NOT use the legacy XSUAA-only dependency, which 503s
    # ("XSUAA credentials not configured") on a Keycloak deployment with no XSUAA
    # binding. Build the same `user` dict run_query_pipeline expects.
    user = {"email": claims.email, "bypass": False, "roles": claims.roles}
    tracker = TokenTracker(query_id=trace_id)
    set_active_tracker(tracker)

    try:
        # ── Step 1: retrieve main data ─────────────────────────────────────────
        sql: str | None = None
        rows: list[dict[str, Any]] = []
        data_error: str | None = None

        if req.sql_override and req.sql_override.strip():
            sql = req.sql_override.strip()
            rows, data_error = _execute_sql_direct(sql)
            if data_error:
                logger.warning(
                    "artifact sql_override execution failed: %s",
                    data_error,
                    extra={"trace_id": trace_id},
                )
        else:
            try:
                data_req = QueryRequest(
                    question=req.data_focus,
                    mode=req.mode,
                    session_id=None,
                    workspace_id=req.workspace_id,
                    env=req.env,
                )
                data_result = run_query_pipeline(data_req, user)
                sql = data_result.sql
                rows = data_result.rows or []
            except Exception as exc:
                data_error = str(exc)[:200]
                logger.warning(
                    "artifact data retrieval failed — continuing with no-data document: %s",
                    exc,
                    extra={"trace_id": trace_id},
                )

        # ── Step 2: build datasets (main + analytical sub-queries) ─────────────
        datasets: list[ArtifactDataset] = []

        if sql and not data_error:
            datasets.append(
                ArtifactDataset(
                    name="Main Dataset",
                    sql=sql,
                    rows=rows,
                )
            )

            # Generate analytical sub-queries from the main SQL
            from ask_llm_gateway.infrastructure.secrets import resolve_db_config

            db_type, _db_config = resolve_db_config(None)
            hana_schema = _db_config.get("schema", "") if db_type == "hana" else ""

            sub_sqls = _generate_sub_sqls(
                main_sql=sql,
                db_type=db_type,
                hana_schema=hana_schema,
                artifact_type=req.artifact_type,
                data_focus=req.data_focus,
            )

            # Execute sub-queries concurrently
            if sub_sqls:
                from concurrent.futures import ThreadPoolExecutor, as_completed

                with ThreadPoolExecutor(max_workers=len(sub_sqls)) as executor:
                    future_to_item = {
                        executor.submit(_execute_sql_direct, item["sql"]): item for item in sub_sqls
                    }
                    for future in as_completed(future_to_item):
                        item = future_to_item[future]
                        try:
                            sub_rows, sub_err = future.result()
                        except Exception as exc:
                            sub_rows, sub_err = [], str(exc)[:200]
                        datasets.append(
                            ArtifactDataset(
                                name=item.get("name", f"Dataset {len(datasets) + 1}"),
                                sql=item["sql"],
                                rows=sub_rows,
                                error=sub_err,
                            )
                        )

        elif sql:
            # SQL exists but execution failed or returned nothing
            datasets.append(
                ArtifactDataset(
                    name="Main Dataset",
                    sql=sql,
                    rows=[],
                    error=data_error,
                )
            )

        # ── Step 3: generate document ──────────────────────────────────────────
        datasets_dicts = [ds.model_dump() for ds in datasets]
        content = _generate_document(req, datasets_dicts, sql, trace_id, data_error=data_error)

        # ── Step 4: token summary ──────────────────────────────────────────────
        summary = tracker.summary()
        breakdown: TokensBreakdown | None = None
        if (summary.get("total_calls") or 0) > 0:
            breakdown = TokensBreakdown(
                total_calls=summary["total_calls"],
                input_tokens=summary["input_tokens"],
                output_tokens=summary["output_tokens"],
                total_tokens=summary["total_tokens"],
                total_cost_usd=summary.get("total_cost_usd", 0.0),
                by_phase=summary.get("by_phase", {}),
                records=summary.get("records", []),
            )

        return ArtifactResponse(
            name=req.name,
            artifact_type=req.artifact_type,
            format=req.format,
            content=content,
            sql=sql,
            rows=rows or None,
            data_error=data_error,
            datasets=datasets or None,
            trace_id=trace_id,
            tokens_used=summary.get("total_tokens"),
            tokens_breakdown=breakdown,
        )

    except Exception as exc:
        logger.exception("artifact creation failed", extra={"trace_id": trace_id})
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error_code="ARTIFACT_ERROR",
                message=str(exc),
                trace_id=trace_id,
            ).model_dump(),
        )
    finally:
        clear_active_tracker()
