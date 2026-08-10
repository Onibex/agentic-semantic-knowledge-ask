from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field


class MappedField(BaseModel):
    semantic_term: str = Field(
        description="El término semántico explícito que se solicitó (ej. 'revenue', 'created on')"
    )
    physical_column_name: str = Field(
        description="El name exacto de la columna física en el esquema disponible"
    )
    physical_node_id: str = Field(
        description="El internal_id o node_id de la tabla a la que pertenece la columna"
    )


class FieldMappingResponse(BaseModel):
    mappings: list[MappedField] = Field(
        description="Lista de mapeos 1 a 1 de término semántico a columna física"
    )
    unmapped_terms: list[str] = Field(
        default_factory=list,
        description="Semantic terms that could NOT be mapped to any physical column — explicitly rejected after evaluation",
    )


class SemanticFieldMapperService:
    def __init__(self, llm):
        self.parser = PydanticOutputParser(pydantic_object=FieldMappingResponse)

        system_prompt = """You are an expert Data Architect mapping semantic business queries to physical database schemas.
Your task is to take a list of 'Semantic Terms' requested by the user, and map each one strictly to the MOST logical 'Physical Column' from the provided 'Available Schema'.

CRITICAL RULES:
1. Provide exactly ONE physical column and its corresponding physical_node_id for each semantic term.
2. Resolve synonyms (e.g. 'client' -> 'customer'), translations (Spanish to English), abbreviations ('req qty' -> 'requested quantity'), and semantic variations ('created on' -> 'order_date').
3. Strict Role Matching:
   - A term expecting 'measure' MUST map to a field with role 'measure'.
   - A term expecting 'dimension' MUST map to a field with role 'dimension' or 'identifier'.
   - A term expecting 'timestamp' MUST map to a field with role 'timestamp'.
4. ZERO HALLUCINATION RULE: If there is NO logical, business-appropriate corresponding column for a semantic term in the provided Available Schema (e.g. searching for 'revenue' but only 'quantity' exists), you MUST:
   a) OMIT that term from your 'mappings' list entirely. Do NOT force a wrong mapping.
   b) ADD the term to the 'unmapped_terms' list so the system knows it was explicitly evaluated and rejected.
   Every input semantic term MUST appear in EXACTLY ONE of the two lists: either in 'mappings' OR in 'unmapped_terms'. No term should be silently dropped.
5. If there is ambiguity (e.g. multiple dates), pick the one that best fits the exact verb ('created' -> creation date, 'delivered' -> delivery date). If still ambiguous, pick the most generic primary date.
6. TABLE COHESION RULE: When measure terms are present, prefer dimension columns from the same node_id that holds the measure mappings (the Fact Table). Only resolve a dimension to a different node_id if the field does NOT exist in the Fact Table at all. When NO measure terms are present (all terms are dimensions), this rule does not apply.
7. ENTITY AFFINITY RULE: Each field includes an 'entity_role' (fact, dimension, or reference) indicating the purpose of its parent table. When ALL semantic terms have expected_role='dimension' (no measures requested), PREFER fields from nodes with entity_role='dimension' — these are master data tables purpose-built for descriptive attributes. Only fall back to fact/reference entities if no dimension entity has the requested field.

{format_instructions}
"""
        user_prompt = """AVAILABLE SCHEMA (Candidate Tables):
{schema_context}

SEMANTIC TERMS TO MAP:
{semantic_terms}

Map each semantic term to its best physical column following the rules above."""
        self.prompt = ChatPromptTemplate.from_messages(
            [("system", system_prompt), ("human", user_prompt)]
        )
        self.chain = self.prompt | llm | self.parser

    def map_fields(
        self,
        candidate_fields: list[dict[str, Any]],
        terms_to_map: list[dict[str, str]],
    ) -> tuple:
        """
        Mapea términos semánticos a columnas físicas usando el LLM como juez.

        Returns:
            tuple(dict, list):
                - mappings: { semantic_term: {"column": str, "node": str} }
                - unmapped_terms: [str] — términos que el LLM no pudo resolver
        """
        if not terms_to_map or not candidate_fields:
            return {}, []

        # 1. Compactar el esquema a enviar (con entity_role para Rule 7)
        schema_lines = []
        for f in candidate_fields:
            schema_lines.append(
                f"- node_id: '{f.get('node_id')}', entity_role: '{f.get('entity_role', '')}', "
                f"name: '{f.get('name')}', role: '{f.get('field_role')}', "
                f"type: '{f.get('type')}', desc: '{f.get('description', '')}'"
            )
        schema_context = "\n".join(schema_lines)

        # 2. Compactar términos
        terms_lines = []
        for t in terms_to_map:
            terms_lines.append(f"- Term: '{t['term']}', Expected Role: '{t['expected_role']}'")
        terms_context = "\n".join(terms_lines)

        # 3. Construir lookup de columnas válidas por node_id para post-validación
        valid_columns = {}  # node_id -> set of column names
        prefix_index = {}  # node_id -> { prefix -> column_name }
        for f in candidate_fields:
            nid = f.get("node_id")
            col = f.get("name")
            if not nid or not col:
                continue
            valid_columns.setdefault(nid, set()).add(col)
            # Indexar por prefijo (antes del último '_') para corrección de sufijo
            # ej. 'werks_vbap' -> prefix 'werks' -> 'werks_vbap'
            parts = col.rsplit("_", 1)
            if len(parts) == 2:
                prefix_index.setdefault(nid, {}).setdefault(parts[0], []).append(col)

        # 4. Invocar Cadena
        from ask_llm_gateway.infrastructure.token_tracker import track_phase

        with track_phase("field_mapping"):
            response = self.chain.invoke(
                {
                    "schema_context": schema_context,
                    "semantic_terms": terms_context,
                    "format_instructions": self.parser.get_format_instructions(),
                }
            )

        # 5. Post-validación: corregir columnas alucinadas por el LLM
        mappings = {}
        unmapped = list(response.unmapped_terms)
        for m in response.mappings:
            col = m.physical_column_name
            nid = m.physical_node_id
            node_cols = valid_columns.get(nid, set())

            if col in node_cols:
                # Columna existe tal cual — mapping válido
                mappings[m.semantic_term] = {"column": col, "node": nid}
            else:
                # LLM alucinó el nombre — intentar corrección por prefijo
                prefix = col.rsplit("_", 1)[0] if "_" in col else col
                candidates = prefix_index.get(nid, {}).get(prefix, [])
                if len(candidates) == 1:
                    corrected = candidates[0]
                    print(
                        f"🔧 [Field Mapper] Auto-corrected '{col}' → '{corrected}' "
                        f"(LLM hallucinated suffix for node '{nid}')"
                    )
                    mappings[m.semantic_term] = {"column": corrected, "node": nid}
                else:
                    print(
                        f"⚠️  [Field Mapper] Column '{col}' does not exist in node '{nid}' "
                        f"— moved to unmapped"
                    )
                    unmapped.append(m.semantic_term)

        return mappings, unmapped
