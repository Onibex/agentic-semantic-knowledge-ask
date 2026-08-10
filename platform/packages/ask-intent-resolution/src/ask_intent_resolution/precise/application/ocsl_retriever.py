from typing import Any


class OCSLHybridRetriever:
    """
    Orquestador de la Fase 2 del Agentic RAG.
    Implementa la arquitectura de 3 etapas: RRF Expansion, Medallion Re-ranking y Governance Injection.
    """

    # Constantes matemáticas del scoring OCSL (post-cleanup 2026-04-21).
    # Se eliminaron MODULE_MATCH_BONUS y ENTITY_HINT_BONUS tras validar que el
    # IR casi nunca emite module_hint (1/9) ni detected_entity_hint útil (3/9);
    # eran decorativos y rompían la jerarquía Gold>Silver cuando aplicaban.
    # El ranking ahora depende de BM25+kNN (normalized) + Medallion tier +
    # priority + role, y el governance gate Gold-first garantiza spec §13.1.
    TIER_BONUS = {"gold": 0.40, "silver": 0.15, "bronze": 0.00}
    PRIORITY_BONUS = {"critical": 0.20, "high": 0.10, "normal": 0.00}
    ROLE_BONUS = {
        "fact": 0.20,
        "reference": 0.05,
        "dimension": 0.00,
    }  # Fact Tables tienen prioridad analitica
    GOLD_CONFIDENCE_THRESHOLD = 0.75

    def __init__(self, repository, embedder):
        self.repository = repository
        self.embedder = embedder

    def get_relevant_documents(
        self,
        query: str,
        has_metrics: bool = True,
        allowed_ids: list | None = None,
    ) -> dict:
        """
        Flujo principal de recuperación.

        Args:
            query:        Texto de la consulta (intent_summary + metrics/dims).
            has_metrics:  True si el IR tiene semantic_metrics. Cuando False
                          (query dimension-only), ROLE_BONUS no se aplica
                          para no penalizar tablas dimension frente a facts.
            allowed_ids:  Workspace scope — restricts the candidate universe to
                          these entity ids (passed through to both OS queries).
                          None = search the whole registry (legacy behaviour).
        """
        # --- STAGE 1: RRF Candidate Expansion ---
        # 1. Generar vector de la pregunta
        query_vec = self.embedder.embed_query(query)

        # 2. Consultas en paralelo (simuladas aqui secuencialmente)
        rrf_hits = self.repository.search_hybrid_rrf(
            query, query_vec, size=50, allowed_ids=allowed_ids
        )
        gold_hits = self.repository.search_gold_rescue(query, size=5, allowed_ids=allowed_ids)

        # 3. Mezclar y deduplicar por ID
        candidates = self._merge_deduplicate(rrf_hits, gold_hits)

        if not candidates:
            return {"mode": "fallback_no_gold", "documents": []}

        # --- STAGE 2: Medallion Re-ranking ---
        candidates = self._normalize_scores(candidates)

        for doc in candidates:
            source = doc["_source"]
            layer = source.get("layer", "silver").lower()
            priority = source.get("anti_hallucination_priority", "normal").lower()
            entity_role = source.get("entity_role", "dimension").lower()

            entity_module = source.get("module", "")
            if isinstance(entity_module, list):
                entity_module = " ".join(entity_module).upper()
            else:
                entity_module = str(entity_module).upper()

            # ROLE_BONUS solo aplica cuando hay métricas — en queries dimension-only
            # no tiene sentido favorecer fact tables sobre dimension tables
            role_bonus = self.ROLE_BONUS.get(entity_role, 0.0) if has_metrics else 0.0

            # Suma de bonos aditivos: normalized BM25+kNN + Medallion tier +
            # data contract priority + analytical role.
            doc["_final_score"] = (
                doc["_normalized"]
                + self.TIER_BONUS.get(layer, 0.0)
                + self.PRIORITY_BONUS.get(priority, 0.0)
                + role_bonus
            )

            print(
                f"📊 [Scoring] {source.get('name')} | "
                f"Base: {doc['_normalized']:.2f} | Final: {doc['_final_score']:.2f} | "
                f"Capa: {layer.upper()} | Rol: {entity_role} | Módulo: {entity_module}"
            )

        # Ordenar por el puntaje final
        reranked = sorted(candidates, key=lambda x: x["_final_score"], reverse=True)

        # --- STAGE 3: Governance gate (spec §13.1 MUST: Gold > Silver) ---
        # Aplica la policy Gold-first. Defensa en profundidad: aunque hoy
        # no hay bonuses aditivos fuertes que puedan invertir la jerarquía
        # Gold>Silver, el gate garantiza el MUST del spec en todas las
        # distribuciones de scores posibles.
        return self._apply_governance_gate(reranked)

    def _apply_governance_gate(self, reranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Gold-first hard gate (spec §13.1). Filtra el ranking según 3 modos,
        preservando el shape `list[doc]` con `_source` intacto para compatibilidad
        con `EntityResolutionService.select_relevant_yamls`.

        Modes:
          - gold_authoritative      — top es Gold con score ≥ GOLD_CONFIDENCE_THRESHOLD:
                                      devolver solo Golds, suprimir Silvers.
          - gold_with_silver_support — top es Gold pero score < threshold:
                                      Golds primero + Silvers de apoyo detrás.
          - fallback_no_gold        — no hay Gold en el ranking:
                                      devolver tal cual (Silvers puros).
        """
        if not reranked:
            return reranked

        golds = [d for d in reranked if (d["_source"].get("layer") or "").lower() == "gold"]

        if not golds:
            raw_top = reranked[0]
            print(
                f"⚠️  [Governance Gate] fallback_no_gold → "
                f"raw_top={raw_top['_source'].get('name')} "
                f"(layer={(raw_top['_source'].get('layer') or '').lower()}, "
                f"score={float(raw_top.get('_final_score', 0.0)):.2f}) — "
                f"no Gold in reranking"
            )
            return reranked

        # El mejor Gold (ya vienen ordenados por _final_score desc dentro de `reranked`).
        best_gold = golds[0]
        best_gold_score = float(best_gold.get("_final_score", 0.0))

        if best_gold_score >= self.GOLD_CONFIDENCE_THRESHOLD:
            # Gold con score alto → modo gold_authoritative: suprimir Silvers,
            # conservar las demás capas no-Silver como tail.
            non_silver_tail = [
                d
                for d in reranked
                if (d["_source"].get("layer") or "").lower() not in ("gold", "silver")
            ]
            print(
                f"🥇 [Governance Gate] gold_authoritative → "
                f"best_gold={best_gold['_source'].get('name')} "
                f"(score={best_gold_score:.2f} ≥ threshold "
                f"{self.GOLD_CONFIDENCE_THRESHOLD}) — "
                f"{len(golds)} Gold(s), Silvers suprimidos"
            )
            return golds + non_silver_tail

        # Gold existe pero no alcanza el umbral → gold_with_silver_support:
        # Gold(s) primero + Silvers de apoyo detrás (para Dijkstra / LLM context).
        non_gold_tail = [d for d in reranked if (d["_source"].get("layer") or "").lower() != "gold"]
        print(
            f"🥈 [Governance Gate] gold_with_silver_support → "
            f"best_gold={best_gold['_source'].get('name')} "
            f"(score={best_gold_score:.2f} < threshold "
            f"{self.GOLD_CONFIDENCE_THRESHOLD}) "
            f"+ {len(non_gold_tail)} support doc(s)"
        )
        return golds + non_gold_tail

    def _merge_deduplicate(self, rrf_hits: list, gold_hits: list) -> list:
        """Deduplica resultados priorizando el score de RRF si existe en ambos."""
        seen = set()
        merged = []

        for hit in rrf_hits:
            seen.add(hit["_id"])
            merged.append(hit)

        for hit in gold_hits:
            if hit["_id"] not in seen:
                # Documento rescatado que no estaba en el top 50
                print(f"🛟 [Gold Rescue Activado] Inyectando: {hit['_source'].get('name')}")
                seen.add(hit["_id"])
                merged.append(hit)

        return merged

    def _normalize_scores(self, candidates: list) -> list:
        """Aplica normalización Min-Max para comprimir los scores al rango [0, 1]."""
        if not candidates:
            return []

        scores = [hit["_score"] for hit in candidates if hit["_score"] is not None]
        if not scores:
            for hit in candidates:
                hit["_normalized"] = 0.0
            return candidates

        max_score = max(scores)
        min_score = min(scores)

        for hit in candidates:
            raw = hit["_score"] or 0.0
            if max_score == min_score:
                hit["_normalized"] = 1.0
            else:
                hit["_normalized"] = (raw - min_score) / (max_score - min_score)

        return candidates

    def _governance_inject(self, reranked: list) -> dict[str, Any]:
        """
        Toma la decisión final de qué enviar al LLM / Dijkstra basado en el umbral de confianza.
        """
        top_doc = reranked[0]
        top_score = top_doc["_final_score"]
        top_layer = top_doc["_source"].get("layer", "").lower()

        response = {
            "mode": "",
            "documents": [],
            "metadata": {"top_score": top_score, "top_layer": top_layer},
        }

        # ESCENARIO 1: Hay un Gold y es perfecto (0 saltos en Dijkstra)
        if top_layer == "gold" and top_score >= self.GOLD_CONFIDENCE_THRESHOLD:
            response["mode"] = "gold_authoritative"
            response["documents"] = [self._format_for_llm(top_doc)]
            print(f"🥇 [Stage 3] {response['mode']} -> Solo {top_doc['_source'].get('name')}")

        # ESCENARIO 2: Hay un Gold, pero el score es bajo. Mandamos Gold + N Silvers
        elif top_layer == "gold":
            response["mode"] = "gold_with_silver_support"

            # Buscamos hasta 4 Silvers de apoyo en el resto del ranking
            silver_support = [
                d for d in reranked[1:] if d["_source"].get("layer", "").lower() == "silver"
            ][:4]

            docs = [self._format_for_llm(top_doc)]
            docs.extend([self._format_for_llm(d) for d in silver_support])

            response["documents"] = docs
            print(
                f"🥈 [Stage 3] {response['mode']} -> {top_doc['_source'].get('name')} + {len(silver_support)} Silvers"
            )

        # ESCENARIO 3 (Tu caso): No hay Gold. Mandamos puras tablas Silver (N Silvers) para armar JOINs
        else:
            response["mode"] = "fallback_no_gold"

            # Tomamos los top 5 mejores Silvers para que Dijkstra tenga piezas de donde armar la ruta
            silvers = [d for d in reranked if d["_source"].get("layer", "").lower() == "silver"][:5]
            response["documents"] = [self._format_for_llm(d) for d in silvers]

            print(
                f"⚠️ [Stage 3] {response['mode']} -> Pasando {len(silvers)} nodos Silver puros a Dijkstra"
            )

        return response

    def _format_for_llm(self, hit: dict) -> dict:
        """
        Prepara el documento. Extrae el key_fields_summary para evitar el Lost-in-the-Middle.
        """
        source = hit["_source"]
        return {
            "id": source.get("id"),
            "layer": source.get("layer"),
            # Enviamos el resumen curado al LLM en lugar del raw_yaml
            "llm_prompt_context": source.get("key_fields_summary", source.get("description")),
            "raw_source": source,  # Lo conservamos por si Dijkstra necesita leer campos estructurados
        }

    def fetch_entity_by_id(self, entity_id: str) -> dict | None:
        """
        Lookup directo de una entidad por su ID semantico en OpenSearch.
        Se usa como fallback garantizado cuando un Silver declarado en las
        relationships del Gold no aparecio en los resultados del retriever kNN.

        Returns:
            Doc formateado igual que los candidatos del retriever, o None si no existe.
        """
        source = self.repository.get_entity_by_id(entity_id)
        if source:
            return {
                "_source": source,
                "_score": 0.0,
                "_normalized": 0.0,
                "_final_score": 0.5,  # Neutro: esta tabla esta por Data Contract, no por semantica
            }
        return None
