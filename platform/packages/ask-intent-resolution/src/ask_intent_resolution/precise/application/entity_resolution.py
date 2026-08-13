import logging
from typing import Any

from ask_intent_resolution.precise.application.ocsl_retriever import OCSLHybridRetriever
from ask_intent_resolution.precise.domain.ir_models import SemanticPlanIR

logger = logging.getLogger(__name__)


from ask_intent_resolution.precise.application.semantic_field_mapper import (
    SemanticFieldMapperService,
)
from ask_knowledge_graph.application._legacy_dictionary import (
    SemanticDictionaryService,
)
from ask_knowledge_graph.infrastructure._legacy_config import ConfigManager


class EntityResolutionService:
    def __init__(
        self,
        embedder,
        os_repository,
        llm,
        semantic_dictionary: SemanticDictionaryService | None = None,
    ):
        self.retriever = OCSLHybridRetriever(repository=os_repository, embedder=embedder)
        self.field_mapper = SemanticFieldMapperService(llm=llm)
        self.semantic_dictionary = semantic_dictionary

        # Cargar esquema global para resolución de nombres físicos.
        # `or {}`: load_config() returns None when config/settings.json is absent
        # (gitignored — a fresh clone has none), and the bare `.get()` chain then
        # crashed the whole PRECISE chat path with
        # "'NoneType' object has no attribute 'get'" (BACKLOG group 0, P1).
        config = ConfigManager().load_config() or {}
        self.global_schema = (config.get("hana") or {}).get("schema") or (
            config.get("postgresql") or {}
        ).get("schema")

    def _expand_phrases(self, dimensions: list[str]) -> list[str]:
        """
        Phrase Expansion: busca cada dimensión en el diccionario global.
        Si es tipo 'phrase', expande sus campos semánticos/técnicos en la lista.
        Soporta campos mixtos (semánticos y físicos): "document number, POSNR, customer".
        Deduplica preservando orden.
        """
        if not self.semantic_dictionary:
            return dimensions

        expanded: list[str] = []
        for dim in dimensions:
            matches = self.semantic_dictionary.lookup_term_global(dim)
            phrase_match = next((m for m in matches if m.get("type") == "phrase"), None)
            if phrase_match:
                raw_fields = phrase_match.get("technical_name", "")
                fields = [f.strip() for f in raw_fields.split(",") if f.strip()]
                if fields:
                    print(f"📖 [Phrase Expansion] '{dim}' → {fields}")
                    expanded.extend(fields)
                    continue
            expanded.append(dim)

        # Deduplica preservando orden (case-insensitive)
        seen: set = set()
        unique: list[str] = []
        for term in expanded:
            key = term.lower()
            if key not in seen:
                seen.add(key)
                unique.append(term)
        return unique

    # ── YAML SELECTION (semi-deterministic hybrid path) ─────────────────────
    # Returns raw YAMLs of the top-ranked entities so the FreeformSQLGenerator
    # can reason over full schema context. Hybrid OCSL retrieval + Medallion
    # re-ranking happen inside `self.retriever.get_relevant_documents(...)`.
    def select_relevant_yamls(
        self,
        plan_ir: SemanticPlanIR,
        top_k: int = 5,
        include_bronze: bool = False,
        allowed_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Selection-only variant used by the semi-deterministic hybrid pipeline.

        Flow:
          1. Expand IR phrases + build enriched retrieval query.
          2. Call `OCSLHybridRetriever.get_relevant_documents(...)` → sorted
             candidates with Medallion-adjusted `_final_score`.
          3. Filter by layer (Silver/Gold; Bronze optional).
          4. Return up to `top_k` entries as:
               [
                 {
                   "id": "silver_s4h_sd_sales_order",
                   "layer": "silver",
                   "module": "SD",
                   "entity_role": "fact",
                   "raw_yaml": "<full YAML string from ingestion>",
                   "final_score": 1.78,
                   "name": "sales_order",
                 },
                 ...
               ]

        The caller (future LangGraph node) feeds:
          - `raw_yaml` list → `FreeformSQLGeneratorService.generate(yamls=...)`
          - `id`   list   → `PathSelectorService.expand_context(anchor_yamls=...)`

        Raises:
          ValueError if retrieval returns zero candidates.
        """
        # --- STAGE 0: Phrase expansion (non-destructive copy) ---------------
        original_dims = list(plan_ir.semantic_dimensions)
        expanded_dims = self._expand_phrases(plan_ir.semantic_dimensions)
        if expanded_dims != original_dims:
            print(f"📖 [YAML Selection] Dimensions expanded: {original_dims} → {expanded_dims}")

        # --- Enriched retrieval query (anchors search to entity hint + IR terms) ---
        query_parts: list[str] = []
        if plan_ir.detected_entity_hint:
            query_parts.append(plan_ir.detected_entity_hint)
        if plan_ir.intent_summary:
            query_parts.append(plan_ir.intent_summary)
        key_terms = (plan_ir.semantic_metrics + expanded_dims)[:5]
        query_parts.extend(key_terms)
        query_text = " ".join(filter(None, query_parts)).strip()

        if not query_text:
            raise ValueError("Cannot build retrieval query from IR — all text fields empty.")

        print(f"🔎 [YAML Selection] Retrieval query: '{query_text}'")

        # --- STAGE 1-2: OCSL hybrid retrieval + Medallion re-ranking --------
        # module_hint + detected_entity_hint se siguen usando para enriquecer
        # `query_text` (más señal al BM25+kNN), pero ya NO como bonuses
        # aditivos separados — ver limpieza post-validación 2026-04-21.
        reranked = self.retriever.get_relevant_documents(
            query_text,
            has_metrics=bool(plan_ir.semantic_metrics),
            allowed_ids=allowed_ids,
        )

        if not reranked:
            raise ValueError(
                "YAML selection returned zero candidates. Check OpenSearch "
                "connectivity and whether the entity-registry index has been "
                "populated."
            )

        # --- Filter by layer + pack output ----------------------------------
        # Silver + Gold only. The `metric` layer was removed from the semantic
        # layer, and until the registry purge runs, legacy metric documents may
        # still sit in the index — this gate keeps them out of the SQL prompt.
        allowed_layers = {"silver", "gold"}
        if include_bronze:
            allowed_layers.add("bronze")

        selected: list[dict[str, Any]] = []
        for doc in reranked:
            source = doc.get("_source", {}) or {}
            layer = (source.get("layer") or "").lower()
            if layer not in allowed_layers:
                continue

            raw_yaml = source.get("raw_yaml", "") or ""
            if not raw_yaml.strip():
                # No raw YAML stored — skip silently. The caller gets fewer
                # than top_k; log so we notice.
                print(
                    f"⚠️  [YAML Selection] Skipping '{source.get('id')}' — "
                    f"no raw_yaml stored in OpenSearch."
                )
                continue

            module = source.get("module", "")
            if isinstance(module, list):
                module = ",".join(m for m in module if m)

            selected.append(
                {
                    "id": source.get("id"),
                    "name": source.get("name"),
                    "layer": layer,
                    "module": module,
                    "entity_role": (source.get("entity_role") or "").lower(),
                    "raw_yaml": raw_yaml,
                    "final_score": float(doc.get("_final_score", 0.0)),
                }
            )
            if len(selected) >= top_k:
                break

        if not selected:
            raise ValueError(
                "YAML selection filtered out every candidate. "
                "Likely cause: none of the retrieved entities have raw_yaml "
                "stored, or all matched an excluded layer."
            )

        print(
            f"✅ [YAML Selection] {len(selected)} YAML(s) selected: "
            + ", ".join(f"{e['id']}({e['layer']})" for e in selected)
        )
        return selected

    # ── GOLD-ONLY ANCHOR SELECTION (Plan v1 — 2-pass freeform) ──────────────
    # Starter set for the 2-pass SQL flow: devuelve SOLO Golds que superaron el
    # governance gate (no Silvers de apoyo). Usado como contexto inicial del
    # FreeformSQLGenerator. Si el LLM necesita más contexto, pedirá Silvers
    # puntuales vía `fetch_entities_by_ids`.
    def select_gold_anchors(
        self,
        plan_ir: SemanticPlanIR,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Variante de `select_relevant_yamls` que filtra SOLO entidades Gold.

        Reutiliza el mismo retrieval híbrido + governance gate; luego descarta
        cualquier capa no-Gold antes del top_k. Útil como starter minimal del
        flujo 2-pass donde el LLM decide si necesita Silvers adicionales.
        """
        all_docs = self.select_relevant_yamls(
            plan_ir,
            top_k=top_k * 3,  # pedimos más para no quedarnos cortos tras filtrar
            include_bronze=False,
        )
        golds = [d for d in all_docs if (d.get("layer") or "").lower() == "gold"]
        if not golds:
            print(
                "⚠️  [Gold Anchors] retrieval returned 0 Golds — caller should "
                "fall back to full select_relevant_yamls"
            )
        else:
            print(
                f"🥇 [Gold Anchors] {len(golds)} Gold(s) selected: "
                + ", ".join(g["id"] for g in golds[:top_k])
            )
        return golds[:top_k]

    # ── FETCH BY ID (Plan v1 — 2-pass freeform) ──────────────────────────────
    # Cuando el LLM responde con `need_more_context` + lista de entity_ids,
    # este helper trae sus raw_yamls del registry. Valida existencia pero NO
    # impone que estén conectados a los Golds actuales — eso se advierte aguas
    # arriba. Devuelve el mismo shape que `select_relevant_yamls`.
    def fetch_entities_by_ids(
        self,
        entity_ids: list[str],
        include_bronze: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Fetch directo de entities por ID. Salta el ranking y el gate — se
        confía en el LLM para no pedir tablas fuera del scope autoritativo.

        Args:
            entity_ids:      lista de IDs que el LLM pidió en la 1ra pasada.
            include_bronze:  si True, permite ingerir también Bronzes.

        Returns:
            list[dict] mismo shape que `select_relevant_yamls`. IDs no
            encontrados se omiten silenciosamente (con log).
        """
        if not entity_ids:
            return []

        allowed_layers = {"silver", "gold"}
        if include_bronze:
            allowed_layers.add("bronze")

        # El repo se expone a través del retriever (ya existe la conexión).
        repo = self.retriever.repository

        fetched: list[dict[str, Any]] = []
        missing: list[str] = []
        for eid in entity_ids:
            if not eid:
                continue
            try:
                source = repo.get_entity_by_id(eid)
            except Exception as exc:
                print(f"⚠️  [Fetch by ID] lookup failed for '{eid}': {exc}")
                missing.append(eid)
                continue

            if not source:
                missing.append(eid)
                continue

            layer = (source.get("layer") or "").lower()
            if layer not in allowed_layers:
                print(
                    f"⚠️  [Fetch by ID] '{eid}' is layer='{layer}' — "
                    f"not in allowed layers {allowed_layers}"
                )
                missing.append(eid)
                continue

            raw_yaml = source.get("raw_yaml", "") or ""
            if not raw_yaml.strip():
                print(f"⚠️  [Fetch by ID] '{eid}' has no raw_yaml — skipping")
                missing.append(eid)
                continue

            module = source.get("module", "")
            if isinstance(module, list):
                module = ",".join(m for m in module if m)

            fetched.append(
                {
                    "id": source.get("id"),
                    "name": source.get("name"),
                    "layer": layer,
                    "module": module,
                    "entity_role": (source.get("entity_role") or "").lower(),
                    "raw_yaml": raw_yaml,
                    "final_score": 0.0,  # fetched by ID, not ranked
                }
            )

        print(
            f"📥 [Fetch by ID] {len(fetched)}/{len(entity_ids)} entity(s) fetched"
            + (f"; missing: {missing}" if missing else "")
        )
        return fetched
