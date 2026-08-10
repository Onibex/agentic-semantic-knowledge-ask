"""Tests for MetadataIngestionServiceWrapper using stubbed legacy + writer."""

from __future__ import annotations

import pytest

from ask_knowledge_graph.application.ingestion_service import (
    MetadataIngestionServiceWrapper,
    _detect_entity_id,
    _detect_layer,
)
from ask_knowledge_graph.domain.errors import IngestionError
from ask_knowledge_graph.domain.models import IngestionRequest, IngestionResult
from ask_knowledge_graph.domain.ports import IngestionService

SILVER_YAML = """
id: silver_s4h_sd_sales_order
layer: silver
module: sd
fields:
  - name: vbeln
    source: VBAK.VBELN
"""

GOLD_YAML = """
id: gold_sales_performance
medallion_layer: GOLD
fields: []
"""

UNKNOWN_LAYER_YAML = """
id: foo_bar
layer: platinum
"""

# The `metric` layer was REMOVED (not deprecated) — it must detect as unknown
# exactly like `platinum`, so no stale metric YAML can re-enter the registry.
METRIC_YAML = """
id: metric_sd_sales_document_count
layer: metric
home_entity: silver_s4h_sd_sales_order
base_field: vbeln_vbak
aggregation_function: COUNT_DISTINCT
"""

INVALID_YAML = "not: a: valid: yaml: %%%"


class _StubLegacy:
    def __init__(self, *, return_value=None, raises=None, json_return=None, json_raises=None):
        self.calls: list[str] = []
        self.json_calls: list[dict] = []
        self._return = return_value or {"entities": 1, "fields": 5, "edges": 0}
        self._raises = raises
        self._json_return = json_return or {"entities": 2, "fields": 12, "edges": 1}
        self._json_raises = json_raises

    def execute_yaml_ingestion(self, yaml_content: str):
        self.calls.append(yaml_content)
        if self._raises:
            raise self._raises
        return self._return

    def execute(self, raw_json: dict):
        self.json_calls.append(raw_json)
        if self._json_raises:
            raise self._json_raises
        return self._json_return


class _StubWriter:
    def __init__(self):
        self.deleted: list[str] = []

    def save_bronze(self, *a, **kw): ...
    def save_silver(self, *a, **kw): ...
    def save_gold(self, *a, **kw): ...

    def delete_entity(self, entity_id: str):
        self.deleted.append(entity_id)
        return {"entities": 1, "fields": 5, "edges": 2}


def test_protocol_satisfied():
    svc: IngestionService = MetadataIngestionServiceWrapper(_StubLegacy(), _StubWriter())
    assert callable(svc.ingest_yaml)
    assert callable(svc.ingest_sap_json)
    assert callable(svc.delete_entity)


def test_empty_yaml_returns_error():
    svc = MetadataIngestionServiceWrapper(_StubLegacy(), _StubWriter())
    result = svc.ingest_yaml(IngestionRequest(yaml_content=""))
    assert result.error == "Empty YAML content."
    assert result.entity_id is None


def test_whitespace_yaml_returns_error():
    svc = MetadataIngestionServiceWrapper(_StubLegacy(), _StubWriter())
    result = svc.ingest_yaml(IngestionRequest(yaml_content="   \n   "))
    assert result.error == "Empty YAML content."


def test_silver_yaml_happy_path():
    legacy = _StubLegacy(return_value={"entities": 1, "fields": 7, "edges": 4})
    svc = MetadataIngestionServiceWrapper(legacy, _StubWriter())
    result = svc.ingest_yaml(IngestionRequest(yaml_content=SILVER_YAML))

    assert isinstance(result, IngestionResult)
    assert result.error is None
    assert result.entity_id == "silver_s4h_sd_sales_order"
    assert result.layer == "silver"
    assert result.entities_indexed == 1
    assert result.fields_indexed == 7
    assert result.edges_indexed == 4
    # The legacy got the EXACT yaml_content (no transformation).
    assert legacy.calls == [SILVER_YAML]


def test_gold_yaml_recognises_medallion_layer_alias():
    legacy = _StubLegacy()
    svc = MetadataIngestionServiceWrapper(legacy, _StubWriter())
    result = svc.ingest_yaml(IngestionRequest(yaml_content=GOLD_YAML))
    assert result.layer == "gold"
    assert result.entity_id == "gold_sales_performance"


def test_legacy_exception_wraps_in_typed_error():
    svc = MetadataIngestionServiceWrapper(
        _StubLegacy(raises=ValueError("bronze parser exploded")),
        _StubWriter(),
    )
    with pytest.raises(IngestionError) as ei:
        svc.ingest_yaml(IngestionRequest(yaml_content=SILVER_YAML))
    assert "bronze parser exploded" in str(ei.value)


