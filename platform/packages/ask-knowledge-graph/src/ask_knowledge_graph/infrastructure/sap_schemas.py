# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

from pydantic import BaseModel, Field


class SapInfoSchema(BaseModel):
    """Valida el bloque 'info' del JSON"""

    id: int
    domainv: str = Field(..., min_length=1)  # Proceso de negocio (ej. ORDER TO CASH)
    type: str = Field(..., min_length=1)  # Clasificación (T o M)
    description: str
    """Description fluye 1:1 al YAML Silver (se usa para retrieval semántico
    vía BM25 + embedding). Ponlo con texto rico — idealmente un párrafo que
    explique qué representa la entidad y cuándo usarla, no solo el nombre."""
    tag2: str = Field(..., min_length=1)  # Sistema fuente (ej. S4H)
    tag3: str = Field(..., min_length=1)
    tag4: str | None = ""
    tag5: str | None = ""
    version: int | str = Field(default="1")


class SapDataprodclassSchema(BaseModel):
    """Valida el bloque 'dataprodclass'"""

    mmodule: str = Field(..., min_length=1)  # Módulo (ej. SD)


class SapColumnSchema(BaseModel):
    """Valida que cada columna tenga la información mínima para crear el Bronze/Silver"""

    tabname: str = Field(..., min_length=1)
    alias_tabname: str = Field(..., min_length=1)
    fldname: str = Field(..., min_length=1)
    alias_fldname: str = Field(..., min_length=1)
    key_field: str | None = ""
    inttype: str | None = "C"
    leng: int | str | None = 0
    description_field: str | None = ""


class SapRelationSchema(BaseModel):
    """Valida que los cruces (joins) tengan sentido lógico"""

    parent_relation: str | None = ""
    tabname: str = Field(..., min_length=1)
    field_main: str = Field(..., min_length=1)

    # Permitimos vacío porque la secuencia 1 (root) no tiene campo secundario
    field_sec: str | None = ""
    join_type: str | None = ""

    sequence: int | str
    subsequence: int | str | None = 1

    # La descripción real de la tabla ("Sales Document: Header Data"). Sin
    # declararla, Pydantic la descartaba (extra='ignore') y el parser caía
    # SIEMPRE al placeholder "SAP Table <X>" — y `description` es uno de los 8
    # campos que se indexan de un Bronze, además del único texto por el que un
    # Bronze es alcanzable léxicamente (no lleva embedding).
    description_table: str | None = ""

    # SAP delivery class (DD02L-CONTFLAG). Misma historia que `description_table`:
    # el export SIEMPRE lo trae, pero al no estar declarado Pydantic lo descartaba
    # con extra='ignore', así que `all_relations_config` en
    # `_determine_entity_role` era SIEMPRE False y la regla `M` + CONTFLAG del spec
    # (Sec 6.1) era código inalcanzable. Es el discriminador que distingue una
    # tabla de customizing de master data mientras el Data Modeler no emita `C`
    # (ver 61_UPSTREAM_DEFECT_REPORT.md, UP-4): sobre el corpus actual separa
    # 9 exports todo-`C` (las entidades de configuración) de 8 todo-`A`, sin un
    # solo falso positivo.
    contflag: str | None = ""


class SapRootSchema(BaseModel):
    """El documento completo de exportación de SAP"""

    entity: str
    info: SapInfoSchema
    dataprodclass: SapDataprodclassSchema
    columns: list[SapColumnSchema]
    relations: list[SapRelationSchema] | None = []
