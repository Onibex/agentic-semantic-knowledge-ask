"""Curated column naming (pure domain logic).

Single home for the two ingredients every published Silver/Gold column name is
made of:

* :func:`normalize_identifier` — the identifier normalizer for anything the
  extractor sends that is name-bearing (``alias_fldname``, ``fldname``,
  ``tabname``, ``alias_tabname``). Free-text fields (``description_field``)
  are NEVER normalized.
* :class:`ColumnNamingMode` — the deployment-level convention that decides
  which token prefixes the published column: the SAP field code
  (``vbeln_vbak``) or the business alias (``documento_ventas_vbak``). The
  suffix is the SAP table name in both modes.

The mode is resolved from the environment/config by
``infrastructure.naming_config`` (this module stays I/O-free) and consumed
only where names are MINTED — the SAP JSON parser and the admin SPA's manual
entity form. Everything downstream (grain, joins, prompts, SQL) reads the
persisted ``fields[].name`` and never re-derives it.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import Any


class ColumnNamingMode(str, Enum):
    """How the published curated column name is built from an extractor row.

    ``TECHNICAL`` — ``<fldname>_<tabname>`` (``vbeln_vbak``). The default.
    ``ALIAS`` — ``<alias_fldname>_<tabname>`` (``documento_ventas_vbak``),
    for clients whose ETL names physical columns after the business alias.
    """

    TECHNICAL = "technical"
    ALIAS = "alias"


# ── Identifier hygiene ───────────────────────────────────────────────────────
# The upstream OneConnect export is the origin of every alias defect we have
# seen (a trailing U+FFFD in TSPAT's ``alias_tabname``, junk labels, two
# dedup-suffix styles). ASK sanitizes defensively here; the export should not
# emit them (tracked as an upstream requirement).
#
# Non-printable / non-ASCII characters are DROPPED, never replaced, so the
# mojibake leaves no phantom underscore behind. Only the remaining illegal
# ASCII (space, '-', '.', '/', '%', tab…) becomes '_'.
#
# Deliberately NOT done: no stripping of trailing digits (96 aliases in the
# corpus mirror SAP's own column numbering — STCD1..4, KVGR1..5, PARH1..5) and
# no stripping of leading/trailing underscores (7 real aliases end in one:
# on_, tel_, from_, to_). Verified byte-identical on all 2,491 field aliases of
# the shipped SAP payloads; the only value it changes is the TSPAT mojibake.
_NON_PRINTABLE_RE = re.compile(r"[^\x20-\x7e]+")
_BAD_LOWER_RE = re.compile(r"[^a-z0-9_]+")
_BAD_UPPER_RE = re.compile(r"[^A-Z0-9_]+")


def normalize_identifier(raw: Any, *, fallback: str, upper: bool = False) -> str:
    """Coerce one identifier-bearing token into printable-ASCII snake_case.

    NFKD-folds first so accented Latin text degrades to its base letters
    ("año" → "ano", "crédito" → "credito") instead of losing the character
    outright, then drops what is still non-printable / non-ASCII and maps the
    remaining illegal ASCII to "_".

    ``upper=True`` (entity alias) forces UPPER_SNAKE — what 48/48 real
    ``alias_tabname`` values already are; ``upper=False`` (field aliases, id
    segments) forces lowercase. Falls back to ``fallback`` when sanitation
    leaves nothing usable: ``BronzeField.alias`` / ``BronzeNode.alias`` are
    both required and the alias is the last segment of the bronze id, so it can
    never be blank.

    In ``ColumnNamingMode.ALIAS`` this function IS the client-facing contract:
    the physical curated column must equal ``normalize_identifier(alias_fldname)
    + "_" + tabname.lower()`` (see REQ_CURATED_COLUMN_NAMING.md). A value it
    changes is reported as an ingest warning, never a rejection.
    """
    bad_re = _BAD_UPPER_RE if upper else _BAD_LOWER_RE

    def _clean(value: Any) -> str:
        s = unicodedata.normalize("NFKD", str(value or ""))
        s = _NON_PRINTABLE_RE.sub("", s)
        s = s.upper() if upper else s.lower()
        return bad_re.sub("_", s)

    out = _clean(raw)
    if out.strip("_"):
        return out
    out = _clean(fallback)
    return out if out.strip("_") else ("TABLE" if upper else "field")


def published_column_name(prefix: str, table: str) -> str:
    """Suffix a name-bearing prefix with its SAP table: ``<prefix>_<table>``.

    The suffix is the SAP table name in EVERY naming mode — it is what the
    suffix-based machinery keys on (field-mapper auto-correction, join hints,
    prompt rules), so it never varies with :class:`ColumnNamingMode`.
    """
    return f"{prefix}_{table.lower()}"
