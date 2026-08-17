"""
ask_knowledge_graph.application.rag_text_renderer
─────────────────────────────────────────────────────────────────────────────
Render an ASK Spec YAML (Bronze / Silver / Gold) into a human-readable text
optimized for embedding + retrieval against the `rag_schema` collection.

Why this lives here
─────────────────────
The KG package already owns the YAML parser, the typed node models
(BronzeNode / SilverNode / GoldNode) and the catalog writer.
Producing the "embedding text" view of those same YAMLs is a peer concern:
both branches of the unified ingest endpoint (catalog + RAG) start from the
same YAML, so the projection from YAML → embedding-text belongs next to the
projection from YAML → catalog node.

Output shape
─────────────
Each renderer returns ``(text, metadata)`` where:
  - ``text``     : a multi-line string with stable section markers
                   (``\\n\\nFIELDS\\n``, ``\\n\\nRELATIONSHIPS\\n``) so the
                   `RecursiveCharacterTextSplitter` in `rag_chunking` can
                   split on semantic boundaries.
  - ``metadata`` : a dict suitable for OpenSearch filtering — keys mirror
                   the legacy `utils/yaml_data_product.py` output where it
                   makes sense (table_name, layer, sap_module, measures,
                   dimensions, identifiers, timestamps, related_tables) so
                   admin search filters keep working.
"""

from __future__ import annotations

from typing import Any

from ..infrastructure.yaml_serializer import load_yaml_text

__all__ = [
    "render_yaml_for_embedding",
    "render_node_for_embedding",
]


# ─────────────────────────────────────────────────────────────────────────────
# Public entrypoints
# ─────────────────────────────────────────────────────────────────────────────
def render_yaml_for_embedding(yaml_content: str) -> tuple[str, dict[str, Any]]:
    """Parse YAML text and return (embedding_text, metadata).

    Raises ``ValueError`` if the layer is missing or unsupported.
    """
    raw = load_yaml_text(yaml_content) or {}
    if not isinstance(raw, dict):
        raise ValueError("YAML root is not a mapping")
    return render_node_for_embedding(raw)


