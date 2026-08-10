import logging
import re
import unicodedata
from typing import Any

from pydantic import ValidationError

from ..domain.entity_deriver import EntityDeriver, silver_column_name
from ..domain.nodes import (
    AskIdGenerator,
    BronzeField,
    BronzeNode,
    Grain,
    JoinCondition,
    SilverField,
    SilverNode,
    normalize_business_process,
)
from ..domain.source_profiles import get_profile
from .sap_schemas import SapRootSchema

logger = logging.getLogger(__name__)

# SAP "control flag" values that mark a related table as configuration/reference.
_CONFIG_FLAGS = {"C", "G", "E", "S", "W"}

# ── Upstream normalisation ───────────────────────────────────────────────────
# Shims over defects in the OneConnect SAP Data Modeler, not ASK design. Each is
# registered in the internal upstream defect report with the condition under
# which it can be RETIRED. Do not grow them without adding a matching entry
# there. `business_process` normalisation lives on the domain
# model (nodes.normalize_business_process) so every write path gets it, not just
# this parser.

# UP-3 / UP-4: `info.type` only ever emits `D` (master) and `T` (transactional).
# `M` has never appeared, and `C` (configuration) is not implemented upstream yet.
_CLASSIFICATION_ALIASES = {"D": "M"}

# ── Alias/identifier hygiene ─────────────────────────────────────────────────
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


