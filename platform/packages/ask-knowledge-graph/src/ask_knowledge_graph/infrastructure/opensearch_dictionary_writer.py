"""
OpenSearchDictionaryWriter — concrete impl of DictionaryWriter (Iter 8).

Wraps the production-tested legacy `SemanticDictionaryService`. Same WRAP
strategy used by Iter 4's reader and Iter 6's writer — the legacy class
still owns index mapping, embedding hookup, and search bodies; this
adapter exposes them through a typed Protocol so admin tooling does not
need to import from `legacy/src/`.

Note: legacy methods that are designed to be defensive (return False / [] /
None on failure) preserve that contract through the wrapper. Methods that
can legitimately raise (notably `ensure_global_index` on a brand-new
cluster) get their failures translated to `DictionaryError` so callers can
catch a single typed exception.
"""

from __future__ import annotations

import logging
from typing import Any

from ..domain.errors import DictionaryError
from ..domain.models import DictionaryTerm
from ..domain.ports import DictionaryWriter

logger = logging.getLogger(__name__)


class OpenSearchDictionaryWriter(DictionaryWriter):
    """Adapter over `SemanticDictionaryService`'s read + write surface."""

    def __init__(self, legacy_service: Any) -> None:
        # legacy_service is a SemanticDictionaryService instance, constructed
        # by the caller (admin pages, factory) so this package does not bind
        # to the legacy class symbol.
        self._svc = legacy_service

    # ── Per-Silver-entity extension indices ─────────────────────────────────
    def ensure_index(self, silver_index: str) -> None:
        try:
            self._svc.ensure_index(silver_index)
        except Exception as exc:  # noqa: BLE001 — adapter boundary
            logger.warning("ensure_index(%s) failed: %s", silver_index, exc)
            raise DictionaryError(f"ensure_index({silver_index!r}) failed: {exc}") from exc

    def upsert_entry(self, silver_index: str, entry: dict[str, Any]) -> bool:
        try:
            return bool(self._svc.upsert_entry(silver_index, entry))
        except Exception as exc:  # noqa: BLE001
            logger.warning("upsert_entry(%s) failed: %s", silver_index, exc)
            raise DictionaryError(f"upsert_entry({silver_index!r}) failed: {exc}") from exc

    def list_entries(self, silver_index: str) -> list[DictionaryTerm]:
        try:
            return list(self._svc.list_entries(silver_index) or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("list_entries(%s) failed: %s", silver_index, exc)
            raise DictionaryError(f"list_entries({silver_index!r}) failed: {exc}") from exc

    def lookup_term(self, silver_index: str, business_term: str) -> DictionaryTerm | None:
        try:
            return self._svc.lookup_term(silver_index, business_term)
        except Exception as exc:  # noqa: BLE001
            logger.warning("lookup_term(%s, %s) failed: %s", silver_index, business_term, exc)
            raise DictionaryError(
                f"lookup_term({silver_index!r}, {business_term!r}) failed: {exc}"
            ) from exc

    # ── Global enriched dictionary ──────────────────────────────────────────
    def ensure_global_index(self) -> None:
        try:
            self._svc.ensure_global_index()
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensure_global_index failed: %s", exc)
            raise DictionaryError(f"ensure_global_index failed: {exc}") from exc

    def upsert_entry_global(self, entry: dict[str, Any]) -> bool:
        try:
            return bool(self._svc.upsert_entry_global(entry))
        except Exception as exc:  # noqa: BLE001
            logger.warning("upsert_entry_global failed: %s", exc)
            raise DictionaryError(f"upsert_entry_global failed: {exc}") from exc

    def search_hybrid(
        self,
        query: str,
        query_vector: list[float],
        module: str | None = None,
        entry_type: str | None = None,
        size: int = 10,
    ) -> list[DictionaryTerm]:
        try:
            return list(
                self._svc.search_hybrid(
                    query=query,
                    query_vector=query_vector,
                    module=module,
                    entry_type=entry_type,
                    size=size,
                )
                or []
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_hybrid failed: %s", exc)
            raise DictionaryError(f"search_hybrid failed: {exc}") from exc

    def lookup_term_global(self, business_term: str) -> list[DictionaryTerm]:
        try:
            return list(self._svc.lookup_term_global(business_term) or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("lookup_term_global(%s) failed: %s", business_term, exc)
            raise DictionaryError(f"lookup_term_global({business_term!r}) failed: {exc}") from exc

    def list_entries_global(self, module: str | None = None) -> list[DictionaryTerm]:
        try:
            return list(self._svc.list_entries_global(module) or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("list_entries_global(%s) failed: %s", module, exc)
            raise DictionaryError(f"list_entries_global({module!r}) failed: {exc}") from exc

    def delete_entry_global(self, entry_id: str) -> bool:
        try:
            return bool(self._svc.delete_entry_global(entry_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("delete_entry_global(%s) failed: %s", entry_id, exc)
            raise DictionaryError(f"delete_entry_global({entry_id!r}) failed: {exc}") from exc

    # ── Schema v2 — value-level enrichment ──────────────────────────────────
    def get_field_enrichments(
        self, entity_id: str, field_name: str | None = None
    ) -> list[DictionaryTerm]:
        try:
            return list(self._svc.get_field_enrichments(entity_id, field_name) or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "get_field_enrichments(%s, %s) failed: %s",
                entity_id,
                field_name,
                exc,
            )
            raise DictionaryError(
                f"get_field_enrichments({entity_id!r}, {field_name!r}) failed: {exc}"
            ) from exc

    def get_field_enrichments_bulk(self, entity_ids: list[str]) -> dict[str, list[DictionaryTerm]]:
        try:
            return dict(self._svc.get_field_enrichments_bulk(entity_ids) or {})
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_field_enrichments_bulk failed: %s", exc)
            raise DictionaryError(f"get_field_enrichments_bulk failed: {exc}") from exc
