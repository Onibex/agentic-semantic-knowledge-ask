"""
src/pipeline_v2/domain/catalog.py
─────────────────────────────────────────────────────────────────────────────
CatalogEntry — representación compacta de una entidad para el prompt context
del EntitySelectorService.

El catálogo entero (~40-50 entries de Silver+Gold) se renderiza en ~3-5K tokens
y se cachea (ideal para prompt caching de Claude).

Spec ref: Sec. 7.1 (Entity Registry), Sec. 13.1 (Retrieval Ranking).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Layer = Literal["silver", "gold"]
EntityRole = Literal["fact", "dimension", "reference"]


class CatalogEntry(BaseModel):
    """Una entrada mínima del catálogo que ve el LLM Selector.

    Sólo campos que ayudan al LLM a discriminar una entity de otra.
    NO incluye fields ni raw_yaml — el selector sólo elige IDs.
    """

    id: str = Field(..., description="Ej. 'silver_s4h_sd_sales_order'")
    name: str = Field(..., description="Nombre corto business-friendly")
    layer: Layer
    module: str | None = Field(
        default=None,
        description=(
            "SAP module (SD, MM, FI, PP, HR, ...). Silver lo trae explícito. "
            "Gold no siempre — se deriva del ID (gold_<domain>_<name>) o queda None."
        ),
    )
    entity_role: EntityRole
    description: str = Field(default="", description="info.description completo del YAML")
    entity_type: str | None = Field(
        default=None,
        description="Tipo semántico (journal_entry, sales_order, ...) — spec Sec. 7.1",
    )
    business_process: str | None = Field(
        default=None,
        description="Para Gold: dominio/proceso (ar, otc, scm, ...)",
    )

    @property
    def grouping_key(self) -> str:
        """Clave para agrupar en el catálogo rendereado."""
        if self.module:
            return self.module.upper()
        if self.business_process:
            return f"Gold / {self.business_process.upper()}"
        return "OTHER"


class Catalog(BaseModel):
    """Catálogo completo de entidades consultables (Silver + Gold)."""

    entries: list[CatalogEntry]
    version: str = Field(default="v1")

    def filter_by_modules(self, modules: list[str]) -> Catalog:
        """Narrow catalog to entries in specified SAP modules (uppercase)."""
        mods_upper = {m.upper() for m in modules}
        return Catalog(
            entries=[e for e in self.entries if (e.module and e.module.upper() in mods_upper)],
            version=self.version,
        )

    def get_entry(self, entity_id: str) -> CatalogEntry | None:
        """Returns entry by id or None."""
        for e in self.entries:
            if e.id == entity_id:
                return e
        return None

    def valid_ids(self) -> set[str]:
        """Set de IDs válidos (para validación contra LLM hallucination)."""
        return {e.id for e in self.entries}