def _sanitize_token(raw: Any, *, fallback: str, upper: bool = False) -> str:
    """Coerce one SAP alias / table name into a printable-ASCII snake_case token.

    NFKD-folds first so accented Latin text degrades to its base letters
    ("año" → "ano") instead of losing the character outright, then drops what is
    still non-printable / non-ASCII and maps the remaining illegal ASCII to "_".

    ``upper=True`` (entity alias) forces UPPER_SNAKE — what 48/48 real
    ``alias_tabname`` values already are; ``upper=False`` (field aliases, id
    segments) forces lowercase. Falls back to ``fallback`` when sanitation
    leaves nothing usable: ``BronzeField.alias`` / ``BronzeNode.alias`` are
    both required and the alias is the last segment of the bronze id, so it can
    never be blank.
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


def _dedup_alias(alias: str, used: set[str]) -> str:
    """ONE dedup-suffix style ("_2", "_3", …), applied ONLY on a real in-file
    collision — never on a first occurrence.

    The two suffix styles in the shipped corpus (``unit1`` vs ``color_1``) come
    from the upstream exporter, not from here: the source JSONs already carry
    ``unit`` / ``unit1`` / ``unit11`` as distinct aliases and have ZERO
    per-table alias collisions. This is therefore a defensive guard for
    ``BronzeNode``'s field-alias-uniqueness rule, not a mass renamer.
    """
    if alias not in used:
        used.add(alias)
        return alias
    n = 2
    while f"{alias}_{n}" in used:
        n += 1
    out = f"{alias}_{n}"
    used.add(out)
    return out


def _sap_type_code(inttype: Any, leng: Any) -> str:
    """Raw SAP type code, e.g. ``C10`` / ``P15`` / ``D8``.

    ``SapColumnSchema`` declares ``leng: int | str | None = 0`` and
    ``inttype: str | None = "C"``, so a missing length is coerced away instead
    of producing the garbage string ``"CNone"`` the old ``f"{inttype}{leng}"``
    emitted (which silently fell through the type mapper's unknown→STRING rule).
    """
    letter = str(inttype or "C").strip().upper()
    try:
        n = int(str(leng).strip())
    except (TypeError, ValueError):
        n = 0
    return f"{letter}{n}" if n > 0 else letter


class SapJsonParser:
    """Translates the proprietary SAP export JSON into the domain model (ASK Spec v1.0).

    Strictly typed: the payload is validated by Pydantic before anything is read.
    """

    def __init__(self, deriver: EntityDeriver | None = None) -> None:
        # Shared derivation heuristics — the SAME EntityDeriver the admin
        # Manual/DDL path runs at /import. Delegating keeps both ingestion
        # paths in lock-step (DIP); see ITERATION_ENTITY_CREATION_REDESIGN.md.
        self._deriver = deriver or EntityDeriver()

    def parse_to_domain(self, raw_data: dict[str, Any]) -> tuple[list[BronzeNode], SilverNode]:
        """Main orchestrator — reads like a table of contents."""
        # 1. Strict validation (the Pydantic shield)
        valid_data = self._validate_payload(raw_data)

        # 2. Extract global metadata
        meta = self._extract_global_metadata(valid_data)

        # 3. Determine the entity role (fact / dimension / reference)
        meta["entity_role"] = self._determine_entity_role(
            classification=meta["classification"],
            columns=valid_data.columns,
            relations=valid_data.relations,
            entity_name=meta["entity_name"],
        )

        # 4. Build the Bronze nodes and extract the Silver fields
        bronze_nodes, silver_fields, composed_of_ids = self._build_bronze_layer(
            columns=valid_data.columns,
            relations=valid_data.relations,
            source_system=meta["source_system"],
            source_system_no=meta["source_system_no"],
        )

        # 5. Build the join graph
        join_graph = self._build_join_graph(valid_data.relations)

        # 6. Compute the entity grain (needs the join graph from step 5 — the
        #    predicates decide which composed tables widen the grain at all)
        grain_obj = self._calculate_grain(bronze_nodes, meta["entity_name"], join_graph)

        # 6b. Declare each measure's fan-out (needs the grain from step 6). A
        #     denormalised Silver restates a measure on every row its own table did
        #     not produce — a header amount on every item, a stock level on every
        #     movement — and until this was emitted the SQL generator had to infer it
        #     from prose and measurably did not. Derived, never curated; fill-when-
        #     absent, so it cannot overwrite an author.
        filled = self._deriver.apply_measure_fanout(
            silver_fields,
            entity_grain=list(grain_obj.entity_grain),
            join_graph=join_graph,
        )
        if filled:
            logger.info(
                "Declared measure fan-out on %d of %d fields for '%s'.",
                filled,
                len(silver_fields),
                meta["entity_name"],
            )

        # 7. Build the final Silver node
        silver_node = self._build_silver_node(
            meta=meta,
            valid_info_id=valid_data.info.id,
            grain_obj=grain_obj,
            composed_of_ids=composed_of_ids,
            join_graph=join_graph,
            silver_fields=silver_fields,
        )

        return bronze_nodes, silver_node

    # ─── PRIVATE SINGLE-RESPONSIBILITY HELPERS ───

    def _validate_payload(self, raw_data: dict[str, Any]):
        try:
            return SapRootSchema.model_validate(raw_data)
        except ValidationError as e:
            problems = [f"'{err['loc'][-1]}': {err['msg']}" for err in e.errors()]
            raise ValueError(
                f"The JSON does not match the required specification: {', '.join(problems)}"
            )

    def _extract_global_metadata(self, valid_data) -> dict[str, Any]:
        """Extract global metadata, mapping the SAP tags per ASK Spec v1.0."""
        version_val = str(valid_data.info.version) if valid_data.info.version else "1"
        if version_val == "0":
            version_val = "1"

        # entity_name (used for ids, filenames, grains) comes from the top-level
        # `entity` — a clean identifier such as "PRODUCTION_CONFIRMATION". It used
        # to come from `info.description`, but description now carries the rich
        # semantic text for retrieval and cannot be used as an id. Falls back to
        # `info.description` when `entity` is absent (older JSONs).
        raw_entity = (getattr(valid_data, "entity", "") or "").strip()
        if not raw_entity:
            raw_entity = valid_data.info.description.strip()
        entity_name = raw_entity.lower()

        return {
            "source_system": valid_data.info.tag2.lower(),
            "source_system_no": int(valid_data.info.tag3),
            # NOTE: `module` comes from `dataprodclass.mmodule`, NOT from Tag 1.
            # ASK Spec Sec 6.1 assigns Tag 1 to BOTH `business_process` and `module`,
            # but `info.tag1` is byte-identical to `info.domainv` in every export and
            # holds a process name ("ORDER TO CASH"), never a module code — so that
            # spec row is a documentation defect, not a design. Lowercase here because
            # this feeds the ID token; the FIELD is upper-cased at `_build_silver_node`
            # (spec Sec 21.1 rule 1 governs ids, not the field).
            "module": valid_data.dataprodclass.mmodule.lower(),
            "business_process": normalize_business_process(valid_data.info.domainv),
            # Per ASK Spec 6.1: ASK tag1 = export Tag 4, ASK tag2 = export Tag 5.
            # Secondary categorization for catalog faceting — now modelled on
            # SilverNode/GoldNode and indexed, where before both were silently
            # dropped by Pydantic's extra='ignore'.
            "tag1": valid_data.info.tag4,
            "tag2": valid_data.info.tag5,
            "entity_name": entity_name,
            "classification": self._normalize_classification(
                valid_data.info.type, valid_data.relations
            ),
            "version": version_val,
            # description flows 1:1 from the JSON to the YAML to feed retrieval
            # (BM25 + embedding). The parser no longer fabricates a templated
            # description; the ingestor respects what the JSON author wrote.
            "description": valid_data.info.description,
        }

    @staticmethod
    def _normalize_classification(raw_type: str | None, relations: list) -> str:
        """Map the Data Modeler's ``info.type`` onto the ASK M/T/C vocabulary.

        Two upstream defects are absorbed here (61_UPSTREAM_DEFECT_REPORT.md):

        * **UP-4** — ``C`` (Configuration) is not implemented upstream, so a
          configuration entity arrives as ``D``. SAP itself supplies the missing
          discriminator: when EVERY relation carries a non-application delivery
          class (``CONTFLAG ∈ {C,G,E,S,W}``), the Data Product is customizing
          data. This is the escape hatch ASK Spec Sec 6.1 designed for exactly
          this case, and it is measured to be exact on the shipped corpus.
          We write ``C`` rather than ``M`` deliberately: under ``M`` the admin
          save path re-derives ``entity_role`` with ``relations_present=None``
          and permanently demotes the entity back to ``dimension``, whereas the
          ``C`` branch is unconditional and therefore stable on every write path.
        * **UP-3** — ``D`` means *master*, not "document". Anything left after
          the configuration test maps ``D → M``. ``invoice`` is the one entity
          this gets wrong, and that is an upstream mis-tag to be fixed at source
          rather than special-cased here.
        """
        code = str(raw_type or "").strip().upper()
        if relations and all(getattr(rel, "contflag", "") in _CONFIG_FLAGS for rel in relations):
            return "C"
        return _CLASSIFICATION_ALIASES.get(code, code)

    def _determine_entity_role(
        self, classification: str, columns: list, relations: list, entity_name: str
    ) -> str:
        # Delegated to EntityDeriver (single source of truth). This method
        # computes the SAP-specific signals; the decision tree lives in the
        # deriver so the Manual/DDL path derives identically.
        all_relations_config = (
            all(getattr(rel, "contflag", "") in _CONFIG_FLAGS for rel in relations)
            if relations
            else False
        )
        return self._deriver.entity_role(
            classification=classification,
            is_item="item" in entity_name.lower(),
            has_measure=any(col.inttype == "P" for col in columns),
            relations_present=bool(relations),
            all_relations_config=all_relations_config,
        )

    def _build_bronze_layer(
        self, columns: list, relations: list, source_system: str, source_system_no: int
    ) -> tuple[list[BronzeNode], list[SilverField], list[str]]:
        # `description_table` is now declared on SapRelationSchema, so the real
        # table label from the export reaches the YAML. Empty values still fall
        # back to the placeholder — `.strip() or` and not `getattr(..., default)`,
        # which never fired because the attribute always exists.
        table_descriptions = {
            rel.tabname: (getattr(rel, "description_table", "") or "").strip()
            or f"SAP Table {rel.tabname}"
            for rel in relations
            if rel.tabname
        }

        # The entity's own `source_system` selects the TypeMapper that re-encodes
        # raw SAP `(inttype, leng)` into the canonical ANSI vocabulary. Resolved
        # once per parse; all profiles share one mapper instance.
        mapper = get_profile(source_system).type_mapper

        grouped_tables = self._group_columns_by_table([col.model_dump() for col in columns])
        bronze_nodes, silver_fields, composed_of_ids = [], [], []

        for tabname, table_data in grouped_tables.items():
            alias_tabname = _sanitize_token(
                table_data["alias_tabname"], fallback=tabname, upper=True
            )
            description_table = table_descriptions.get(tabname, f"SAP Table {tabname}")

            # `name` keeps the SAP table name verbatim (Bronze mirrors the source);
            # only the ID SEGMENT is sanitized, so a namespaced table like
            # /BEV1/RBVBAP yields a grammar-valid id instead of a hard reject.
            bronze_id = AskIdGenerator.generate_bronze_id(
                source_system, _sanitize_token(tabname, fallback="table"), alias_tabname
            )
            composed_of_ids.append(bronze_id)

            fields_dict: dict[str, BronzeField] = {}
            primary_keys: list[str] = []
            used_aliases: set[str] = set()

            for col in table_data["columns"]:
                fldname = col.get("fldname", "")
                is_key = col.get("key_field") == "X"
                inttype = col.get("inttype", "C")
                # ONE type vocabulary across all three layers: the canonical ANSI
                # encoding. `field_role` still keys off the raw SAP `inttype`
                # below, which is why the raw letter is kept in scope here.
                canonical_type = mapper.canonical(_sap_type_code(inttype, col.get("leng")))
                description_field = col.get("description_field", "")

                # ── Row-level dedup (root cause of the duplicated primary_key) ──
                # The SAP exports repeat whole (tabname, fldname) rows — 6 of the
                # 17 shipped payloads do, up to 4x (BSEG 4x, KNVP 4x, MARD 3x,
                # BKPF 3x…). `fields_dict[fldname] = …` always collapsed them, but
                # `primary_keys.append` and `silver_fields.append` did not — which
                # is exactly why 9 shipped bronze YAMLs carry a 2-4x duplicated
                # primary_key and 4 shipped silver YAMLs carry duplicated field
                # names. Guarding the ROW fixes both with one branch and keeps
                # every downstream list order-preserving and single-valued.
                if fldname in fields_dict:
                    # First occurrence wins for type/alias/description (verified
                    # identical in every repeat group of the real payloads). The
                    # key flag is still OR-ed in so an inconsistent export can
                    # never silently drop a PK member.
                    if is_key and fldname not in primary_keys:
                        primary_keys.append(fldname)
                        fields_dict[fldname].key_field = True
                    continue

                if is_key:
                    primary_keys.append(fldname)

                fields_dict[fldname] = BronzeField(
                    # Canonical ANSI type: STRING(10) / DECIMAL(15) / DATE.
                    # STRING(n) absorbs SAP CHAR, NUMC and TIMS — the CHAR-vs-NUMC
                    # (zero-padding) and time-of-day distinctions are NOT
                    # recoverable from the stored type; see "What canonical drops"
                    # in docs/semantic-layer/BRONZE_LAYER.md.
                    type=canonical_type,
                    alias=_dedup_alias(
                        _sanitize_token(col.get("alias_fldname"), fallback=fldname),
                        used_aliases,
                    ),
                    key_field=is_key,
                    description=description_field,
                )

                # Semantic classification (ASK Spec 6.2) — delegated to the deriver.
                semantic_role = self._deriver.field_role_for_inttype(
                    key_field=is_key, inttype=inttype
                )

                silver_fields.append(
                    SilverField(
                        # Same helper the grain derivation uses, so a grain member
                        # and the field it names can never drift apart.
                        name=silver_column_name(tabname, fldname),
                        source=f"{tabname}.{fldname}",
                        field_role=semantic_role,
                        # Same canonical encoding as Bronze. This closes a
                        # long-standing split: `EntityDeriver._complete_silver_gold`
                        # already rewrote Silver types to canonical on every admin
                        # save, so a Silver touched through the SPA was canonical
                        # while the same Silver produced here was raw SAP. Silver
                        # `raw_yaml` reaches the SQL-generation prompt, so this
                        # changes what the model reads — see the one-vocabulary
                        # note in docs/semantic-layer/BRONZE_LAYER.md §3.6.
                        type=canonical_type,
                        description=description_field,
                    )
                )

            if not primary_keys:
                # Decision (owner, 2026-08-03): WARN, don't reject. `key_field`
                # is the data-product author's key declaration and ASK consumes
                # it as authority — a table with none declared is an upstream
                # authoring error (seen live: VBFA in `sales_order`, whose S/4
                # key RUUID was left out of the selection), and the ASK author
                # escalates it to the Data Modeler admin instead of being
                # blocked here. The Bronze ingests keyless; `structural_grain`
                # then treats the table as contributing no key columns, so the
                # Silver grain cannot see this table's fan-out. Note the data
                # itself is suspect too: upstream materializes keyed-by-nothing
                # tables collapsed to one row per collision.
                logger.warning(
                    "table '%s' has no column flagged key_field='X' in the "
                    "export — ingesting a keyless Bronze. Its rows cannot be "
                    "uniquely identified and it contributes nothing to the "
                    "Silver grain; report the missing key declaration to the "
                    "data-product author (Data Modeler).",
                    tabname,
                )

            bronze_nodes.append(
                BronzeNode(
                    id=bronze_id,
                    source_system=source_system,
                    source_system_id=source_system_no,
                    name=tabname,
                    alias=alias_tabname,
                    description=description_table,
                    primary_key=primary_keys,
                    fields=fields_dict,
                )
            )

        return bronze_nodes, silver_fields, composed_of_ids

    def _build_join_graph(self, relations: list) -> list[JoinCondition]:
        return self._deriver.derive_join_graph(relations)

    def _calculate_grain(
        self,
        bronze_nodes: list[BronzeNode],
        entity_name: str,
        join_graph: list[JoinCondition],
    ) -> Grain:
        # Keys are passed KEYED BY TABLE (not flattened): the grain derivation needs
        # to know which table owns each key column, both to publish the
        # `<column>_<table>` name and to tell `VBAK.VBELN` (the order) apart from
        # `VBFA.VBELN` (the subsequent document) — flattening merged those two by
        # bare name. The join graph comes in because it decides which tables
        # multiply rows at all; see `EntityDeriver.structural_grain`.
        #
        # Still unaffected by the row-level dedup in `_build_bronze_layer`: the
        # derivation de-duplicates per table, so removing per-node repeats
        # beforehand only drops occurrences it would drop anyway. Do NOT conclude
        # the upstream dedup is redundant — it also fixes the PERSISTED bronze
        # `primary_key` and the `primary_keys` field written verbatim to
        # OpenSearch (opensearch_repository.py:237).
        table_keys = {b_node.name: list(b_node.primary_key) for b_node in bronze_nodes}
        return self._deriver.derive_grain(table_keys, entity_name, join_graph=join_graph)

    def _build_silver_node(
        self,
        meta: dict,
        valid_info_id: Any,
        grain_obj: Grain,
        composed_of_ids: list[str],
        join_graph: list[JoinCondition],
        silver_fields: list[SilverField],
    ) -> SilverNode:
        return SilverNode(
            id=AskIdGenerator.generate_silver_id(
                meta["source_system"], meta["module"], meta["entity_name"]
            ),
            # Follows the strict internal_id format
            internal_id=f"{meta['source_system']}_{meta['source_system_no']}_{valid_info_id}",
            layer="silver",
            version=meta["version"],
            source_system=meta["source_system"],
            source_system_no=meta["source_system_no"],
            business_process=meta["business_process"],
            module=meta["module"].upper(),
            tag1=meta["tag1"],
            tag2=meta["tag2"],
            name=meta["entity_name"],
            classification=meta["classification"],
            description=meta["description"],
            entity_role=meta["entity_role"],
            grain=grain_obj,
            composed_of=composed_of_ids,
            join_graph=join_graph,
            fields=silver_fields,
        )

    def _group_columns_by_table(self, columns_raw: list[dict]) -> dict[str, dict]:
        grouped = {}
        for col in columns_raw:
            tabname = col.get("tabname")
            if not tabname:
                continue
            if tabname not in grouped:
                # `.get(k, default)` does NOT cover an empty VALUE: a column with
                # alias_tabname="" never reaches the default, and the id came out
                # as 'bronze_s4h_vbak_' (now rejected by the bronze id grammar).
                grouped[tabname] = {
                    "alias_tabname": (col.get("alias_tabname") or "").strip() or tabname,
                    "columns": [],
                }
            grouped[tabname]["columns"].append(col)
        return grouped