def render_node_for_embedding(raw: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Same as :func:`render_yaml_for_embedding` but starts from a parsed dict.

    Useful when the YAML has already been loaded (e.g. by the IngestionService
    upstream) and we want to avoid re-parsing the string.
    """
    layer = str(raw.get("layer") or raw.get("medallion_layer") or "").strip().lower()
    if layer == "bronze":
        return _render_bronze(raw)
    if layer == "silver":
        return _render_silver(raw)
    if layer == "gold":
        return _render_gold(raw)
    raise ValueError(f"Unsupported or missing layer in YAML: {layer!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Layer-specific renderers
# ─────────────────────────────────────────────────────────────────────────────
def _render_bronze(raw: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    entity_id = str(raw.get("id", ""))
    name = str(raw.get("name", entity_id))
    alias = str(raw.get("alias", ""))
    description = str(raw.get("description", "") or "")
    primary_key = list(raw.get("primary_key") or [])
    fields_dict: dict[str, Any] = raw.get("fields") or {}

    field_lines: list[str] = []
    identifiers: list[str] = []
    measures: list[str] = []
    dimensions: list[str] = []
    timestamps: list[str] = []

    for col_name, fdef in fields_dict.items():
        f = fdef if isinstance(fdef, dict) else {}
        ftype = str(f.get("type", "") or "")
        falias = str(f.get("alias", "") or "")
        fdesc = str(f.get("description", "") or "")
        is_key = bool(f.get("key_field", False))

        role = "identifier" if is_key else _infer_bronze_role(falias, fdesc)
        bucket = {
            "identifier": identifiers,
            "measure": measures,
            "timestamp": timestamps,
        }.get(role, dimensions)
        bucket.append(falias or col_name)

        parts = [f"  - {col_name}"]
        if ftype:
            parts.append(f"({ftype})")
        if falias and falias != col_name:
            parts.append(f"alias:{falias}")
        if is_key:
            parts.append("[key]")
        if fdesc:
            parts.append(f"— {fdesc}")
        field_lines.append(" ".join(parts))

    text_parts = [
        f"DATA PRODUCT: {name}",
        f"Table: {entity_id}",
        "Layer: bronze",
        f"Source system: {raw.get('source_system', '')}",
    ]
    if alias:
        text_parts.append(f"Alias: {alias}")
    if description:
        text_parts.append(f"Description: {description}")
    if primary_key:
        text_parts.append(f"Primary key: {', '.join(primary_key)}")
    if field_lines:
        text_parts.append("\nFIELDS:\n" + "\n".join(field_lines))

    metadata = {
        "doc_type": "yaml_data_product",
        "ingestion_type": "yaml_data_product",
        "entity_id": entity_id,
        "data_product_name": name,
        "table_name": entity_id,
        "layer": "bronze",
        "grain": "transactional",
        "sap_module": "",
        "version": str(raw.get("version", "v1.0")),
        "measures": measures,
        "dimensions": dimensions,
        "identifiers": identifiers,
        "timestamps": timestamps,
        "related_tables": [],
        "is_dashboard_ready": False,
        "business_certified": False,
        "priority": 3,
        "field_count": len(fields_dict),
    }
    return "\n".join(text_parts), metadata


def _render_silver(raw: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return _render_silver_or_gold(raw, layer_label="silver")


def _render_gold(raw: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return _render_silver_or_gold(raw, layer_label="gold")


def _render_silver_or_gold(raw: dict[str, Any], *, layer_label: str) -> tuple[str, dict[str, Any]]:
    entity_id = str(raw.get("id", ""))
    name = str(raw.get("name", entity_id))
    description = str(raw.get("description", "") or "")
    table_name = str(raw.get("db_table_name") or entity_id)

    sap_module = _stringify_module(raw.get("module"))
    business_process = str(raw.get("business_process", "") or "")
    entity_role = str(raw.get("entity_role", "") or "")
    grain = _stringify_grain(raw.get("grain"))

    fields = list(raw.get("fields") or [])
    measures: list[str] = []
    dimensions: list[str] = []
    identifiers: list[str] = []
    timestamps: list[str] = []
    field_lines: list[str] = []

    for f in fields:
        if not isinstance(f, dict):
            continue
        fname = str(f.get("name", "") or "")
        if not fname:
            continue
        role = str(f.get("field_role", "dimension") or "dimension").lower()
        ftype = str(f.get("type", "") or "")
        fdesc = str(f.get("description", "") or "")
        agg = str(f.get("aggregation_behavior", "") or "")
        # Axis 2 — the function alone is ambiguous in retrieval text: "agg:SUM"
        # reads as freely summable even when it is only valid after collapsing a
        # dimension. See REQ_ADDITIVITY_CONTRACT.md.
        additivity = str(f.get("additivity", "") or "")
        non_additive_over = [str(d) for d in (f.get("non_additive_over") or [])]

        if role == "measure":
            measures.append(fname)
        elif role in ("identifier", "key"):
            identifiers.append(fname)
        elif role == "timestamp":
            timestamps.append(fname)
        else:
            dimensions.append(fname)

        parts = [f"  - {fname}"]
        if ftype:
            parts.append(f"({ftype})")
        if role:
            parts.append(f"[{role}]")
        if agg:
            parts.append(f"agg:{agg}")
        if additivity == "semi_additive":
            # Not "time": since v2 the dimensions may be structural rather than
            # temporal, and this string is EMBEDDED text — a wrong token here is a
            # wrong vector, not just a wrong sentence.
            over = ",".join(non_additive_over) or "declared"
            parts.append(f"semi-additive(collapse:{over})")
        elif additivity == "non_additive":
            parts.append("non-additive")
        if fdesc:
            parts.append(f"— {fdesc}")
        # Alternative business names. This text is what gets embedded and chunked
        # for Flash, so a synonym absent from here cannot widen retrieval — the only
        # thing the key is documented to do.
        synonyms = [str(s).strip() for s in (f.get("synonyms") or []) if str(s).strip()]
        if synonyms:
            parts.append(f"(aka: {', '.join(synonyms)})")
        field_lines.append(" ".join(parts))

    # Two relationship surfaces in ASK Spec: `join_graph` (physical INNER/LEFT
    # joins between member tables) and `relationships` (semantic edges to
    # other entities). Both feed the embedding text — they capture different
    # search intents ("how do tables join?" vs "what entities relate to this?").
    rel_lines: list[str] = []
    related_tables: list[str] = []
    for j in raw.get("join_graph") or []:
        if not isinstance(j, dict):
            continue
        lt = str(j.get("left_table", "") or "")
        rt = str(j.get("right_table", "") or "")
        jt = str(j.get("join_type", "JOIN") or "JOIN")
        cond = str(j.get("condition", "") or "")
        if not (lt and rt):
            continue
        rel_lines.append(f"  {jt} {lt} -> {rt}" + (f" ON {cond}" if cond else ""))
    for r in raw.get("relationships") or []:
        if not isinstance(r, dict):
            continue
        target = str(r.get("target_entity", "") or "")
        if not target:
            continue
        related_tables.append(target)
        rtype = str(r.get("relationship_type", "REL") or "REL")
        cond = str(r.get("join_condition", "") or "")
        label = str(r.get("semantic_label", "") or "")
        line = f"  {rtype} {target}"
        if cond:
            line += f" ON {cond}"
        if label:
            line += f"  — {label}"
        rel_lines.append(line)

    text_parts = [
        f"DATA PRODUCT: {name}",
        f"Table: {table_name}",
        f"Layer: {layer_label} | Grain: {grain}",
    ]
    if entity_role:
        text_parts.append(f"Entity role: {entity_role}")
    if sap_module:
        text_parts.append(f"SAP Module: {sap_module}")
    if business_process:
        text_parts.append(f"Business process: {business_process}")
    if description:
        text_parts.append(f"Description: {description}")
    if identifiers:
        text_parts.append(f"Identifiers (keys): {', '.join(identifiers)}")
    if measures:
        text_parts.append(f"Measures: {', '.join(measures)}")
    if dimensions:
        text_parts.append(f"Dimensions: {', '.join(dimensions)}")
    if timestamps:
        text_parts.append(f"Timestamps: {', '.join(timestamps)}")
    if field_lines:
        text_parts.append("\nFIELDS:\n" + "\n".join(field_lines))
    if rel_lines:
        text_parts.append("\nRELATIONSHIPS:\n" + "\n".join(rel_lines))

    metadata = {
        "doc_type": "yaml_data_product",
        "ingestion_type": "yaml_data_product",
        "entity_id": entity_id,
        "data_product_name": name,
        "table_name": table_name,
        "layer": layer_label,
        "grain": grain,
        "sap_module": sap_module,
        "version": str(raw.get("version", "v1.0")),
        "entity_role": entity_role,
        "measures": measures,
        "dimensions": dimensions,
        "identifiers": identifiers,
        "timestamps": timestamps,
        "related_tables": related_tables,
        "is_dashboard_ready": layer_label == "gold",
        "business_certified": layer_label == "gold",
        "priority": 1 if layer_label == "gold" else 2,
        "field_count": len(fields),
    }
    return "\n".join(text_parts), metadata


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _stringify_module(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value or "")


def _stringify_grain(value: Any) -> str:
    if isinstance(value, dict):
        entity_grain = value.get("entity_grain")
        business_grain = value.get("business_grain")
        parts: list[str] = []
        if isinstance(entity_grain, list) and entity_grain:
            parts.append("entity_grain=[" + ", ".join(str(g) for g in entity_grain) + "]")
        elif entity_grain:
            parts.append(f"entity_grain={entity_grain}")
        if business_grain:
            parts.append(f"business_grain={business_grain}")
        return "; ".join(parts) if parts else "transactional"
    return str(value or "transactional")


def _infer_bronze_role(alias: str, description: str) -> str:
    """Best-effort role inference for Bronze fields (no field_role in spec).

    Bronze fields don't carry a `field_role` — they're raw SAP columns. We
    use the alias + description as weak signals to bucket them into
    measure / timestamp / dimension so the metadata stays useful for filters.
    Identifiers come from the explicit `key_field=True` flag, not from here.
    """
    text = f"{alias} {description}".lower()
    if any(t in text for t in _TIMESTAMP_SIGNALS):
        return "timestamp"
    if any(t in text for t in _MEASURE_SIGNALS):
        return "measure"
    return "dimension"


# Signals are matched against alias + description, so they must cover the
# language the layer is AUTHORED in (ASK_SEMANTIC_LANGUAGE). The list carried
# `fecha` but no other Spanish word, so on a Spanish-authored corpus every
# measure fell through to `dimension` — asymmetric by accident, not by design.
_TIMESTAMP_SIGNALS = (
    # English
    "date",
    "time",
    "timestamp",
    "created",
    "changed",
    # Spanish
    "fecha",
    "hora",
    "creado",
    "modificado",
    "periodo",
)

_MEASURE_SIGNALS = (
    # English
    "amount",
    "value",
    "qty",
    "quantity",
    "price",
    "net",
    "gross",
    "weight",
    "volume",
    # Spanish
    "importe",
    "valor",
    "cantidad",
    "precio",
    "monto",
    "peso",
    "volumen",
    "neto",
    "bruto",
    "total",
)
