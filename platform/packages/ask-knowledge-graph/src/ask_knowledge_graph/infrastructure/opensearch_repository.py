# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
OpenSearchAskRepository — full read+write surface over the 4 ask-* indices.

⚠️  Iter 4 deprecation note (read methods only)
─────────────────────────────────────────────────
The READ methods on this class are now also exposed through the typed
KnowledgeGraphReader Protocol in:

    packages/ask-knowledge-graph/src/ask_knowledge_graph/infrastructure/opensearch_reader.py

New code in `packages/` MUST consume reads via that Protocol — enforced by
.importlinter. The class itself stays intact:
  - Iter 4 strategies (SmartStrategy) wrap an instance via
    OpenSearchKnowledgeGraphReader(legacy_repo).
  - The legacy v1 ask_graph and pipeline_v2 services keep using this class
    directly until their iterations land.
  - Ingestion / write methods (save_*, delete_*) are owned by Iter 6
    (Knowledge Graph write side); they stay on this class until then.

The class will be split in Iter 6 (read pieces deleted, write pieces moved
into the dedicated ingestion package).
"""

import logging
import os
import re
from typing import Any

from opensearchpy import OpenSearch, helpers

from ._legacy_config import ConfigManager
from .env_index import env_index

# from domain.entities import BronzeNode, SilverNode  # Importaciones de tu dominio

logger = logging.getLogger(__name__)


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


# ─────────────────────────────────────────────────────────────────────────────
# Edge-document construction
#
# ONE builder, used by both `save_silver_node` and `save_gold_node`. It used to be
# three verbatim copies (the third, `_index_silver_edges`, had zero callers and was
# deleted) — which is how the index mapping and the writer drifted apart in the
# first place: a fix applied to one copy silently left the others behind.
# ─────────────────────────────────────────────────────────────────────────────

# Longest-first so `>=` / `<=` / `<>` / `!=` are not split as `>` / `<` / `!` with
# the `=` left dangling in the right-hand operand.
_COMPARISON_RE = re.compile(r"(>=|<=|<>|!=|=|>|<)")

# A table qualifier: the IDENT in `IDENT.column`. Numeric literals like `1.5` do not
# match (an identifier cannot start with a digit), and quoted literals such as
# `'Purchase Order'` contain no dot at all.
_QUALIFIER_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*[A-Za-z_][A-Za-z0-9_]*")

_FAN_OUT_CARDINALITIES = ("one_to_many", "many_to_many")

_REVERSE_CARDINALITY_MAP = {
    "one_to_many": "many_to_one",
    "many_to_one": "one_to_many",
    "many_to_many": "many_to_many",
    "one_to_one": "one_to_one",
}


def _extract_qualifiers(predicate: str) -> list[str]:
    """Distinct table qualifiers in a join predicate, in order of first appearance."""
    seen: dict[str, None] = {}
    for match in _QUALIFIER_RE.finditer(predicate or ""):
        seen.setdefault(match.group(1), None)
    return list(seen)


def _parse_simple_condition(predicate: str) -> list[dict[str, str]]:
    """Structured `conditions[]` — ONLY for a single, simple comparison.

    Anything else (multi-key `AND`, `IN (...)`, `BETWEEN`, ...) returns `[]` and is
    carried by `join_predicate` instead. The previous behaviour was to fabricate one
    condition holding the ENTIRE predicate as `left_field` with an empty
    `right_field`; the renderer then emitted `ON "<whole predicate>" = ""` under an
    "authoritative, do not invent" heading. 8 of 34 live edge documents were in that
    state — every Gold->Gold and Gold->Silver lineage edge. An empty list is honest:
    the caller falls back to `join_predicate`.
    """
    if not predicate:
        return []
    parts = _COMPARISON_RE.split(predicate)
    if len(parts) != 3:
        return []
    left, operator, right = (p.strip() for p in parts)
    if not left or not right:
        return []
    return [{"left_field": left, "right_field": right, "operator": operator}]


def _derive_reverse_safety(forward_safety: str, reverse_cardinality: str) -> str:
    """`aggregation_safety` for the auto-generated reverse edge.

    NOT a copy of the forward value. Fan-out is directional: if A --one_to_many--> B
    multiplies rows on A's side, the reverse B --many_to_one--> A does not multiply
    anything, so copying `requires_dedup` onto it would make the model dedup for no
    reason. The reverse edge is derived, not authored, so its default is derived the
    same way the authoring surfaces derive theirs — from its own cardinality.

    `unsafe` is the exception: a structurally broken join is broken both ways.
    """
    if forward_safety == "unsafe":
        return "unsafe"
    return "requires_dedup" if reverse_cardinality in _FAN_OUT_CARDINALITIES else "safe"


def _build_edge_pair(node: Any, rel: Any) -> list[tuple[str, dict[str, Any]]]:
    """Build the (doc_id, _source) pairs for one authored relationship.

    Returns the forward edge and its auto-generated reverse edge.
    """
    predicate = (getattr(rel, "join_condition", "") or "").strip()
    conditions = _parse_simple_condition(predicate)

    source_table = (getattr(node, "db_table_name", None) or node.id or "").strip()
    qualifiers = _extract_qualifiers(predicate)

    # SILVER §7.3.1 / GOLD §6.3.1: a join_condition names exactly two tables — this
    # entity's db_table_name and the target's — and nothing else. Verified here
    # because this is the last point that still holds the authored node; violations
    # are LOGGED, never fatal (a bad qualifier must not stop an ingestion).
    upper_quals = {q.upper() for q in qualifiers}
    own_side_qualified = not (source_table and qualifiers) or source_table.upper() in upper_quals
    if not own_side_qualified:
        logger.warning(
            "Qualifier contract: edge %s -> %s does not qualify its own side. "
            "Expected db_table_name %r among %s. Predicate: %s",
            node.id,
            rel.target_entity,
            source_table,
            sorted(upper_quals),
            predicate,
        )
    if len(upper_quals) > 2:
        logger.warning(
            "Qualifier contract: edge %s -> %s names %d tables (expected 2): %s",
            node.id,
            rel.target_entity,
            len(upper_quals),
            sorted(upper_quals),
        )

    # The other side's physical table, read off the predicate rather than looked up:
    # the target entity may not be indexed yet at this point, and by the contract
    # above the predicate already carries it.
    #
    # Gated on the contract actually holding, because otherwise this derivation FAILS
    # OPEN in the one case the check above just detected. When both qualifiers are
    # entity ids (an AI-suggested edge authored while `db_table_name` still held its
    # id default), neither matches `source_table`, so `next()` returns the FIRST one —
    # the source's own id — and the consumer renders `target (table: <source id>)`:
    # actively wrong rather than merely absent. Emitting "" instead degrades
    # `_format_edges_hint._qualified` to the bare entity id, which is honest.
    target_table = (
        next((q for q in qualifiers if q.upper() != source_table.upper()), "")
        if own_side_qualified
        else ""
    )

    forward_safety = getattr(rel, "aggregation_safety", "safe") or "safe"
    cardinality = rel.relationship_type
    reverse_cardinality = _REVERSE_CARDINALITY_MAP.get(cardinality, "one_to_many")
    description = getattr(rel, "description", None)
    cross_module = bool(getattr(rel, "cross_module", False))

    forward = {
        "source_node": node.id,
        "target_node": rel.target_entity,
        # Physical tables of each side, so the consumer never has to infer that
        # `gold_s4h_inventory_situation` and `GOLD_INVENTORY_SITUATION` are the same
        # object — the entity id and the db_table_name differ by more than case.
        "source_table": source_table,
        "target_table": target_table,
        "join_type": "LEFT OUTER",
        "conditions": conditions,
        # The authored predicate, verbatim. Authoritative whenever `conditions` is
        # empty, and always safe to render as-is.
        "join_predicate": predicate,
        "cardinality": cardinality,
        "traversal_cost": rel.traversal_cost,
        "aggregation_safety": forward_safety,
        # Carries the §7.4/§6.5 grain warning the curator wrote. Dropped by every
        # builder until now, so that warning reached no prompt unless the whole
        # entity YAML happened to be retrieved as an anchor.
        "description": description,
        "is_reverse": False,
        "semantic_label": rel.semantic_label,
        "cross_module": cross_module,
    }

    reverse = {
        "source_node": rel.target_entity,
        "target_node": node.id,
        "source_table": target_table,
        "target_table": source_table,
        "join_type": "RIGHT OUTER",
        "conditions": [
            {
                "left_field": c["right_field"],
                "right_field": c["left_field"],
                "operator": c["operator"],
            }
            for c in conditions
        ],
        # Same predicate: it is a symmetric SQL expression, so it does not need
        # rewriting for the reverse direction.
        "join_predicate": predicate,
        "cardinality": reverse_cardinality,
        "traversal_cost": rel.traversal_cost,
        "aggregation_safety": _derive_reverse_safety(forward_safety, reverse_cardinality),
        "description": description,
        "is_reverse": True,
        "semantic_label": f"reverse_of_{rel.semantic_label}",
        "cross_module": cross_module,
    }

    return [
        (f"edge_{node.id}_to_{rel.target_entity}".lower(), forward),
        (f"edge_{rel.target_entity}_to_{node.id}_reverse".lower(), reverse),
    ]


def _opensearch_kwargs(os_cfg: dict) -> dict:
    """Env-first OpenSearch client kwargs (OPENSEARCH_*), settings.json fallback.

    Mirrors ask_llm_gateway.infrastructure.secrets.repository — env vars win so
    this survives the cleanup that strips ``opensearch`` from settings.json.
    """
    host = os.getenv("OPENSEARCH_HOST")
    port_env = os.getenv("OPENSEARCH_PORT")
    use_ssl_env = os.getenv("OPENSEARCH_USE_SSL")
    username = os.getenv("OPENSEARCH_USER") or None
    password = os.getenv("OPENSEARCH_PASSWORD") or None

    if not host:
        host = os_cfg.get("host", "localhost")
        port = int(port_env or os_cfg.get("port", 9200))
        use_ssl = (
            bool(os_cfg.get("use_ssl", False)) if use_ssl_env is None else _truthy(use_ssl_env)
        )
        username = username or os_cfg.get("username") or None
        password = password or os_cfg.get("password") or None
        verify_certs = bool(os_cfg.get("verify_certs", False))
    else:
        port = int(port_env or 9200)
        use_ssl = _truthy(use_ssl_env or "")
        verify_certs = _truthy(os.getenv("OPENSEARCH_VERIFY_CERTS", ""))

    kwargs: dict = {
        "hosts": [{"host": host, "port": port}],
        "use_ssl": use_ssl,
        "verify_certs": verify_certs,
        "ssl_show_warn": False,
    }
    if username and password:
        kwargs["http_auth"] = (username, password)
    return kwargs


# ── Text analysis: one analyzer for every searched text field ────────────────
#
# WHY A CUSTOM ANALYZER (PLAN_SEMANTIC_LANGUAGE.md W3): every text field used to
# declare `analyzer: "english"`, and no index declared an `analysis` block at
# all. Two consequences, both silent:
#
#   1. NO ACCENT FOLDING anywhere. An indexed `crédito` and a queried `credito`
#      are different terms, so BM25 returns nothing — and most people type
#      without accents. At FIELD level that decides resolution outright, because
#      field matching is BM25-only (`search_best_field` has no usable vector).
#   2. Spanish text ran through the ENGLISH Porter stemmer + English stopwords.
#
# Built-in language analyzers cannot be extended with an extra filter, so the
# chain is spelled out here. `asciifolding` sits BEFORE the stemmer: the stemmer
# is fed the folded form, so `crédito` and `credito` reduce to the same stem
# rather than to two. `preserve_original` is deliberately NOT set — keeping the
# accented variant would re-split the term and defeat the point.
#
# The STORED value never changes: analysis only affects inverted-index terms, so
# the UI, the prompts and the YAML keep their correct spelling. Normalize for
# matching, preserve for reading.
_ASK_TEXT_ANALYZER = "ask_text"

# Per-language stopword + stemmer names (OpenSearch built-in filter names).
_LANGUAGE_FILTERS: dict[str, tuple[str, str]] = {
    "en": ("_english_", "english"),
    "es": ("_spanish_", "light_spanish"),
}


def _text_analysis_settings(language: str) -> dict:
    """The ``analysis`` block for a searched-text index in ``language``.

    ``light_spanish`` over ``spanish``: the aggressive Snowball Spanish stemmer
    conflates business terms that must stay distinct (it truncates hard), while
    the light variant only strips inflection — the right trade-off for a semantic
    layer whose terms are nouns, not prose.
    """
    stop_name, stemmer_name = _LANGUAGE_FILTERS.get(
        (language or "en").lower(), _LANGUAGE_FILTERS["en"]
    )
    return {
        "filter": {
            "ask_stop": {"type": "stop", "stopwords": stop_name},
            "ask_stemmer": {"type": "stemmer", "language": stemmer_name},
        },
        "analyzer": {
            _ASK_TEXT_ANALYZER: {
                "type": "custom",
                "tokenizer": "standard",
                "filter": ["lowercase", "asciifolding", "ask_stop", "ask_stemmer"],
            }
        },
    }


class OpenSearchAskRepository:
    def __init__(self, env: str | None = None):
        """
        Inicializa el cliente de OpenSearch.
        Idealmente, estas credenciales vienen de variables de entorno o de tu ConfigManager.

        ``env`` (UX_CHANGES audit CH-2, Iter 2): when set to ``"dev"``/``"prod"``
        every registry index name is suffixed (``ask-entity-registry-v1-dev``).
        ``None`` (the default) keeps the legacy un-suffixed names so existing
        callers and the running read path are unaffected.
        """
        config_manager = ConfigManager()
        # `load_config()` returns None when config/settings.json is absent (it is
        # gitignored, so a fresh clone has none). Without `or {}` that None
        # reached `.get()` below and surfaced as
        # "'NoneType' object has no attribute 'get'" on unrelated endpoints —
        # e.g. GET /v1/admin/yaml/published-ids (BACKLOG group 0, P1).
        config = config_manager.load_config() or {}

        # Env-first (OPENSEARCH_*) with settings.json fallback.
        os_cfg = config.get("opensearch") or {}
        kwargs: dict = _opensearch_kwargs(os_cfg)
        # Larger connection pool — the default behaves as size 1 here and
        # churns connections under concurrent reads. settings.json
        # opensearch.pool_maxsize overrides.
        kwargs["maxsize"] = int(os_cfg.get("pool_maxsize", 20))

        self.client = OpenSearch(**kwargs)

        # Environment this repo writes/reads (None = legacy un-suffixed).
        self.env = env

        # Nombres de los índices según la propuesta — env-suffixed via the
        # canonical resolver so dev/prod stay isolated on the same cluster.
        self.INDEX_ENTITY = env_index("ask-entity-registry-v1", env)
        self.INDEX_FIELD = env_index("ask-field-registry-v1", env)
        self.INDEX_EDGE = env_index("ask-edge-registry-v1", env)

        # Embedding dimension — must match the active embedder.
        # Change opensearch.embedding_dim in settings.json when switching embedders,
        # then call drop_all_registry_indices() + re-ingest all YAMLs.
        # Default 1024 = platform standard (Bedrock Titan Text Embeddings V2,
        # runtime_settings, /setup/effective all agree). Override via
        # OPENSEARCH_EMBEDDING_DIM when switching to an embedder of a different size.
        self.embedding_dim = int(
            os.getenv("OPENSEARCH_EMBEDDING_DIM") or os_cfg.get("embedding_dim", 1024)
        )

        # Language of the analyzer applied to every searched text field. Same
        # deployment flag the authoring prompts read, so the corpus and its index
        # agree by construction (PLAN_SEMANTIC_LANGUAGE.md). Changing it requires
        # recreating the indices — mappings are immutable — and re-publishing.
        from .language_config import resolve_semantic_language

        self.semantic_language = resolve_semantic_language(config).value

    def _ensure_indices_exist(self):
        """
        Crea los índices con el mapping estricto para Agentic RAG.
        Habilita KNN (K-Nearest Neighbors) para búsqueda semántica.
        """
        # Configuración base: vectores + el analyzer de texto del deployment.
        base_settings = {
            "index": {"knn": True, "knn.algo_param.ef_search": 100},
            "analysis": _text_analysis_settings(self.semantic_language),
        }
        text_prop = {"type": "text", "analyzer": _ASK_TEXT_ANALYZER}

        # Vector field definition (HNSW algorithm)
        vector_prop = {
            "type": "knn_vector",
            "dimension": self.embedding_dim,
            "method": {"name": "hnsw", "space_type": "cosinesimil", "engine": "lucene"},
        }

        # 1. Body para ENTITY REGISTRY
        entity_body = {
            "settings": base_settings,
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "internal_id": {"type": "keyword"},
                    "db_table_name": {"type": "keyword"},
                    "layer": {"type": "keyword"},
                    "entity_role": {"type": "keyword"},
                    # `text`, NOT `keyword`: this field is searched with
                    # `multi_match` at the HIGHEST boost (`name^1.5`), and a
                    # keyword only matches the whole string exactly — so the
                    # most-weighted lexical clause could never fire on a real
                    # question, in any language. The `.keyword` subfield keeps
                    # exact matching available (nothing uses it today: no
                    # term/terms query, aggregation or sort targets `name`).
                    "name": {
                        **text_prop,
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "description": text_prop,
                    # Declared explicitly. It was written by `save_silver_node` /
                    # `save_gold_node` but ABSENT from this mapping, so OpenSearch
                    # dynamic-mapped it to the `standard` analyzer — no stemming,
                    # no folding — even though it carries most of the retrieval
                    # signal (name + entity description + every field description
                    # and synonym, see `_extract_business_terms`).
                    "business_terms": text_prop,
                    "raw_yaml": {
                        "type": "text",
                        "index": False,
                    },
                    "embedding": vector_prop,
                }
            },
        }

        # 2. Body para FIELD REGISTRY
        field_body = {
            "settings": base_settings,
            "mappings": {
                "properties": {
                    "node_id": {"type": "keyword"},
                    # Same reasoning as the entity `name`: `search_best_field`
                    # runs `{"match": {"name": ...}}` on it. Field resolution is
                    # BM25-ONLY in practice (no writer emits a field embedding),
                    # so this is load-bearing.
                    "name": {
                        **text_prop,
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "field_role": {"type": "keyword"},
                    "type": {"type": "keyword"},
                    "description": text_prop,
                    # Alternative business names — `text` so BM25 matches them the
                    # same way it matches the description.
                    "synonyms": text_prop,
                    "embedding": vector_prop,
                }
            },
        }

        # 3. Body para EDGE REGISTRY
        #
        # This mapping must mirror `_build_edge_pair` exactly. It used to declare a
        # physical-join shape (node_id / left_table / right_table / condition /
        # embedding) that NONE of the writers ever emitted — the index only worked
        # because OpenSearch dynamic-mapped the real fields on first write. Edge docs
        # carry no vector, so there is no `embedding` here either.
        edge_body = {
            "settings": base_settings,
            "mappings": {
                "properties": {
                    "source_node": {"type": "keyword"},
                    "target_node": {"type": "keyword"},
                    "source_table": {"type": "keyword"},
                    "target_table": {"type": "keyword"},
                    "join_type": {"type": "keyword"},
                    "conditions": {
                        "type": "object",
                        "properties": {
                            "left_field": {"type": "keyword"},
                            "right_field": {"type": "keyword"},
                            "operator": {"type": "keyword"},
                        },
                    },
                    # Authored predicate, verbatim. `text` because it is rendered and
                    # searched as prose, not matched exactly.
                    "join_predicate": {"type": "text"},
                    "cardinality": {"type": "keyword"},
                    "traversal_cost": {"type": "float"},
                    "aggregation_safety": {"type": "keyword"},
                    "description": text_prop,
                    "is_reverse": {"type": "boolean"},
                    "semantic_label": {"type": "keyword"},
                    "cross_module": {"type": "boolean"},
                }
            },
        }

        # Diccionario para iterar y crear
        indices_setup = {
            self.INDEX_ENTITY: entity_body,
            self.INDEX_FIELD: field_body,
            self.INDEX_EDGE: edge_body,
        }

        for index_name, body in indices_setup.items():
            if not self.client.indices.exists(index=index_name):
                self.client.indices.create(index=index_name, body=body)

    def drop_all_registry_indices(self) -> dict[str, Any]:
        """Delete the 3 ask-* registry indices so they are recreated fresh on
        the next ingest call (with the current ``self.embedding_dim`` mapping).

        Use this when switching embedder providers that produce a different
        vector dimension — e.g. SAP AI Core text-embedding-3-large (3072) →
        BAAI/bge-base-en-v1.5 (768). Re-ingest all YAMLs after calling this.
        """
        dropped: list[str] = []
        errors: list[str] = []
        for index in [self.INDEX_ENTITY, self.INDEX_FIELD, self.INDEX_EDGE]:
            try:
                if self.client.indices.exists(index=index):
                    self.client.indices.delete(index=index)
                    dropped.append(index)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{index}: {exc}")
        return {"dropped": dropped, "errors": errors}

    def save_bronze_node(self, node, yaml_content: str) -> dict[str, int]:
        """
        Guarda la capa Bronze.
        REGLA DE ARQUITECTURA: Los campos Bronze NO se indexan en el Field Registry
        para no ensuciar la búsqueda semántica del Agente. Solo guardamos el manifiesto.
        """
        self._ensure_indices_exist()

        action = {
            "_op_type": "index",
            "_index": self.INDEX_ENTITY,
            "_id": node.id,
            "_source": {
                "id": node.id,
                "layer": node.layer,
                "source_system": node.source_system,
                "name": node.name,
                "alias": node.alias,
                "description": node.description,
                "primary_keys": node.primary_key,
                "raw_yaml": yaml_content,
            },
        }

        helpers.bulk(self.client, [action])
        return {"entities": 1, "fields": 0, "edges": 0}

    def save_silver_node(self, node, yaml_content: str, embedder=None) -> dict[str, int]:
        """
        Guarda la capa Silver.
        Se particiona en los 3 índices (Entity, Field, Edge) habilitando el Agentic RAG.
        """
        self._ensure_indices_exist()
        actions = []
        stats = {"entities": 0, "fields": 0, "edges": 0}
        # 1. Convertimos el nodo limpio a diccionario
        entity_dict = node.model_dump()

        # 2. Calculamos metadatos que SOLO viven en OpenSearch
        priority = self._calculate_anti_hallucination_priority(node.layer)
        biz_terms = self._extract_business_terms(entity_dict)
        key_summary = self._generate_key_fields_summary(entity_dict)

        # 3. AHORRO DE CRÉDITOS: Solo generamos el embedding del lenguaje de negocio [cite: 967]
        # Ya no recibimos el embedding por parámetro, lo generamos aquí con el texto mínimo
        embedding = None
        if embedder:
            embedding = embedder.embed_query(biz_terms)

        # 1. Documento para Entity Registry (Incluye el YAML)
        actions.append(
            {
                "_op_type": "index",
                "_index": self.INDEX_ENTITY,
                "_id": node.id,
                "_source": {
                    "id": node.id,
                    "internal_id": node.internal_id,
                    "db_table_name": node.db_table_name,
                    "layer": node.layer,
                    "version": node.version,
                    "source_system": node.source_system,
                    "business_process": node.business_process,
                    "module": node.module,
                    # Secondary categorization, indexed so catalog faceting is
                    # actually possible (the models used to drop these silently,
                    # which made the documented faceting unimplementable).
                    "tag1": getattr(node, "tag1", "") or "",
                    "tag2": getattr(node, "tag2", "") or "",
                    "name": node.name,
                    "classification": node.classification,
                    "description": node.description,
                    "entity_role": node.entity_role,
                    "grain": (
                        node.grain.model_dump() if hasattr(node.grain, "model_dump") else node.grain
                    ),
                    "composed_of": node.composed_of,
                    # Opcional: Guardamos el join_graph interno aquí, no en el Edge Registry
                    "internal_join_graph": [
                        j.model_dump() if hasattr(j, "model_dump") else j for j in node.join_graph
                    ],
                    "raw_yaml": yaml_content,
                    "embedding": embedding,
                    "anti_hallucination_priority": priority,
                    "key_fields_summary": key_summary,
                    "business_terms": biz_terms,
                },
            }
        )
        stats["entities"] += 1

        # 2. Documentos para Field Registry (Solo campos Silver)
        for field in node.fields:
            field_id = f"{node.id}_{field.name}".lower()
            actions.append(
                {
                    "_op_type": "index",
                    "_index": self.INDEX_FIELD,
                    "_id": field_id,
                    "_source": {
                        "node_id": node.id,
                        "name": field.name,
                        "source": field.source,
                        "field_role": field.field_role,
                        "type": field.type,
                        "description": field.description,
                        "aggregation_behavior": field.aggregation_behavior,
                        # Axis 2 of the aggregation contract. Indexed, not just
                        # modelled: without it the retrieval layer cannot tell an
                        # additive SUM from one that is valid only after a
                        # dimension has been collapsed.
                        "additivity": field.additivity,
                        "non_additive_over": field.non_additive_over or [],
                        # Alternative business names. Indexed so `search_best_field`
                        # can match on them, which is the whole point of the key.
                        "synonyms": list(getattr(field, "synonyms", None) or []),
                    },
                }
            )
            stats["fields"] += 1

        # 3. Documentos para Edge Registry (Relaciones Semánticas Inter-Entidades y Reverse Edges)
        if hasattr(node, "relationships") and node.relationships:
            for rel in node.relationships:
                for edge_id, edge_source in _build_edge_pair(node, rel):
                    actions.append(
                        {
                            "_op_type": "index",
                            "_index": self.INDEX_EDGE,
                            "_id": edge_id,
                            "_source": edge_source,
                        }
                    )
                    stats["edges"] += 1

        # Ejecutamos la transacción masiva (Bulk) en OpenSearch
        from opensearchpy import helpers

        helpers.bulk(self.client, actions)

        return stats

    def save_gold_node(self, node, yaml_content: str, embedder=None) -> dict[str, int]:
        """
        Indexa el Data Product Gold en los mismos registros que Bronze/Silver.
        Esto permite que LangChain busque en un solo lugar.

        Signature mirrors `save_silver_node` — the embedder is passed in and the
        embedded text is built HERE, from the same `_extract_business_terms`
        projection. A Gold embedded on `name + description` alone competes for
        kNN against Silvers embedded on every field description, i.e. the
        Medallion priority inverted at the retrieval layer.
        """
        self._ensure_indices_exist()
        actions = []
        stats = {"entities": 0, "fields": 0, "edges": 0}
        entity_dict = node.model_dump()

        # The same three OpenSearch-only fields Silver gets, for the same
        # reasons: `anti_hallucination_priority` is what lifts Gold above Silver
        # in the Medallion re-ranking (`ocsl_retriever` reads it with a "normal"
        # default, so an absent field silently demotes Gold to Silver's tier),
        # `business_terms` is the field both the hybrid search and the Gold
        # rescue query match on, and `key_fields_summary` is the anti
        # Lost-in-the-Middle block the retriever feeds the prompt.
        priority = self._calculate_anti_hallucination_priority(node.layer)
        biz_terms = self._extract_business_terms(entity_dict)
        key_summary = self._generate_key_fields_summary(entity_dict)
        embedding = embedder.embed_query(biz_terms) if embedder else None

        # 1. ENTITY REGISTRY (El documento macro)
        # GoldNode.module puede ser str o List[str]; normalizamos a string para
        # que el CatalogService del pipeline_v2 lo lea consistente con Silver.
        _mod_raw = getattr(node, "module", None)
        if isinstance(_mod_raw, list):
            module_str = ",".join(_mod_raw)
        else:
            module_str = str(_mod_raw) if _mod_raw else ""

        actions.append(
            {
                "_op_type": "index",
                "_index": self.INDEX_ENTITY,
                "_id": node.id,
                "_source": {
                    "id": node.id,
                    "internal_id": node.internal_id,
                    "db_table_name": node.db_table_name,
                    "layer": node.layer,
                    "version": getattr(node, "version", None),
                    "source_system": getattr(node, "source_system", None),
                    "business_process": node.business_process,
                    "module": module_str,
                    # Secondary categorization — see the Silver twin above. All 5
                    # shipped Golds carry these (tag1 = process short code,
                    # tag2 = primary module).
                    "tag1": getattr(node, "tag1", "") or "",
                    "tag2": getattr(node, "tag2", "") or "",
                    "name": node.name,
                    "classification": getattr(node, "classification", None),
                    "description": node.description,
                    "entity_role": node.entity_role,
                    "grain": (
                        node.grain.model_dump() if hasattr(node.grain, "model_dump") else node.grain
                    ),
                    # No `composed_of` at Gold: a Gold is not a composition of
                    # joinable tables, it IS a physical table — carried by
                    # `db_table_name` above. Every consumer of the indexed key
                    # reads it with `.get(..., [])`.
                    "raw_yaml": yaml_content,
                    "embedding": embedding,
                    "anti_hallucination_priority": priority,
                    "key_fields_summary": key_summary,
                    "business_terms": biz_terms,
                },
            }
        )
        stats["entities"] += 1

        # 2. FIELD REGISTRY — Gold usa `fields[]` unificado con field_role.
        # Clasificamos por role para que Field Registry quede consistente con Silver.
        fields = getattr(node, "fields", []) or []
        for field in fields:
            field_id = f"{node.id}_{field.name}".lower()
            # The raw authored role is indexed verbatim, exactly as save_silver_node
            # does at the Silver branch. The previous normalisation collapsed
            # identifier/attribute/status_flag into `dimension`, which gave the Field
            # Registry an effective 3-value vocabulary — narrower than the model, the
            # standard and both public docs — and silently indexed Gold `status_flag`
            # fields as groupable dimensions, the exact thing the role exists to prevent.
            normalized_role = str(getattr(field, "field_role", "dimension")).lower()
            actions.append(
                {
                    "_op_type": "index",
                    "_index": self.INDEX_FIELD,
                    "_id": field_id,
                    "_source": {
                        "node_id": node.id,
                        "name": field.name,
                        "source": getattr(field, "source", None),
                        "field_role": normalized_role,
                        "type": getattr(field, "type", None) or "UNKNOWN",
                        "description": getattr(field, "description", ""),
                        "aggregation_behavior": getattr(field, "aggregation_behavior", None),
                        "additivity": getattr(field, "additivity", None),
                        "non_additive_over": getattr(field, "non_additive_over", None) or [],
                        # Alternative business names. Indexed so `search_best_field`
                        # can match on them, which is the whole point of the key.
                        "synonyms": list(getattr(field, "synonyms", None) or []),
                    },
                }
            )
            stats["fields"] += 1

        # 3. EDGE REGISTRY — Gold también indexa relationships (spec Sec 7.3).
        # Patron idéntico al de save_silver_node: forward edge + reverse edge
        # auto-generado con cardinalidad invertida.
        if hasattr(node, "relationships") and node.relationships:
            for rel in node.relationships:
                for edge_id, edge_source in _build_edge_pair(node, rel):
                    actions.append(
                        {
                            "_op_type": "index",
                            "_index": self.INDEX_EDGE,
                            "_id": edge_id,
                            "_source": edge_source,
                        }
                    )
                    stats["edges"] += 1

        helpers.bulk(self.client, actions)
        return stats

    def search_best_field(self, text_query: str, vector_query: list) -> dict:
        """
        Busca en el Field Registry la columna que mejor coincide con el término semántico.
        """
        # LEXICAL ONLY, deliberately. There used to be a
        # `{"knn": {"embedding": ...}}` clause here, but NOTHING writes an
        # `embedding` into a field document (`save_silver_node` /
        # `save_gold_node` index name/description/synonyms/role/type only), so it
        # could never match — a dead clause that made this read like a hybrid
        # search and hid the fact that field resolution is decided purely by
        # BM25. Consequence to keep in mind: at field level, wording and
        # diacritics are ALL the matching there is, which is why the analyzer +
        # asciifolding work matters (PLAN_SEMANTIC_LANGUAGE.md W3). Restoring a
        # vector leg means writing a per-field embedding at publish time and
        # declaring the vector in the field mapping — a real feature, not a
        # clause. ``vector_query`` is kept in the signature for that.
        body = {
            "size": 1,
            "query": {
                "bool": {
                    "should": [
                        {"match": {"description": text_query}},
                        {"match": {"name": text_query}},
                        # Alternative business names. The comment above claimed
                        # synonyms were searched long before anything indexed them;
                        # this is the clause that makes the claim true.
                        {"match": {"synonyms": text_query}},
                    ]
                }
            },
        }

        # Asumiendo que guardaste los campos en INDEX_FIELD durante la ingesta
        resp = self.client.search(index=self.INDEX_FIELD, body=body)

        hits = resp["hits"]["hits"]
        if not hits:
            return None

        best_hit = hits[0]
        source = best_hit["_source"]

        return {
            "node_id": source.get("node_id"),  # El ID de la tabla padre
            "field_name": source.get("name"),  # El nombre de la columna física
            "score": best_hit["_score"],
        }

    def get_all_edges(self) -> list:
        """
        Extrae todas las relaciones (aristas) del Edge Registry en OpenSearch
        para alimentar el algoritmo de Dijkstra. Incluye soporte para datos legacy
        y filtra documentos basura.
        """
        from ..domain.graph_models import (
            Cardinality,
            JoinCondition,
            JoinType,
            RelationEdge,
        )

        body = {"query": {"match_all": {}}, "size": 5000}

        try:
            # env-aware: read the same env's edge index the repo was built for
            # (was a hard-coded literal → dev/prod silently read the legacy index)
            resp = self.client.search(index=self.INDEX_EDGE, body=body)
            edges = []

            legacy_map = {
                "1:1": "one_to_one",
                "1:N": "one_to_many",
                "N:1": "many_to_one",
                "N:N": "many_to_many",
            }

            for hit in resp["hits"]["hits"]:
                src = hit["_source"]

                # 🛡️ ESCUDO CONTRA DATOS VIEJOS:
                # Si no tiene source o target explícito, es un join físico viejo. Lo ignoramos.
                source_node = src.get("source_node")
                target_node = src.get("target_node")

                if not source_node or not target_node:
                    continue

                # Pre-alignment documents stuffed the ENTIRE predicate into
                # `left_field` with an empty `right_field` whenever it was not a
                # single simple comparison. Such an entry is not a condition — it is
                # a predicate that failed to parse — so it is dropped here and
                # recovered as `join_predicate` below rather than propagated as a
                # half-empty JoinCondition that renders as `"<predicate>" = ""`.
                raw_conditions = src.get("conditions") or []
                conditions = [
                    JoinCondition(
                        left_field=c.get("left_field", ""),
                        right_field=c.get("right_field", ""),
                        operator=c.get("operator", "="),
                    )
                    for c in raw_conditions
                    if c.get("left_field") and c.get("right_field")
                ]
                salvaged_predicate = next(
                    (
                        c.get("left_field") or c.get("right_field") or ""
                        for c in raw_conditions
                        if not (c.get("left_field") and c.get("right_field"))
                    ),
                    "",
                )

                raw_card = src.get("cardinality", "one_to_many")
                safe_card = legacy_map.get(raw_card, raw_card)

                # Per-edge tolerance. Both enum coercions below used to raise on an
                # unrecognised value, and the raise was caught by the blanket handler
                # at the bottom of this method — which returns `[]`, i.e. ONE bad edge
                # document deleted the ENTIRE join topology for the Precise plane with
                # nothing but a stdout warning. Two live routes into that state:
                # a `cardinality` outside Cardinality (now closed at the model, but
                # migrated/hand-written docs remain), and a `join_type` of `CROSS`,
                # which `nodes.py` permits on `join_graph` while this enum lacks it.
                # Skip the offending edge instead and keep the graph.
                try:
                    edge_join_type = JoinType(src.get("join_type", "INNER").upper())
                    edge_cardinality = Cardinality(safe_card)
                except ValueError as exc:
                    print(
                        f"⚠️ Edge {source_node} → {target_node} skipped: "
                        f"unrecognised join_type/cardinality ({exc})"
                    )
                    continue

                edge = RelationEdge(
                    source_node=source_node,
                    target_node=target_node,
                    join_type=edge_join_type,
                    conditions=conditions,
                    cardinality=edge_cardinality,
                    traversal_cost=src.get("traversal_cost", 1.0),
                    is_reverse=src.get("is_reverse", False),
                    source_table=src.get("source_table") or "",
                    target_table=src.get("target_table") or "",
                    # Pre-alignment documents have no `join_predicate`. Recover it
                    # from the unparsed fragment when there is one, else rebuild it
                    # from the parsed conditions, so an un-reindexed registry still
                    # renders a usable ON clause.
                    join_predicate=src.get("join_predicate")
                    or salvaged_predicate
                    or " AND ".join(
                        f"{c.left_field} {c.operator} {c.right_field}" for c in conditions
                    ),
                    aggregation_safety=src.get("aggregation_safety") or "safe",
                    description=src.get("description"),
                    semantic_label=src.get("semantic_label"),
                    cross_module=bool(src.get("cross_module", False)),
                )
                edges.append(edge)

            return edges

        except Exception as e:
            print(f"⚠️ Advertencia: No se pudieron extraer los Edges de OpenSearch: {str(e)}")
            import traceback

            traceback.print_exc()
            return []

    def get_lightweight_entities(self) -> list:
        """
        Recupera un catálogo ligero de Data Products para la UI,
        excluyendo los embeddings y campos pesados para ahorrar memoria.
        """
        try:
            response = self.client.search(
                index=self.INDEX_ENTITY,
                body={
                    "query": {"match_all": {}},
                    # Solo pedimos los campos estrictamente necesarios para el menú
                    "_source": {"includes": ["id", "name", "layer", "description"]},
                    "size": 100,
                },
            )
            return [hit["_source"] for hit in response["hits"]["hits"]]
        except Exception as e:
            # Name the RESOLVED index: in a from-zero / env-suffixed deploy this
            # is usually "index_not_found" for ``ask-entity-registry-v1-{env}``
            # before anything is published there. A silent [] (the old stderr
            # print) read as "nothing published" — surface which index was hit.
            logger.warning(
                "get_lightweight_entities: query against index %r failed (returning []): %s",
                self.INDEX_ENTITY,
                e,
            )
            return []

    def get_entity_by_id(self, entity_id: str) -> dict:
        """
        Recupera el documento JSON completo para un ID específico.
        """
        try:
            response = self.client.search(
                index=self.INDEX_ENTITY,
                body={
                    "query": {"match": {"id": entity_id}},
                    # Si tuvieras un campo de vector llamado 'embedding',
                    # puedes excluirlo aquí de la descarga final si solo quieres el YAML
                    "_source": {"excludes": ["embedding", "vector_field"]},
                    "size": 1,
                },
            )
            hits = response["hits"]["hits"]
            if hits:
                return hits[0]["_source"]
            return None
        except Exception as e:
            print(f"Error fetching entity by ID: {e}")
            return None

    def _calculate_anti_hallucination_priority(self, layer: str) -> str:
        """
        Implementa la lógica de la Sección 5.4 de la especificación OCSL.
        Calcula la prioridad automáticamente en lugar de requerirla manualmente.
        Para el MVP: La capa Gold asume prioridad crítica (+7 puntos).
        """
        layer_upper = layer.upper()
        if layer_upper == "GOLD":
            return "critical"
        elif layer_upper == "SILVER":
            return "normal"
        return "normal"

    def _generate_key_fields_summary(self, entity_dict: dict[str, Any]) -> str:
        """
        Implementa la lógica de la Sección 6.3 para evitar el problema de "Lost-in-the-Middle".
        Genera un resumen pre-calculado estricto que se inyectará en el prompt del LLM.
        """
        layer = entity_dict.get("layer", "UNKNOWN").upper()
        name = entity_dict.get("name", "UNKNOWN")
        # A Silver names its bronze lineage; a Gold has none — it is itself a
        # physical table — so it names its own. Both labels are honest about
        # what the model is being told it can read from.
        composed_of = entity_dict.get("composed_of") or []
        source_label = "SAP TABLES"
        if not composed_of:
            own_table = entity_dict.get("db_table_name")
            if own_table:
                composed_of = [own_table]
                source_label = "PHYSICAL TABLE"

        # Extraemos solo lo esencial: identificadores, dimensiones y métricas
        key_fields: list[str] = []
        metrics: list[str] = []

        for field in entity_dict.get("fields", []):
            role = field.get("field_role")
            field_name = field.get("name")
            description = field.get("description", "")
            source = field.get("source", "")

            # Everything that is not a measure is a key field. The old allowlist
            # named only identifier/dimension, so three of the six ratified roles
            # (`timestamp`, `status_flag`, `attribute` — see `SilverField`) rendered
            # as nothing: the from-zero `sales_order` alone has 24 `timestamp`
            # fields. Inverting instead of extending the list keeps this branch in
            # step with the role vocabulary automatically, and matches the sibling
            # renderer's own bucketing (`rag_text_renderer._render_silver`).
            if role != "measure":
                key_fields.append(f"- {field_name}: {description}")
            else:
                # Default to SUM only when the key is genuinely absent, which the
                # contract defines as "uncurated, assume additive". Never invent
                # SUM for a curated measure: this summary is prose the retrieval
                # layer shows the model, and printing "SUM" next to a running
                # total contradicts the structured contract in the same breath.
                agg_behavior = field.get("aggregation_behavior") or "SUM"
                additivity = field.get("additivity")
                if additivity == "non_additive":
                    metrics.append(f"- {field_name}: NON-ADDITIVE (never aggregate) of {source}")
                elif additivity == "semi_additive":
                    # No "a time dimension" fallback: since v2 the dimensions may be
                    # structural (a header amount restated on every item), so naming
                    # time would be a wrong fact in the block the model treats as a
                    # summary. `semi_additive` cannot validate without the list
                    # anyway, so the fallback only ever fired on invalid input.
                    over = (
                        ", ".join(field.get("non_additive_over") or []) or "its declared dimensions"
                    )
                    metrics.append(
                        f"- {field_name}: {agg_behavior} of {source} "
                        f"(SEMI-ADDITIVE — collapse {over} first, then aggregate)"
                    )
                else:
                    metrics.append(f"- {field_name}: {agg_behavior} of {source}")

        # Construimos el payload de texto compacto
        summary_lines = [
            f"DATA PRODUCT: {name} ({layer})",
            f"{source_label}: {', '.join(composed_of)}",
            "KEY FIELDS:",
        ]
        summary_lines.extend(key_fields)

        if metrics:
            summary_lines.append("METRICS:")
            summary_lines.extend(metrics)

        return "\n".join(summary_lines)

    def _extract_business_terms(self, entity_dict: dict[str, Any]) -> str:
        """
        Extrae el lenguaje de negocio para vectorizar (Sección 3.2).
        Concatena el nombre, la descripción principal y las descripciones de los campos.
        Evita inyectar nombres técnicos de tablas o columnas de SAP.
        """
        terms: list[str] = []

        # Agregamos el nombre (reemplazando guiones bajos por espacios) y descripción
        name = entity_dict.get("name", "").replace("_", " ")
        description = entity_dict.get("description", "")

        if name:
            terms.append(name)
        if description:
            terms.append(description)

        # Extraemos las descripciones de los campos como términos de negocio
        for field in entity_dict.get("fields", []):
            field_desc = field.get("description")
            if field_desc:
                terms.append(field_desc)
            # Alternative business names belong here for the same reason the
            # descriptions do: this string is what gets embedded, so a synonym that
            # never reaches it cannot boost retrieval — which is the only thing the
            # key was ever documented to do.
            terms.extend(str(s) for s in (field.get("synonyms") or []) if s)

        return " ".join(terms)

    def delete_entity_and_fields(self, entity_id: str) -> dict[str, int]:
        """
        Borra una entidad de ask-entity-registry-v1 y todos sus campos
        asociados de ask-field-registry-v1.
        Solo permite borrar capas silver, gold y metric.
        Retorna stats con la cantidad de documentos eliminados.

        NOTE — why 'metric' is still whitelisted here while the rest of the
        metric layer is gone: this guard is the only sanctioned way to remove
        the legacy `layer: metric` documents that predate the removal and are
        still sitting in the registry. Dropping it before the purge would
        strand them permanently. Once the registry purge has run (internal
        design doc REQ_METRICS_PURGE), drop 'metric' from this tuple and from
        the error message in a follow-up commit.
        """
        stats = {"entities_deleted": 0, "fields_deleted": 0}

        # 1. Verificar que la entidad existe y es de capa permitida
        entity = self.get_entity_by_id(entity_id)
        if not entity:
            raise ValueError(f"Entity '{entity_id}' not found in OpenSearch.")

        layer = (entity.get("layer") or "").lower()
        if layer not in ("silver", "gold", "metric"):
            raise ValueError(
                f"Cannot delete entity with layer '{layer}'. "
                "Only silver, gold and metric layers are allowed."
            )

        # 2. Borrar campos del Field Registry (delete_by_query donde node_id == entity_id)
        field_response = self.client.delete_by_query(
            index=self.INDEX_FIELD,
            body={"query": {"term": {"node_id": entity_id}}},
            refresh=True,
        )
        stats["fields_deleted"] = field_response.get("deleted", 0)

        # 3. Borrar la entidad del Entity Registry
        try:
            self.client.delete(index=self.INDEX_ENTITY, id=entity_id, refresh=True)
            stats["entities_deleted"] = 1
        except Exception:
            # Intentar por query si el _id no coincide exactamente
            del_resp = self.client.delete_by_query(
                index=self.INDEX_ENTITY,
                body={"query": {"term": {"id": entity_id}}},
                refresh=True,
            )
            stats["entities_deleted"] = del_resp.get("deleted", 0)

        return stats

    def delete_edges_for_entity(self, entity_id: str) -> int:
        """Delete every edge in this env's Edge Registry where ``entity_id`` is
        an endpoint (source OR target). Used by the per-env unpublish so the
        env edge index does not keep dangling edges to a removed entity.

        Env-aware via ``self.INDEX_EDGE``. Returns the number of edges deleted.
        Tolerates a missing index (returns 0).
        """
        try:
            resp = self.client.delete_by_query(
                index=self.INDEX_EDGE,
                body={
                    "query": {
                        "bool": {
                            "should": [
                                {"term": {"source_node": entity_id}},
                                {"term": {"target_node": entity_id}},
                            ],
                            "minimum_should_match": 1,
                        }
                    }
                },
                refresh=True,
            )
            return int(resp.get("deleted", 0))
        except Exception as exc:  # noqa: BLE001 — edge cleanup is best-effort
            print(f"⚠️  delete_edges_for_entity('{entity_id}') skipped: {exc}")
            return 0

    def search_hybrid_rrf(
        self,
        text_query: str,
        vector_query: list,
        size: int = 50,
        allowed_ids: list | None = None,
    ) -> list:
        """
        Stage 1a: Ejecuta la búsqueda híbrida usando Reciprocal Rank Fusion (RRF).
        Inmune a los outliers de BM25 (ej. repetición extrema de nombres de tablas).

        ``allowed_ids`` (workspace scope): when provided, the candidate universe
        is hard-restricted to those entity ids (keyword ``id`` field). ``should``
        still drives relevance; ``filter`` makes the search universe the
        workspace instead of the whole registry index.
        """
        bool_query: dict = {
            "should": [
                # Búsqueda Textual (BM25) con pesos específicos
                {
                    "multi_match": {
                        "query": text_query,
                        "fields": [
                            "name^1.5",
                            "description^1.2",
                            "business_terms^1.5",
                        ],
                        "type": "best_fields",
                    }
                },
                # Búsqueda Vectorial (kNN)
                {"knn": {"embedding": {"vector": vector_query, "k": 100}}},
            ]
        }
        # Scope contract: None = unscoped (whole registry); [] = empty scope
        # (return nothing — terms:[] matches no docs). Branch on `is not None`,
        # NOT truthiness, so an empty workspace scope does not silently open up.
        if allowed_ids is not None:
            bool_query["filter"] = [{"terms": {"id": list(allowed_ids)}}]
        body = {"size": size, "query": {"bool": bool_query}}

        try:
            # Nota: Si tu OpenSearch soporta la cláusula "rank": {"rrf": {}}, puedes usarla nativamente.
            # Aquí usamos el score híbrido estándar que OpenSearch devuelve al combinar bool SHOULD.
            resp = self.client.search(index=self.INDEX_ENTITY, body=body)
            return resp["hits"]["hits"]
        except Exception as e:
            print(f"❌ Error en búsqueda híbrida RRF: {e}")
            return []

    def search_gold_rescue(
        self, text_query: str, size: int = 5, allowed_ids: list | None = None
    ) -> list:
        """
        Stage 1b: Consulta paralela de rescate.
        Garantiza que al menos un candidato Gold sea evaluado para evitar el "Gold Starvation".

        ``allowed_ids`` (workspace scope): when provided, the Gold rescue is also
        restricted to the workspace's entity ids.
        """
        filter_clause: list = [{"term": {"layer": "gold"}}]  # Filtro estricto de capa
        # Scope contract: None = unscoped; [] = empty scope (terms:[] → no docs).
        if allowed_ids is not None:
            filter_clause.append({"terms": {"id": list(allowed_ids)}})
        body = {
            "size": size,
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": text_query,
                                "fields": ["name", "description", "business_terms"],
                            }
                        }
                    ],
                    "filter": filter_clause,
                }
            },
        }

        try:
            resp = self.client.search(index=self.INDEX_ENTITY, body=body)
            return resp["hits"]["hits"]
        except Exception as e:
            print(f"❌ Error en Gold Rescue: {e}")
            return []
