"""Agent CUSTOMER CONTEXT renders generic ``source_system`` with a back-compat
fallback to the deprecated ``sap_version``."""

from ask_orchestrator.organization_context import _render


def test_render_prefers_source_system():
    out = _render({"source_system": "SAP S/4HANA 2023"})
    assert "Source system: SAP S/4HANA 2023" in out
    assert "SAP version" not in out


def test_render_falls_back_to_sap_version():
    out = _render({"sap_version": "ECC 6.0"})
    assert "Source system: ECC 6.0" in out


def test_render_source_system_wins_over_legacy():
    out = _render({"source_system": "Salesforce", "sap_version": "old"})
    assert "Source system: Salesforce" in out
    assert "old" not in out


def test_render_none_when_empty():
    assert _render({}) is None
