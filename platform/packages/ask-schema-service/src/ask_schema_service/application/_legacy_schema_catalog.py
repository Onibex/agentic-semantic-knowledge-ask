# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

from io import StringIO

from langchain_core.prompts import PromptTemplate
from ruamel.yaml import YAML

from ask_intent_resolution.precise.application.ocsl_retriever import OCSLHybridRetriever


def _dump_yaml(data: object) -> str:
    """Serialize a dict to YAML text (ruamel, YAML 1.2). Replaces the old
    ``yaml.dump(data, sort_keys=False, allow_unicode=True)`` — key order kept,
    unicode literal — so the repo uses one YAML library.

    Uses round-trip mode (``rt``) on purpose: ruamel's ``safe`` dumper sorts
    keys, which would reorder the entity dict; ``rt`` preserves insertion order.
    """
    y = YAML(typ="rt")
    y.default_flow_style = False
    y.allow_unicode = True
    y.width = 4096  # keep descriptions on one line (don't wrap at col 80)
    buf = StringIO()
    y.dump(data, buf)
    return buf.getvalue()

SCHEMA_STRICT_PROMPT = PromptTemplate.from_template(
    """You are an expert Data Catalog and SAP Data Dictionary assistant.
The user is asking a question about the database schema or data structure.

We have searched our semantic catalog and found the following exact matching entity for the user's query:
<entity_metadata>
{entity_yaml}
</entity_metadata>

<instructions>
1. Evaluate the user's question and extract the factual answers from the provided <entity_metadata> block.
2. Present the information clearly. It is highly valued if you show both the business semantic alias (like 'Sales Document') AND the technical SAP field details (like 'VBAK.VBELN' or Type 'C10') so the user gets a comprehensive answer.
3. If they ask about relationships or joins, refer to the 'relationships' section of the YAML.
4. DO NOT hallucinate fields or tables that are not in the <entity_metadata>.
5. Format your output nicely using Markdown tables or bold lists to make it readable.
6. Respond in the SAME LANGUAGE the user wrote their question in.
7. If the metadata provided DOES NOT have the answers the user is looking for, state politely that the catalog entry for this entity doesn't contain that specific information.
</instructions>

User Question: {question}
Answer:"""
)

class SchemaCatalogService:
    def __init__(self, embedder, os_repository, llm):
        self.retriever = OCSLHybridRetriever(
            repository=os_repository, embedder=embedder
        )
        self.llm = llm

    def resolve_schema(self, user_query: str, allowed_ids: list | None = None) -> str:
        """
        Retorna la estructura y diccionario de datos de una tabla
        usando los Yaml Contracts almacenados en OpenSearch.

        ``allowed_ids`` (BACKLOG A/D1): workspace scope for the retrieval
        universe — filtered at the SEARCH, not on the output, so an
        out-of-scope entity never transits the LLM prompt. ``None`` =
        unscoped; ``[]`` = match nothing (same contract as
        ``search_hybrid_rrf``).
        """
        import json

        # Step 1: Clean the query to avoid BM25 noise and extract layer hint
        from ask_llm_gateway.infrastructure.response_utils import content_to_text
        from ask_llm_gateway.infrastructure.token_tracker import track_phase
        try:
            prompt = (
                f"You are a query parser. The user wants to find a schema. "
                f"Extract the core entity name (e.g. 'sales order') and the layer ('bronze', 'silver', 'gold', or null). "
                f"Query: '{user_query}'\n"
                f"Return ONLY valid JSON like: {{\"entity_name\": \"...\", \"layer_hint\": \"...\"}}"
            )
            with track_phase("schema_catalog_parse"):
                extraction_res = self.llm.invoke(prompt)
            raw_text = content_to_text(extraction_res).strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]

            target = json.loads(raw_text.strip())
            clean_query = target.get("entity_name") or user_query
            layer_hint = target.get("layer_hint")
            if layer_hint:
                layer_hint = layer_hint.lower()
        except Exception as e:
            print(f"⚠️ Warning: Could not parse intent for schema query, falling back to raw query. {e}")
            clean_query = user_query
            layer_hint = None

        print(f"🗂 [SchemaCatalogService] Clean Search: '{clean_query}' | Exact Layer: {layer_hint}")

        # Step 2: Retrieve candidates
        try:
            # We use raw Semantic Hybrid Search (RRF) for 1:1 impartial dictionary lookups
            query_vec = self.retriever.embedder.embed_query(clean_query)
            raw_candidates = self.retriever.repository.search_hybrid_rrf(
                clean_query, query_vec, size=15, allowed_ids=allowed_ids
            )

            candidates = []
            for c in raw_candidates:
                src = c.get("_source", {})
                c_layer = src.get("layer", "").lower()
                c_score = c.get("_score", 0)

                # Masive boost if the user explicitly requested a layer
                if layer_hint and c_layer == layer_hint:
                    c["_boosted_score"] = c_score + 10.0
                else:
                    c["_boosted_score"] = c_score
                candidates.append(c)

            candidates = sorted(candidates, key=lambda x: x["_boosted_score"], reverse=True)

            if candidates:
                for c in candidates[:3]:
                    src = c.get("_source", {})
                    print(f"📊 [Schema Match] {src.get('name')} | Layer: {src.get('layer', '').upper()} | Score: {c.get('_boosted_score', 0):.4f}")

        except Exception as e:
            print(f"Error recuperando documentos para schema: {e}")
            return "An error occurred while querying the data catalog."

        if not candidates:
            return "Could not find any entity or table in the catalog matching your search."

        # Step 3: Extract top document's raw YAML structure
        winner = candidates[0]
        source = winner.get("_source", {})
        layer = source.get('layer', 'Unknown')
        name = source.get('name', 'Unknown')

        print(f"🗂 [SchemaCatalogService] Winner Entity: {name} (Layer: {layer}) | Score: {winner.get('_score', 0):.4f}")

        raw_yaml = source.get("raw_yaml", "")

        if not raw_yaml:
            # Fallback if raw_yaml was not dumped intact
            safe_source = {
                "id": source.get("id"),
                "name": source.get("name"),
                "layer": source.get("layer"),
                "description": source.get("description"),
                "fields": source.get("fields", []),
                "relationships": source.get("relationships", [])
            }
            raw_yaml = _dump_yaml(safe_source)

        # Step 3: Invoke LLM Generation using strict contextual prompt
        prompt_val = SCHEMA_STRICT_PROMPT.format(
            entity_yaml=raw_yaml,
            question=user_query
        )

        with track_phase("schema_catalog_answer"):
            response = self.llm.invoke(prompt_val)
        return content_to_text(response)
