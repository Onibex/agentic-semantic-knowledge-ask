# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

from typing import Any

from pydantic import BaseModel, Field


class IRFilter(BaseModel):
    """Representa un filtro explícito extraído de la pregunta del usuario."""

    semantic_field: str = Field(
        description="El término de negocio a filtrar (ej. 'cliente', 'fecha de orden', 'estatus')"
    )
    operator: str = Field(description="Operador lógico (ej. '=', '>', '<', 'BETWEEN', 'IN')")
    value: Any = Field(description="El valor o valores a filtrar")


class SortSpec(BaseModel):
    """Especificación de ordenamiento. ASK Spec 10.1."""

    field: str = Field(
        description="El término semántico a ordenar (ej. 'net_value', 'sales_amount')"
    )
    direction: str = Field(default="DESC", description="ASC | DESC")


class TimeContext(BaseModel):
    """Contexto temporal opcional. ASK Spec 10.1."""

    field: str = Field(description="Término semántico de fecha (ej. 'posting_date', 'order_date')")
    start: str | None = Field(default=None, description="Fecha de inicio ISO 8601 (YYYY-MM-DD)")
    end: str | None = Field(default=None, description="Fecha de fin ISO 8601 (YYYY-MM-DD)")
    granularity: str | None = Field(default=None, description="day | week | month | quarter | year")


class SemanticPlanIR(BaseModel):
    """
    ASK Semantic PlanIR (Intermediate Representation).
    Esta es la salida estructurada del LLM en la Fase 1 del pipeline.
    Representa la 'intención' pura del usuario, desvinculada de tablas físicas.
    """

    intent_summary: str = Field(description="Resumen breve de la intención analítica del usuario.")
    semantic_metrics: list[str] = Field(
        default_factory=list,
        description="Lista de conceptos matemáticos o medidas a calcular (ej. ['total de ingresos', 'cantidad ordenada']).",
    )
    semantic_dimensions: list[str] = Field(
        default_factory=list,
        description="Lista de conceptos por los cuales se agrupará la información (ej. ['planta', 'mes', 'cliente']).",
    )
    filters: list[IRFilter] = Field(
        default_factory=list, description="Filtros aplicables extraídos de la pregunta."
    )
    module_hint: str | None = Field(
        default=None,
        description=(
            "Módulo SAP detectado en la pregunta. Use EXACTLY one of: "
            "'SD' (Sales & Distribution: sales orders, customers, delivery), "
            "'MM' (Materials Management: purchasing, inventory, stock), "
            "'PP' (Production Planning: production orders, manufacturing), "
            "'FI' (Finance: invoices, accounting), "
            "'CO' (Controlling: cost centers), "
            "'WM' (Warehouse Management). "
            "Set to null if uncertain or the query spans multiple modules."
        ),
    )
    time_context: TimeContext | None = Field(
        default=None,
        description="Rango de tiempo extraído (si se proporciona un mes o periodo específico).",
    )
    sorting: list[SortSpec] | None = Field(
        default=None, description="Ordenamiento requerido (ej. para Top N o listados rankeados)."
    )
    limit: int | None = Field(
        default=None, description="Límite máximo de registros a devolver (ej. 5 para un 'Top 5')."
    )
    is_impossible: bool = Field(
        default=False,
        description="True si la pregunta es un saludo o no tiene sentido analítico.",
    )

    detected_entity_hint: str | None = Field(
        default=None,
        description=(
            "El módulo SAP o tipo de entidad detectado en la query ambigua. "
            "Se usa para cargar el schema del entity y mostrar campos disponibles al usuario. "
            "Ejemplos: 'sales order', 'purchase order', 'journal entry'."
        ),
    )
