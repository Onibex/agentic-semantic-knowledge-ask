"""
src/pipeline_v2/domain/ir.py
─────────────────────────────────────────────────────────────────────────────
Semantic Plan IR v2 — alineado al ASK Specification Sec. 10.1.

Diferencias vs el IR de v1 (src/pipeline/domain/ir_models.py):
  - base_entity es un entity_id (string), no un SemanticMetric resolved
  - traversals[] es lista de entity_ids a alcanzar (no de dimensions)
  - measures/dimensions son NOMBRES de business terms; el PathResolver los
    resuelve a physical fields después
  - filters usan shape {field, operator, value} como dict genérico
  - No hay resolved_plan — eso es responsabilidad del compiler / freeform SQL

Validation rules (spec Sec. 10.2) se aplican en EntitySelectorService.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

OutputShape = Literal["table", "scalar", "time_series", "ranked_list"]
Operator = Literal[
    "EQ",
    "NE",
    "GT",
    "GE",
    "LT",
    "LE",
    "IN",
    "NOT_IN",
    "LIKE",
    "NOT_LIKE",
    "IS_NULL",
    "IS_NOT_NULL",
    "BETWEEN",
]
Direction = Literal["ASC", "DESC"]


class IRFilter(BaseModel):
    field: str
    operator: Operator
    value: Any | None = None
    values: list[Any] | None = None  # for IN / NOT_IN / BETWEEN


class IRTimeContext(BaseModel):
    field: str = Field(..., description="Timestamp field name")
    start: str | None = None  # ISO date
    end: str | None = None  # ISO date
    granularity: Literal["day", "week", "month", "quarter", "year"] | None = None


class IRSort(BaseModel):
    field: str
    direction: Direction = "DESC"


class SemanticPlanIRv2(BaseModel):
    """Output del EntitySelectorService — el único artifact que produce el LLM #1.

    Spec Sec. 10.1 schema (adapted, without selected_metric — the `metric`
    layer has been removed from the semantic layer).
    """

    intent: str = Field(..., description="NL description para audit y debugging")
    base_entity: str = Field(
        ...,
        description="Silver/Gold entity ID — primary query target",
    )
    measures: list[str] = Field(
        default_factory=list,
        description="Business-term names de las medidas a agregar",
    )
    dimensions: list[str] = Field(
        default_factory=list,
        description="Business-term names para GROUP BY",
    )
    filters: list[IRFilter] = Field(default_factory=list)
    time_context: IRTimeContext | None = None
    traversals: list[str] = Field(
        default_factory=list,
        description="Entity IDs que el query necesita alcanzar (base_entity excluido)",
    )
    output_shape: OutputShape = "table"
    sorting: list[IRSort] = Field(default_factory=list)
    limit: int | None = None

    # Signals del selector (no son parte formal del spec pero son útiles)
    module_hints: list[str] = Field(
        default_factory=list,
        description="Módulos SAP relevantes según el selector (SD/MM/FI/...)",
    )
    reasoning: str | None = Field(
        default=None,
        description="Explicación libre del selector para trace/debug",
    )


class SelectorOutput(BaseModel):
    """Wrapper del output del LLM selector con validación + metadata de la llamada."""

    ir: SemanticPlanIRv2
    invalid_entity_ids: list[str] = Field(
        default_factory=list,
        description="IDs que el LLM devolvió pero no existen en el catálogo",
    )
    retry_count: int = 0