def test_layer_override_takes_precedence():
    legacy = _StubLegacy()
    svc = MetadataIngestionServiceWrapper(legacy, _StubWriter())
    result = svc.ingest_yaml(IngestionRequest(yaml_content=SILVER_YAML, layer_override="gold"))
    assert result.layer == "gold"  # override beats the YAML's `layer: silver`


def test_unknown_layer_returns_none_layer():
    legacy = _StubLegacy()
    svc = MetadataIngestionServiceWrapper(legacy, _StubWriter())
    result = svc.ingest_yaml(IngestionRequest(yaml_content=UNKNOWN_LAYER_YAML))
    # The legacy will raise for "platinum" — but here we stub success.
    # The point: detection returns None for unknown layers; consumer sees that.
    assert result.layer is None
    assert result.entity_id == "foo_bar"


def test_delete_entity_negates_stats():
    """Delete returns stats with NEGATIVE counts (semantic: 'removed N')."""
    writer = _StubWriter()
    svc = MetadataIngestionServiceWrapper(_StubLegacy(), writer)
    result = svc.delete_entity("silver_x")
    assert writer.deleted == ["silver_x"]
    assert result.entity_id == "silver_x"
    assert result.entities_indexed == -1
    assert result.fields_indexed == -5
    assert result.edges_indexed == -2


def test_delete_empty_id_returns_error():
    svc = MetadataIngestionServiceWrapper(_StubLegacy(), _StubWriter())
    result = svc.delete_entity("")
    assert result.error == "Empty entity_id."


# ─────────────────────────────────────────────────────────────────────────────
# ingest_sap_json (Iter 8) — drives MetadataIngestionService.execute
# ─────────────────────────────────────────────────────────────────────────────
def test_ingest_sap_json_happy_path():
    legacy = _StubLegacy(json_return={"entities": 3, "fields": 18, "edges": 5})
    svc = MetadataIngestionServiceWrapper(legacy, _StubWriter())
    payload = {"name": "MOCK_DP", "fields": []}
    result = svc.ingest_sap_json(payload)

    assert isinstance(result, IngestionResult)
    assert result.error is None
    assert result.entities_indexed == 3
    assert result.fields_indexed == 18
    assert result.edges_indexed == 5
    assert legacy.json_calls == [payload]


def test_ingest_sap_json_empty_payload_returns_error():
    svc = MetadataIngestionServiceWrapper(_StubLegacy(), _StubWriter())
    result = svc.ingest_sap_json({})
    assert result.error == "Empty or invalid SAP JSON payload."


def test_ingest_sap_json_non_dict_returns_error():
    svc = MetadataIngestionServiceWrapper(_StubLegacy(), _StubWriter())
    result = svc.ingest_sap_json(None)  # type: ignore[arg-type]
    assert result.error == "Empty or invalid SAP JSON payload."


def test_ingest_sap_json_legacy_failure_wraps():
    svc = MetadataIngestionServiceWrapper(
        _StubLegacy(json_raises=RuntimeError("parser blew up")),
        _StubWriter(),
    )
    with pytest.raises(IngestionError) as ei:
        svc.ingest_sap_json({"k": "v"})
    assert "parser blew up" in str(ei.value)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def test_detect_layer_from_layer_field():
    assert _detect_layer(SILVER_YAML, None) == "silver"


def test_detect_layer_from_medallion_layer_field():
    assert _detect_layer(GOLD_YAML, None) == "gold"


def test_detect_layer_returns_none_for_unknown():
    assert _detect_layer(UNKNOWN_LAYER_YAML, None) is None


def test_detect_layer_returns_none_for_removed_metric_layer():
    """`metric` is no longer a valid layer — it must not round-trip."""
    assert _detect_layer(METRIC_YAML, None) is None


def test_detect_layer_returns_none_for_invalid_yaml():
    assert _detect_layer(INVALID_YAML, None) is None


def test_detect_layer_override_short_circuits():
    assert _detect_layer(SILVER_YAML, override="bronze") == "bronze"


def test_detect_entity_id_from_id_field():
    assert _detect_entity_id(SILVER_YAML) == "silver_s4h_sd_sales_order"


def test_detect_entity_id_returns_none_for_invalid_yaml():
    assert _detect_entity_id(INVALID_YAML) is None


def test_detect_entity_id_returns_none_when_no_id():
    yaml_no_id = "layer: silver\nfields: []"
    assert _detect_entity_id(yaml_no_id) is None
