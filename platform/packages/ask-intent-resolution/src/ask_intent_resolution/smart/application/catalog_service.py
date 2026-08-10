"""
CatalogService — builds and caches the compact Silver+Gold catalog that the
EntitySelectorService injects into the prompt.

Responsibilities:
  1. Initial query to ask-entity-registry-v1 filtering layer in ["silver","gold"].
  2. Map OpenSearch docs → CatalogEntry.
  3. Cache in memory (one service process = one live catalog).
  4. Provide manual invalidation (refresh()) for when the corpus is re-ingested.
  5. Render the catalog as YAML-ish text for the prompt.

The rendered catalog is expected to be ~3-5K tokens with 40-50 entities.
Prompt caching keeps that cost at ~$0.001/query in steady state.
"""

from __future__ import annotations

import re
from typing import Any

from opensearchpy.helpers import scan

from ask_intent_resolution.smart.domain.catalog import Catalog, CatalogEntry


class CatalogService:
    """Lee ask-entity-registry-v1, construye y cachea el catálogo v2."""

    ENTITY_INDEX = "ask-entity-registry-v1"
    ALLOWED_LAYERS = ("silver", "gold")

    _SOURCE_FIELDS = [
        "id",
        "name",
        "layer",
        "module",
        "entity_role",
        "description",
        "business_process",
    ]

    def __init__(self, os_repository):
        """
        Args:
            os_repository: OpenSearchAskRepository de src/pipeline/infrastructure/.
                Reusamos la infra de v1 en vez de duplicar.
        """
        self._repo = os_repository
        self._cache: Catalog | None = None

    def get_catalog(
        self,
        allowed_ids: set[str] | None = None,
        force_refresh: bool = False,
    ) -> Catalog:
        """
        Devuelve el catálogo. Primera llamada hace fetch a OpenSearch.

        Args:
            allowed_ids: si se provee, filtra a sólo esos IDs (profile scope).
                Útil para restringir el catálogo al scope del perfil activo
                (config.pipeline_v2.active_profile — unión de sus data_products + extras).
            force_refresh: re-fetch desde OpenSearch.
        """
        if self._cache is None or force_refresh:
            self._cache = self._fetch_from_opensearch()
        # Scope contract: None = unscoped (full catalog); empty set = empty scope
        # (no entries). Branch on `is not None`, NOT truthiness, so an empty
        # workspace scope does not silently return the whole catalog.
        if allowed_ids is not None:
            return Catalog(
                entries=[e for e in self._cache.entries if e.id in allowed_ids],
                version=self._cache.version,
            )
        return self._cache

    @staticmethod
    def resolve_active_entity_ids(config: dict) -> set[str] | None:
        """
        Lee config.pipeline_v2.{active_profile, profiles, data_products} y devuelve
        el set de entity IDs del perfil activo: unión de los entity_ids de cada
        data product listado en el perfil + sus extra_entity_ids.

        Returns None si no hay perfil activo configurado (catálogo completo).
        """
        pv2 = (config or {}).get("pipeline_v2") or {}
        active = pv2.get("active_profile")
        profiles = pv2.get("profiles") or {}
        dps = pv2.get("data_products") or {}
        if not active or active not in profiles:
            return None
        profile = profiles[active] or {}
        ids: set[str] = set()
        for dp_name in profile.get("data_products") or []:
            dp = dps.get(dp_name) or {}
            ids.update(dp.get("entity_ids") or [])
        ids.update(profile.get("extra_entity_ids") or [])
        return ids or None

    def refresh(self) -> Catalog:
        """Invalida cache y re-fetch."""
        return self.get_catalog(force_refresh=True)

    def render_as_prompt_context(self, catalog: Catalog | None = None) -> str:
        """
        Renderiza el catálogo como bloque estructurado para inyectar al prompt.

        Formato estable (determinístico) — mismo catálogo produce exactamente la
        misma cadena para maximizar cache hits del prompt caching de Claude.

        Agrupa por módulo (o dominio Gold), ordena alfabéticamente dentro de cada
        grupo por `id`. Incluye counts por grupo para que el LLM sepa el tamaño.
        """
        cat = catalog if catalog is not None else self.get_catalog()

        # Agrupar por grouping_key (módulo o dominio Gold)
        buckets: dict[str, list[CatalogEntry]] = {}
        for entry in cat.entries:
            buckets.setdefault(entry.grouping_key, []).append(entry)

        # Ordenar cada bucket por id
        for key in buckets:
            buckets[key].sort(key=lambda e: e.id)

        # Ordenar buckets alfabéticamente (Gold al final por prefijo "Gold / ...")
        sorted_groups = sorted(buckets.keys())

        lines: list[str] = []
        lines.append("=== ENTITY CATALOG (Silver + Gold) ===")
        lines.append(f"total_entities: {len(cat.entries)}")
        lines.append(f"groups: {len(sorted_groups)}")
        lines.append("")

        for group_key in sorted_groups:
            entries = buckets[group_key]
            lines.append(f"## {group_key}  (count: {len(entries)})")
            for e in entries:
                lines.append(f"- id: {e.id}")
                lines.append(f"  name: {e.name}")
                role = e.entity_role
                lines.append(f"  layer: {e.layer} | role: {role}")
                if e.entity_type:
                    lines.append(f"  entity_type: {e.entity_type}")
                desc = (e.description or "").strip().replace("\n", " ")
                if desc:
                    lines.append(f"  description: {desc}")
                lines.append("")

        return "\n".join(lines)

    # ── internals ────────────────────────────────────────────────────────────

    def _fetch_from_opensearch(self) -> Catalog:
        """Scroll sobre Entity Registry filtrando layer in [silver, gold]."""
        query = {
            "query": {"terms": {"layer": list(self.ALLOWED_LAYERS)}},
            "_source": self._SOURCE_FIELDS,
        }
        entries: list[CatalogEntry] = []
        # env-aware: use the repo's resolved index (dev/prod), not the base literal,
        # so a dev/prod chat reads that env's catalog instead of the legacy index.
        for hit in scan(self._repo.client, index=self._repo.INDEX_ENTITY, query=query):
            entry = self._doc_to_entry(hit.get("_source", {}))
            if entry is not None:
                entries.append(entry)
        return Catalog(entries=entries)

    def _doc_to_entry(self, source: dict[str, Any]) -> CatalogEntry | None:
        """Convierte un _source de OpenSearch a CatalogEntry. None si inválido."""
        entity_id = source.get("id")
        layer = source.get("layer")
        if not entity_id or layer not in self.ALLOWED_LAYERS:
            return None

        raw_module = source.get("module")
        if isinstance(raw_module, list):
            raw_module = raw_module[0] if raw_module else None
        elif isinstance(raw_module, str) and "," in raw_module:
            # save_gold_node joins multi-module lists as "SD,MM"; take first
            raw_module = raw_module.split(",")[0].strip() or None
        module = raw_module or self._infer_module_from_id(entity_id)
        entity_role = source.get("entity_role") or "reference"

        try:
            return CatalogEntry(
                id=entity_id,
                name=source.get("name") or entity_id,
                layer=layer,
                module=module,
                entity_role=entity_role,
                description=source.get("description") or "",
                business_process=source.get("business_process"),
            )
        except Exception:
            return None

    @staticmethod
    def _infer_module_from_id(entity_id: str) -> str | None:
        """
        Parsea módulo a partir del ID según spec Sec. 21.1:
          silver_<source_system>_<module>_<entity_name>
          gold_<domain>_<name>
        Para Gold devuelve None (el domain va en business_process).
        """
        m = re.match(r"^silver_[^_]+_([a-z]+)_", entity_id)
        if m:
            return m.group(1).upper()
        return None
