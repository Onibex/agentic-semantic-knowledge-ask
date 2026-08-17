"""Source-system profiles + canonical type system.

Pure domain module (no I/O). Makes the SAP assumption *explicit, not hardcoded*:
the entity's ``source_system`` selects a :class:`SourceSystemProfile` whose
:class:`TypeMapper` knows how to read that system's raw column types and re-encode
them into a **source-agnostic canonical type** (``STRING(10)``, ``DECIMAL(15,2)``,
``DATE`` …).

Design ref: internal design doc (ITERATION_ENTITY_CREATION_REDESIGN) §3.1
(OQ#1: canonical type is authoritative, the mapper parses SAP / SQL / canonical
inputs and renders canonical). Rendering canonical → per-dialect physical type is
reserved for SQL-gen and intentionally not implemented here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Canonical bases (the source-agnostic vocabulary — design §3.1).
_BASES = ("STRING", "INTEGER", "DECIMAL", "DATE", "TIMESTAMP", "BOOLEAN")


@dataclass(frozen=True)
class CanonicalType:
    """A source-agnostic logical type. ``length`` applies to STRING; ``precision``
    /``scale`` to DECIMAL. ``render()`` is the authoritative string stored in YAML."""

    base: str
    length: int | None = None
    precision: int | None = None
    scale: int | None = None

    def render(self) -> str:
        if self.base == "STRING":
            return f"STRING({self.length})" if self.length else "STRING"
        if self.base == "DECIMAL":
            if self.precision and self.scale is not None and self.scale > 0:
                return f"DECIMAL({self.precision},{self.scale})"
            if self.precision:
                return f"DECIMAL({self.precision})"
            return "DECIMAL"
        return self.base

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.render()


# ── Raw-type → canonical lookups ─────────────────────────────────────────────

# SAP ABAP "internal type" single-char codes (what ``inttype`` carries).
_SAP_INTTYPE: dict[str, str] = {
    "C": "STRING",  # char
    "N": "STRING",  # numeric text — keep as STRING to preserve leading zeros
    "G": "STRING",  # string / SSTRING
    "X": "STRING",  # raw / hex
    "Y": "STRING",  # xstring
    "D": "DATE",  # DATS
    "T": "STRING",  # TIMS (time-of-day text; no TIME in the canonical vocab)
    "P": "DECIMAL",  # packed (quantities, currencies)
    "F": "DECIMAL",  # float
    "A": "DECIMAL",  # decfloat
    "E": "DECIMAL",  # decfloat34
    "I": "INTEGER",  # int4
    "S": "INTEGER",  # int2
    "B": "INTEGER",  # int1
}

# DDIC / SQL keyword aliases (when the raw type is a word, not a single-char code).
_KEYWORD_BASE: dict[str, str] = {
    # canonical (identity)
    "STRING": "STRING",
    "INTEGER": "INTEGER",
    "DECIMAL": "DECIMAL",
    "DATE": "DATE",
    "TIMESTAMP": "TIMESTAMP",
    "BOOLEAN": "BOOLEAN",
    # SQL strings
    "VARCHAR": "STRING",
    "VARCHAR2": "STRING",
    "NVARCHAR": "STRING",
    "NVARCHAR2": "STRING",
    "CHAR": "STRING",
    "NCHAR": "STRING",
    "BPCHAR": "STRING",  # Postgres blank-padded char
    "TEXT": "STRING",
    "CLOB": "STRING",
    "UUID": "STRING",
    "JSON": "STRING",
    "JSONB": "STRING",
    "BYTEA": "STRING",
    "STRING_": "STRING",
    # SQL integers
    "INT": "INTEGER",
    "INT2": "INTEGER",
    "INT4": "INTEGER",
    "INT8": "INTEGER",
    "BIGINT": "INTEGER",
    "SMALLINT": "INTEGER",
    "TINYINT": "INTEGER",
    "SERIAL": "INTEGER",
    # SQL numerics
    "NUMERIC": "DECIMAL",
    "NUMBER": "DECIMAL",
    "DEC": "DECIMAL",
    "FLOAT": "DECIMAL",
    "FLOAT4": "DECIMAL",  # Postgres real
    "FLOAT8": "DECIMAL",  # Postgres double precision
    "DOUBLE": "DECIMAL",
    "REAL": "DECIMAL",
    "MONEY": "DECIMAL",
    # SQL temporals
    "DATETIME": "TIMESTAMP",
    "TIMESTAMPTZ": "TIMESTAMP",
    "DATETIME2": "TIMESTAMP",  # SQL Server
    "DATETIMEOFFSET": "TIMESTAMP",  # SQL Server
    "SMALLDATETIME": "TIMESTAMP",  # SQL Server
    "TIMESTAMP_NTZ": "TIMESTAMP",  # Snowflake / Databricks
    "TIMESTAMP_LTZ": "TIMESTAMP",  # Snowflake
    "TIMESTAMP_TZ": "TIMESTAMP",  # Snowflake
    "DATETIME64": "TIMESTAMP",  # ClickHouse (sub-second precision param ignored)
    "DATE32": "DATE",  # ClickHouse extended-range date
    "TIME": "STRING",  # time-of-day text; no TIME in the canonical vocab (like TIMS)
    # SQL booleans
    "BOOL": "BOOLEAN",
    "BIT": "BOOLEAN",
    # ClickHouse scalars (SHOW CREATE TABLE spells them CamelCase; lookups are
    # uppercased). Int2/4/8 above are Postgres aliases; these are bit widths.
    "INT16": "INTEGER",
    "INT32": "INTEGER",
    "INT64": "INTEGER",
    "INT128": "INTEGER",
    "INT256": "INTEGER",
    "UINT8": "INTEGER",
    "UINT16": "INTEGER",
    "UINT32": "INTEGER",
    "UINT64": "INTEGER",
    "UINT128": "INTEGER",
    "UINT256": "INTEGER",
    "FLOAT32": "DECIMAL",
    "FLOAT64": "DECIMAL",
    "FIXEDSTRING": "STRING",
    "ENUM8": "STRING",
    "ENUM16": "STRING",
    "ENUM": "STRING",
    "IPV4": "STRING",
    "IPV6": "STRING",
    # MySQL / SQL Server / Snowflake extras
    "MEDIUMINT": "INTEGER",
    "LONGTEXT": "STRING",
    "MEDIUMTEXT": "STRING",
    "TINYTEXT": "STRING",
    "NTEXT": "STRING",
    "UNIQUEIDENTIFIER": "STRING",
    "VARIANT": "STRING",
    # DDIC datatypes (multi-char) occasionally surface instead of inttype
    "DATS": "DATE",
    "TIMS": "STRING",
    "NUMC": "STRING",
    "CUKY": "STRING",
    "UNIT": "STRING",
    "LANG": "STRING",
    "CLNT": "STRING",
    "CURR": "DECIMAL",
    "QUAN": "DECIMAL",
    "FLTP": "DECIMAL",
    "RAW": "STRING",
    "SSTRING": "STRING",
    "STRG": "STRING",
}

_PAREN_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\)\s*$")
_BARE_WORD_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*?)\s*$")
_SAP_CODE_RE = re.compile(r"^\s*([A-Za-z])\s*(\d+)\s*$")

# Keyword with arbitrary parenthesized args — catches vendor spellings whose
# params are not plain integers (``DateTime('UTC')``, ``DateTime64(3, 'UTC')``,
# ``Enum8('new' = 1, 'done' = 2)``). The keyword decides the base; any LEADING
# integer args are kept as params (a trailing timezone/label is dropped).
_ANY_PAREN_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*\((.*)\)\s*$", re.DOTALL)

# Transparent wrappers: the physical column's logical type is the INNER type.
# ClickHouse `Nullable(X)` / `LowCardinality(X)` (nesting occurs in the wild:
# `LowCardinality(Nullable(String))`).
_WRAPPER_RE = re.compile(
    r"^\s*(?:NULLABLE|LOWCARDINALITY)\s*\((.*)\)\s*$", re.IGNORECASE | re.DOTALL
)

# ClickHouse fixed-precision decimals: the single param is the SCALE; precision
# is fixed by the bit width. `Decimal64(7)` ≡ `Decimal(18, 7)`.
_CLICKHOUSE_DECIMAL_PRECISION: dict[str, int] = {
    "DECIMAL32": 9,
    "DECIMAL64": 18,
    "DECIMAL128": 38,
    "DECIMAL256": 76,
}

# Multi-word ANSI spellings, rewritten to their single-word alias BEFORE keyword
# lookup (applied case-insensitively on the whitespace-collapsed string).
_MULTIWORD_REWRITES: tuple[tuple[str, str], ...] = (
    ("TIMESTAMP WITHOUT TIME ZONE", "TIMESTAMP"),
    ("TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ"),
    ("TIME WITHOUT TIME ZONE", "TIME"),
    ("TIME WITH TIME ZONE", "TIME"),
    ("DOUBLE PRECISION", "DOUBLE"),
    ("NATIONAL CHARACTER VARYING", "NVARCHAR"),
    ("NATIONAL CHARACTER", "NCHAR"),
    ("CHARACTER VARYING", "VARCHAR"),
    ("CHARACTER", "CHAR"),
    ("LONG VARCHAR", "VARCHAR"),
)


class TypeMapper:
    """Parses raw column types (SAP ``C10`` / SQL ``VARCHAR(10)`` / canonical
    ``STRING(10)``) into a :class:`CanonicalType` and renders canonical strings.

    Tolerant + idempotent: ``parse(render(parse(x))) == parse(x)``. One instance
    is shared across profiles in v1; the per-profile seam exists so a future
    source can override ambiguous interpretations without touching callers.
    """

    def parse(self, raw: str | None) -> CanonicalType:
        s = " ".join((raw or "").split())  # collapse newlines/runs: Decimal(76,\n 7)
        if not s:
            return CanonicalType("STRING")

        # 0a. Multi-word ANSI spellings → single-word alias (TIMESTAMP WITH TIME
        #     ZONE, DOUBLE PRECISION, CHARACTER VARYING(50), …).
        upper = s.upper()
        for phrase, alias in _MULTIWORD_REWRITES:
            if upper.startswith(phrase):
                s = alias + s[len(phrase) :]
                break

        # 0b. Unwrap transparent wrappers — the logical type is the inner type.
        #     Depth-capped so a pathological input can't loop.
        for _ in range(4):
            m = _WRAPPER_RE.match(s)
            if not m:
                break
            s = m.group(1).strip()

        # 1. Parenthesized keyword: STRING(10) / VARCHAR(10) / DECIMAL(15,2)
        m = _PAREN_RE.match(s)
        if m:
            word = m.group(1).upper()
            a = int(m.group(2))
            b = int(m.group(3)) if m.group(3) is not None else None
            fixed = _CLICKHOUSE_DECIMAL_PRECISION.get(word)
            if fixed:
                return CanonicalType("DECIMAL", precision=fixed, scale=a)
            base = _KEYWORD_BASE.get(word)
            if base:
                return self._with_params(base, a, b)

        # 1b. Keyword with non-integer args: DateTime('UTC') / DateTime64(3,'UTC')
        #     / Enum8('a' = 1). The keyword decides; leading integer args survive.
        m = _ANY_PAREN_RE.match(s)
        if m:
            word = m.group(1).upper()
            base = _KEYWORD_BASE.get(word)
            if base:
                ints: list[int] = []
                for part in m.group(2).split(","):
                    part = part.strip()
                    if part.isdigit():
                        ints.append(int(part))
                    else:
                        break
                return self._with_params(
                    base, ints[0] if ints else None, ints[1] if len(ints) > 1 else None
                )

        # 2. Bare keyword (no trailing digits): DATE / INTEGER / VARCHAR / DEC
        m = _BARE_WORD_RE.match(s)
        if m:
            word = m.group(1).upper()
            if word in _CLICKHOUSE_DECIMAL_PRECISION:
                return CanonicalType("DECIMAL", precision=_CLICKHOUSE_DECIMAL_PRECISION[word])
            base = _KEYWORD_BASE.get(word)
            if base:
                return CanonicalType(base)
            # single-letter SAP inttype with no length (e.g. "P", "C", "D")
            if len(word) == 1 and word in _SAP_INTTYPE:
                return CanonicalType(_SAP_INTTYPE[word])

        # 3. SAP single-char code + length: C10, P15, D8, N6
        m = _SAP_CODE_RE.match(s)
        if m:
            letter = m.group(1).upper()
            leng = int(m.group(2))
            base = _SAP_INTTYPE.get(letter)
            if base:
                return self._with_params(base, leng, None)

        # 4. Unknown → STRING (safest, never raises)
        return CanonicalType("STRING")

    def render(self, t: CanonicalType) -> str:
        return t.render()

    def canonical(self, raw: str | None) -> str:
        """Convenience: raw → canonical string (the value stored in YAML)."""
        return self.parse(raw).render()

    @staticmethod
    def _with_params(base: str, a: int | None, b: int | None) -> CanonicalType:
        if base == "STRING":
            return CanonicalType("STRING", length=a or None)
        if base == "DECIMAL":
            return CanonicalType("DECIMAL", precision=a or None, scale=b)
        # INTEGER / DATE / TIMESTAMP / BOOLEAN ignore params
        return CanonicalType(base)


# ── Source-system profiles ───────────────────────────────────────────────────


@dataclass(frozen=True)
class SourceSystemProfile:
    """Parameterizes derivation + prompts for one source ERP.

    ``type_mapper`` is the only piece the EntityDeriver consumes today.
    ``prompt_fragment`` is surfaced to AI prompts (DDL/enrichment) so the model
    reasons in the right system's terms. Naming/validation rules are folded into
    the mapper for v1 and can grow into dedicated fields when a source needs them.
    """

    key: str
    label: str
    type_mapper: TypeMapper
    prompt_fragment: str = ""


_SHARED_MAPPER = TypeMapper()

_PROFILES: dict[str, SourceSystemProfile] = {
    "s4h": SourceSystemProfile(
        key="s4h",
        label="SAP S/4HANA",
        type_mapper=_SHARED_MAPPER,
        prompt_fragment="Source system is SAP S/4HANA (ABAP DDIC types like C, N, P, D).",
    ),
    "ecc": SourceSystemProfile(
        key="ecc",
        label="SAP ECC",
        type_mapper=_SHARED_MAPPER,
        prompt_fragment="Source system is SAP ECC (ABAP DDIC types like C, N, P, D).",
    ),
    "generic": SourceSystemProfile(
        key="generic",
        label="Generic SQL",
        type_mapper=_SHARED_MAPPER,
        prompt_fragment="Source system is a generic ANSI SQL database.",
    ),
    # Stubs — share the tolerant ANSI mapper until they earn dedicated rules.
    "salesforce": SourceSystemProfile(
        key="salesforce",
        label="Salesforce",
        type_mapper=_SHARED_MAPPER,
        prompt_fragment="Source system is Salesforce.",
    ),
    "odoo": SourceSystemProfile(
        key="odoo",
        label="ODOO",
        type_mapper=_SHARED_MAPPER,
        prompt_fragment="Source system is ODOO.",
    ),
}

_DEFAULT_PROFILE = _PROFILES["generic"]


def get_profile(source_system: str | None) -> SourceSystemProfile:
    """Resolve the profile for an entity's ``source_system``.

    Keys on the lowercased first token, so a short entity key (``"s4h_100"`` /
    ``"S4H"``) and a human Organization label (``"SAP S/4HANA 2023"``) both
    resolve. Order: exact profile key → human-label prefix alias → ``generic``
    ANSI fallback (never raises)."""
    if not source_system:
        return _DEFAULT_PROFILE
    raw = str(source_system).strip().lower()
    if not raw:
        return _DEFAULT_PROFILE
    key = raw.split("_", 1)[0].split()[0]
    # Exact profile key wins (the entity's own short key, e.g. "s4h" / "s4h_100").
    if key in _PROFILES:
        return _PROFILES[key]
    # Human-label heuristics on the FULL string — Organization.source_system is
    # free text like "SAP S/4HANA 2023" or "SAP ECC 6.0". Check ECC before the
    # generic "sap" signal, since an ECC label also contains "sap".
    if "ecc" in raw:
        return _PROFILES["ecc"]
    if "s/4" in raw or "s4h" in raw or "s4hana" in raw or "sap" in raw:
        return _PROFILES["s4h"]
    if "salesforce" in raw or "sfdc" in raw:
        return _PROFILES["salesforce"]
    if "odoo" in raw:
        return _PROFILES["odoo"]
    return _DEFAULT_PROFILE


def list_profiles() -> list[dict[str, str]]:
    """All code-defined profiles as ``[{key, label}]`` — drives the DDL form's
    source-system selector so the UI never hardcodes the list."""
    return [{"key": p.key, "label": p.label} for p in _PROFILES.values()]
