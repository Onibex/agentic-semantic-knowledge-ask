"""Contract test for CatalogService scope filtering (smart mode).

Pins the three-valued allowed_ids contract at the catalog layer:
  * None       → full catalog (unscoped)
  * empty set  → EMPTY catalog (the workspace resolves to nothing in this env)
  * {ids}      → only those entries
Treating an empty set as falsy would return the WHOLE catalog — a scope leak.
"""

from __future__ import annotations

from ask_intent_resolution.smart.application.catalog_service import CatalogService
from ask_intent_resolution.smart.domain.catalog import Catalog, CatalogEntry


def _entry(eid: str) -> CatalogEntry:
    return CatalogEntry(id=eid, name=eid, layer="silver", entity_role="fact")


def _service_with_cache() -> CatalogService:
    svc = CatalogService(os_repository=None)  # repo unused once _cache is primed
    svc._cache = Catalog(entries=[_entry("a"), _entry("b"), _entry("c")])  # noqa: SLF001
    return svc


def test_none_returns_full_catalog():
    svc = _service_with_cache()
    assert svc.get_catalog(allowed_ids=None).valid_ids() == {"a", "b", "c"}


def test_subset_filters_to_those_ids():
    svc = _service_with_cache()
    assert svc.get_catalog(allowed_ids={"a", "c"}).valid_ids() == {"a", "c"}


def test_empty_set_returns_empty_catalog_not_full():
    svc = _service_with_cache()
    assert svc.get_catalog(allowed_ids=set()).entries == []
