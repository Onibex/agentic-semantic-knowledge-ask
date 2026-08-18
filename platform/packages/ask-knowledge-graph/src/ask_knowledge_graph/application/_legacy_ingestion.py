# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

# application/_legacy_ingestion.py — Iter 8.5: promoted from legacy/src/pipeline/application/ingestion_service.py
from ..infrastructure.yaml_serializer import AskYamlSerializer, load_yaml_text
from ..infrastructure.file_storage_repo import AskPathBuilder
from ..domain.nodes import GoldNode


class MetadataIngestionService:
    def __init__(self, parser, os_repository, file_repository=None, embedder=None):
        self.parser = parser
        self.os_repository = os_repository
        self.file_repository = file_repository  # <--- Inyectamos el repo de archivos
        self.yaml_serializer = AskYamlSerializer()
        self.embedder = embedder

    def execute(self, raw_json: dict) -> dict:
        bronze_nodes, silver_node = self.parser.parse_to_domain(raw_json)
        total_stats = {"entities": 0, "fields": 0, "edges": 0}

        # 1. Procesar capa Bronze
        for b_node in bronze_nodes:
            yaml_string = self.yaml_serializer.to_yaml(b_node.dict(exclude_none=True))

            if self.file_repository:
                file_path = AskPathBuilder.build_path(b_node)
                self.file_repository.save_file(file_path, yaml_string)

            # --- CORRECCIÓN AQUÍ ---
            # b_stats es un dict: {"entities": 1, "fields": 0, "edges": 0}
            b_stats = self.os_repository.save_bronze_node(
                b_node, yaml_content=yaml_string
            )

            total_stats["entities"] += b_stats.get("entities", 0)
            # Ya no restamos 1, porque save_bronze_node ya devuelve 0 fields por diseño
            total_stats["fields"] += b_stats.get("fields", 0)

        # 2. Procesar capa Silver
        if silver_node:
            silver_yaml = self.yaml_serializer.to_yaml(
                silver_node.dict(exclude_none=True)
            )

            if self.file_repository:
                file_path = AskPathBuilder.build_path(silver_node)
                self.file_repository.save_file(file_path, silver_yaml)

            # s_stats es un dict: {"entities": 1, "fields": X, "edges": Y}
            s_stats = self.os_repository.save_silver_node(
                silver_node, yaml_content=silver_yaml, embedder=self.embedder
            )

            total_stats["entities"] += s_stats.get("entities", 0)
            total_stats["fields"] += s_stats.get("fields", 0)
            total_stats["edges"] += s_stats.get("edges", 0)

            # Surface the Silver back to the caller so the admin-api router
            # can cascade the RAG indexing (rag_schema) without re-parsing
            # the SAP JSON. The keys are read by
            # MetadataIngestionServiceWrapper.ingest_sap_json → IngestionResult.raw_stats.
            total_stats["silver_entity_id"] = silver_node.id
            total_stats["silver_yaml"]      = silver_yaml

        return total_stats

    def execute_yaml_ingestion(self, yaml_content: str) -> dict:
        """
        Método genérico que detecta la capa del YAML y orquesta la ingesta.
        """
        try:
            # YAML 1.2 (ruamel) — the same parser the admin editor uses on
            # read/write. PyYAML's YAML 1.1 safe_load coerces bare tokens like
            # On/Off/Yes/No/True/False to bool, which then fails Pydantic string
            # fields (e.g. a bronze field whose description is the text "On").
            raw_data = load_yaml_text(yaml_content)

            # Detectamos la capa. Ajusta la llave ("layer") según la estructura de tu YAML
            layer = raw_data.get("layer", raw_data.get("medallion_layer", "")).lower()

            if layer == "gold":
                from ..domain.nodes import GoldNode

                node = GoldNode.model_validate(raw_data)

                # Same call shape as the Silver branch below: the repository owns
                # the embedded projection (`_extract_business_terms` = name +
                # description + every field description + synonyms), so both
                # planes are vectorized from the same text.
                return self.os_repository.save_gold_node(
                    node, yaml_content, self.embedder
                )

            elif layer == "silver":
                # Lógica para Silver YAML
                from ..domain.nodes import SilverNode

                node = SilverNode.model_validate(raw_data)

                # Asumiendo que tu repo tiene un método equivalente para guardar Silver Nodes aislados
                return self.os_repository.save_silver_node(
                    node, yaml_content, self.embedder
                )

            elif layer == "metric":
                # The `metric` layer is REMOVED, not merely deprecated: a
                # measure is a `field_role: measure` field with an
                # `aggregation_behavior` on its owning Silver/Gold. Reject
                # loudly so a stale metric YAML cannot silently re-enter the
                # registry. See docs/semantic-layer/README.md Appendix A.
                raise ValueError(
                    "The 'metric' layer has been removed from the ASK semantic layer. "
                    "Declare the measure as a field with field_role: measure + "
                    "aggregation_behavior on the Silver/Gold that owns it."
                )

            elif layer == "bronze":
                # Bronze YAML directo (típicamente vía cascade desde Publish de
                # un Silver, o re-ingest manual del archivo). save_bronze_node
                # no necesita embedder — los Bronces no llevan texto
                # business-rich, se buscan por nombre de tabla exacto.
                from ..domain.nodes import BronzeNode

                node = BronzeNode.model_validate(raw_data)
                return self.os_repository.save_bronze_node(
                    node, yaml_content=yaml_content
                )

            else:
                raise ValueError(
                    f"Capa desconocida o no especificada en el YAML: '{layer}'"
                )

        except Exception as e:
            raise ValueError(f"Error procesando la ingesta del SML YAML: {str(e)}")
