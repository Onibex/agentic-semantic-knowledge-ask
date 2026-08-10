"""Read and write YAML files from the semantic layer workspace.

Reads + writes go through ruamel.yaml round-trip so comments, key order and
multi-line string styles survive admin edits.
Field-level merge rules by layer:
  Bronze  — enrichable props: alias, description (per field)
  Silver/Gold — enrichable props: field_role, description, aggregation_behavior (per field)
              — join_graph is fully replaceable
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from ask_knowledge_graph.infrastructure.yaml_serializer import (
    AskYamlSerializer,
    load_yaml_text,
)

from ..config import get_settings
from ..models.viz_models import (
    VizField,
    VizFieldUpdate,
    VizGrain,
    VizJoinCondition,
    VizLayer,
    VizMeta,
    VizRelationship,
    VizYAMLNode,
    VizYAMLSummary,
    VizYAMLUpdateRequest,
)
from .conflict_store import ConflictStore
from .enrichments_store import EnrichmentsStore
from .provenance_engine import (
    ENRICHABLE_PROPS,
    compute_enrichments_bronze,
    compute_enrichments_silver,
)

logger = logging.getLogger(__name__)

# Structural fields that the PUT endpoint must never overwrite.
_READONLY_TOP_LEVEL = {"id", "layer", "source_system", "composed_of", "primary_key", "version"}


class YAMLNotFoundError(Exception):
    def __init__(self, yaml_id: str) -> None:
        super().__init__(f"YAML '{yaml_id}' not found in workspace")
        self.yaml_id = yaml_id


class YAMLFileService:
    def __init__(self, workspace_path: str = "", repo_root: str = "") -> None:
        if not workspace_path or not repo_root:
            # The boot lifespan in main.py is the authoritative gate, but tests
            # that instantiate the service directly still benefit from a clear
            # error rather than a silent CWD-relative resolve (the old default
            # ``"workspace/ask"`` / ``"."`` is what caused YAML commits to land
            # in the code repo's .git pre-split).
            raise ValueError(
                "YAMLFileService requires workspace_path and repo_root. "
                "Set WORKSPACE_PATH and REPO_ROOT env vars (Settings reads them) "
                "or pass them explicitly."
            )
        self.workspace = Path(workspace_path)
        self.repo_root = Path(repo_root).resolve()
        # Conflicts now live in a sidecar under .sap_baseline/ (Pass H), so
        # the YAML body stays clean. We still hydrate VizMeta.conflicts on
        # read so the API contract is unchanged for the SPA.
        try:
            settings = get_settings()
            baseline_path = settings.baseline_path
        except Exception:  # noqa: BLE001 — tests may not have settings loaded
            baseline_path = ".sap_baseline"
        baseline_root = self.repo_root / baseline_path
        self._conflict_store = ConflictStore(baseline_root)
        # Sidecar for _meta.field_enrichments / entity_enrichments — keeps
        # framework provenance OUT of the YAML so git diffs stay clean.
        self._enrichments_store = EnrichmentsStore(baseline_root)
        # Parse-once catalog cache (see _ensure_cache). Guards the read path
        # (list_yamls / get_yaml(s)) from re-globbing + re-parsing the whole
        # workspace on every call.
        self._cache_lock = threading.RLock()
        self._cache: dict | None = None

    # ── Public API ───────────────────────────────────────────────────────────

    def _iter_yaml_files(self):
        """Yield every YAML in the workspace, accepting both .yaml and .yml.

        Gold data products in this workspace use the .yml extension; Bronze/Silver
        use .yaml. Both must be visible to the visualizer.
        """
        yield from self.workspace.rglob("*.yaml")
        yield from self.workspace.rglob("*.yml")

    # ── Catalog cache (parse-once) ─────────────────────────────────────────────
    # list_yamls / get_yaml(s) used to rglob + ruamel-parse the WHOLE workspace
    # on EVERY call, so a canvas "+" burst (each add does getYaml + N bronze
    # getYamls) re-scanned + re-parsed every file N×(1+bronzes) times — the main
    # source of the "adds very slowly" lag. We now parse once into an in-memory
    # index keyed by id and reuse it until the workspace changes. The change check
    # is a stat-only signature (mtime_ns + size per file) — far cheaper than
    # re-parsing — and local writes invalidate explicitly so a save is reflected
    # immediately regardless of filesystem mtime resolution; external changes
    # (git publish / restore) are caught by the signature.

    def _workspace_signature(self) -> tuple:
        sig: list[tuple[str, int, int]] = []
        for f in self._iter_yaml_files():
            try:
                st = f.stat()
            except OSError:
                continue
            sig.append((str(f), st.st_mtime_ns, st.st_size))
        sig.sort()
        return tuple(sig)

    def _ensure_cache(self) -> dict:
        """Return the parsed catalog, rebuilding only when the workspace changed.

        Cache shape: ``{"sig": <signature>, "raws": [(Path, raw)], "by_id":
        {id: (raw, Path)}}``. Cached ``raw`` dicts are served READ-ONLY to the
        read methods (which project into fresh Pydantic models); the write path
        re-loads from disk via ``_load_raw`` and never mutates a cached dict.
        """
        with self._cache_lock:
            sig = self._workspace_signature()
            cache = self._cache
            if cache is not None and cache["sig"] == sig:
                return cache
            raws: list[tuple[Path, dict]] = []
            by_id: dict[str, tuple[dict, Path]] = {}
            for yaml_file in sorted(self._iter_yaml_files()):
                try:
                    raw = self._load_raw(yaml_file)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Skipping %s: %s", yaml_file, exc)
                    continue
                if not raw or "id" not in raw:
                    continue
                raws.append((yaml_file, raw))
                by_id.setdefault(str(raw["id"]), (raw, yaml_file))
            cache = {"sig": sig, "raws": raws, "by_id": by_id}
            self._cache = cache
            return cache

    def _invalidate_cache(self) -> None:
        """Drop the cached catalog so the next read re-parses. Called after every
        local write (update / import / delete / create)."""
        with self._cache_lock:
            self._cache = None

    def list_yamls(self, layer: VizLayer | None = None) -> list[VizYAMLSummary]:
        """Catalog rows, including the §3.1 entity header.

        The header + counts are FREE here: ``_ensure_cache`` has already parsed
        every document in full, so this is a projection over dicts in memory, not
        extra I/O. The old 6-field summary discarded them, which is why the catalog
        page could show nothing but name / layer / module.
        """
        result: list[VizYAMLSummary] = []
        for yaml_file, raw in self._ensure_cache()["raws"]:
            try:
                node_layer = self._parse_layer(raw.get("layer", ""))
                if node_layer is None:
                    continue
                if layer and node_layer != layer:
                    continue
                module = self._extract_module(raw)
                grain = self._extract_grain(raw)
                field_count, measure_count = self._count_fields(raw, node_layer)
                result.append(
                    VizYAMLSummary(
                        id=raw["id"],
                        layer=node_layer,
                        module=module,
                        name=raw.get("name") or raw.get("alias") or raw["id"],
                        alias=raw.get("alias"),
                        file_path=self._rel_posix(yaml_file),
                        entity_grain=grain.entity_grain if grain else [],
                        business_grain=grain.business_grain if grain else None,
                        primary_key=[str(k) for k in raw.get("primary_key") or []],
                        field_count=field_count,
                        measure_count=measure_count,
                        relationship_count=len(raw.get("relationships") or []),
                        has_normalization=isinstance(raw.get("normalization"), dict)
                        and bool(raw.get("normalization")),
                        **self._header_common(raw),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping %s: %s", yaml_file, exc)
        return result

    def get_yaml(self, yaml_id: str) -> VizYAMLNode:
        entry = self._ensure_cache()["by_id"].get(yaml_id)
        if entry is None:
            raise YAMLNotFoundError(yaml_id)
        raw, yaml_file = entry
        return self._raw_to_node(raw, yaml_file)

    def get_yamls_by_ids(self, ids: set[str]) -> list[VizYAMLNode]:
        """Return the full nodes for ``ids``. Backed by the parse-once catalog
        cache, so this is a dict lookup per id instead of an O(N x files) disk
        scan. Preserves the workspace's sorted-file order.
        """
        if not ids:
            return []
        idset = set(ids)
        out: list[VizYAMLNode] = []
        for yaml_file, raw in self._ensure_cache()["raws"]:
            if raw.get("id") in idset:
                try:
                    out.append(self._raw_to_node(raw, yaml_file))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Skipping %s: %s", yaml_file, exc)
        return out

    def load_raw_by_id(self, yaml_id: str) -> dict:
        """Return the round-trip raw dict for an entity ID.

        Distinct from :meth:`get_yaml` which projects the YAML into the typed
        ``VizYAMLNode`` (losing ordering / comments). The enrichment service
        needs the original structure to round-trip through the LLM, so it
        consumes this raw form.

        Raises :class:`YAMLNotFoundError` when no file contains the ID.
        """
        for yaml_file in self._iter_yaml_files():
            try:
                raw = self._load_raw(yaml_file)
                if raw and raw.get("id") == yaml_id:
                    return dict(raw)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error reading %s: %s", yaml_file, exc)
        raise YAMLNotFoundError(yaml_id)

    def update_yaml(
        self,
        yaml_id: str,
        req: VizYAMLUpdateRequest,
        git_service=None,  # GitService | None — optional to avoid circular import typing
        author_name: str | None = None,  # server-derived (JWT); overrides req.author_*
        author_email: str | None = None,
    ) -> VizYAMLNode:
        node = self.get_yaml(yaml_id)
        abs_path = self.repo_root / node.file_path
        raw = self._load_raw(abs_path)

        # Enrichment provenance (which props the admin / AI touched) is
        # tracked in a sidecar JSON (.sap_baseline/<id>.enrichments.json),
        # NOT inside the YAML body. Keeps `git diff workspace/` focused on
        # business-meaningful changes — framework metadata stays out.
        existing_entity_enr, existing_field_enr = self._enrichments_store.read(yaml_id)
        entity_enr_set = set(existing_entity_enr)
        field_enr = dict(existing_field_enr)

        # Apply top-level enrichable updates + record entity-level provenance.
        if req.description is not None:
            raw["description"] = req.description
            entity_enr_set.add("description")
        if req.alias is not None:
            raw["alias"] = req.alias
            entity_enr_set.add("alias")
        # Core structural fields (standards §4.1/§4.2). db_table_name +
        # classification are common-header (any layer); entity_role is a
        # Silver/Gold body field — there is NO entity_role on Bronze (raw
        # tables), so guard against writing one there.
        if req.db_table_name is not None:
            raw["db_table_name"] = req.db_table_name
            entity_enr_set.add("db_table_name")
        if req.classification is not None:
            raw["classification"] = req.classification
            entity_enr_set.add("classification")
        # GOLD ONLY. At Silver, entity_role is derived and `_finalize_silver_gold`
        # recomputes it below, so accepting it here would write a value that is
        # discarded a hundred lines later — the client would be silently ignored.
        # Gold authors it, so a Gold request is honoured.
        if req.entity_role is not None and node.layer == VizLayer.gold:
            raw["entity_role"] = req.entity_role
            entity_enr_set.add("entity_role")

        # Apply field-level updates + recompute field provenance for the
        # affected fields only (compute_enrichments_* preserves the rest).
        if req.fields:
            self._apply_field_updates(raw, req.fields, node.layer)
            updated_field_names = {upd.name for upd in req.fields}
            if node.layer == VizLayer.bronze:
                field_enr = compute_enrichments_bronze(
                    raw.get("fields") or {},
                    field_enr,
                    updated_field_names,
                )
            else:
                field_enr = compute_enrichments_silver(
                    raw.get("fields") or [],
                    field_enr,
                    updated_field_names,
                )

        # Lazy migration: drop the legacy `_meta` block if it's still inline
        # in the YAML. The sidecar is the new source of truth.
        if "_meta" in raw:
            legacy_meta = raw.pop("_meta") or {}
            # Merge any legacy entity_enrichments / field_enrichments we
            # haven't already moved (defensive — usually empty after the
            # first save under this code path).
            if isinstance(legacy_meta, dict):
                for p in legacy_meta.get("entity_enrichments") or []:
                    if isinstance(p, str):
                        entity_enr_set.add(p)
                legacy_fields = legacy_meta.get("field_enrichments") or {}
                if isinstance(legacy_fields, dict):
                    for fname, props in legacy_fields.items():
                        if isinstance(props, list) and fname not in field_enr:
                            field_enr[str(fname)] = [str(p) for p in props if isinstance(p, str)]

        # Replace join_graph (Silver/Gold only, send full list)
        if req.join_graph is not None and node.layer in (VizLayer.silver, VizLayer.gold):
            raw["join_graph"] = [
                {
                    "left_table": j.left_table,
                    "right_table": j.right_table,
                    "join_type": j.join_type,
                    "condition": j.condition,
                    "sequence": j.sequence,
                }
                for j in req.join_graph
            ]

        # Replace relationships (Silver/Gold only, full list). Drop None subfields
        # so the YAML stays clean.
        if req.relationships is not None and node.layer in (VizLayer.silver, VizLayer.gold):
            raw["relationships"] = [r.model_dump(exclude_none=True) for r in req.relationships]

        # Replace normalization block (currency / UoM). Empty dict clears it.
        if req.normalization is not None:
            if req.normalization:
                raw["normalization"] = req.normalization
            else:
                raw.pop("normalization", None)

        # Full structural replace (edit-in-full parity with Create): wholesale
        # replace fields / composed_of / grain / module, then re-normalize via the
        # EntityDeriver + re-validate. Lets a curator fix structure post-creation
        # (add/remove/rename/retype columns, keys, joins) — not just enrichment.
        if (
            req.fields_full is not None
            or req.composed_of is not None
            or req.grain is not None
            or req.module is not None
        ):
            # Snapshot enrichable field props BEFORE the wholesale replace. The
            # SPA routes ALL field edits (including a pure description /
            # field_role enrichment) through fields_full, so this is the ONLY
            # place those edits can be captured as provenance. Without it, a
            # later SAP re-ingest silently AUTO-APPLIES over the curator's value
            # instead of raising a conflict — the per-field ``req.fields`` path
            # above never runs for an edit-in-full.
            pre_fields = self._fields_by_name(raw, node.layer)
            self._apply_structural_replace(raw, req, node.layer)
            post_fields = self._fields_by_name(raw, node.layer)
            # Mark only fields whose enrichable prop actually changed (mirrors
            # the per-field path's "touched" semantic) — recomputing every field
            # would flag the whole SAP-derived entity as enriched.
            enriched_touched = {
                name
                for name, newf in post_fields.items()
                if any((pre_fields.get(name) or {}).get(p) != newf.get(p) for p in ENRICHABLE_PROPS)
            }
            if node.layer == VizLayer.bronze:
                field_enr = compute_enrichments_bronze(
                    raw.get("fields") or {}, field_enr, enriched_touched
                )
            else:
                field_enr = compute_enrichments_silver(
                    raw.get("fields") or [], field_enr, enriched_touched
                )
            # Drop provenance for fields the structural edit removed / renamed.
            field_enr = {k: v for k, v in field_enr.items() if k in post_fields}

        # Persist enrichment provenance (entity + field) AFTER both the per-field
        # and structural paths have settled the final field set. (Was written
        # earlier before the structural path existed — moving it here is what
        # closes the "edit-in-full skips provenance" gap.)
        self._enrichments_store.write(
            yaml_id,
            entity_enrichments=sorted(entity_enr_set),
            field_enrichments=field_enr,
        )

        # Derived fields are recomputed authoritatively (Silver/Gold): the client
        # never sets entity_role / entity_grain — they follow from classification
        # and the fields' identifier roles. Runs on EVERY save (per-field patch OR
        # structural) so the values can never drift from the inputs. Re-validates
        # against the layer model (e.g. zero identifier fields → empty grain → 422,
        # which correctly forces the author to mark an identifier).
        if node.layer in (VizLayer.silver, VizLayer.gold):
            self._finalize_silver_gold(raw, node.layer)

        self._drop_blank_field_sources(raw)

        # Serialize and write
        yaml_content = self._serialize(raw)
        abs_path.write_text(yaml_content, encoding="utf-8")
        self._invalidate_cache()
        logger.info("Written %s", abs_path)

        # Git commit — author is the server-verified identity when provided.
        # ``source`` (manual / ai_assist / import / merge / history_restore)
        # picks the commit message so ``git log`` tells you the provenance of
        # every change. The default ``manual`` preserves the legacy wording.
        if git_service is not None:
            source = getattr(req, "source", "manual") or "manual"
            commit_message = _build_commit_message(yaml_id, source, req)
            commit_paths = [node.file_path]
            # Include the enrichments sidecar (written/removed just above) so it
            # does not linger as an uncommitted tracked change — an uncommitted
            # .enrichments.json later aborts the publish branch switch, same
            # class as the SAP baseline. _stage tolerates a never-tracked path.
            try:
                enr_rel = (
                    self._enrichments_store._path(yaml_id)  # noqa: SLF001 — same module
                    .relative_to(self.repo_root)
                    .as_posix()
                )
                commit_paths.append(enr_rel)
            except ValueError:
                pass  # sidecar outside repo root — skip
            git_service.commit(
                commit_paths,
                commit_message,
                author_name or req.author_name,
                author_email or req.author_email,
            )

        return self.get_yaml(yaml_id)

    def import_yaml(
        self,
        yaml_content: str,
        *,
        force: bool = False,
        git_service=None,
        author_name: str | None = None,
        author_email: str | None = None,
    ) -> VizYAMLNode:
        """Pass I — import a hand-authored or offline YAML into the workspace.

        Workflow:
          1. Parse + strict-validate against the layer-specific Pydantic model
             (BronzeNode / SilverNode / GoldNode). Bad YAML returns a
             ValueError; bad schema raises pydantic.ValidationError.
          2. Compute the canonical workspace path from the entity's
             ``source_system`` / ``layer`` / ``module`` / ``name``.
          3. Write the file (with parent directories) using the standard
             serializer.
          4. Optional git commit when ``git_service`` is supplied.

        Refuses to overwrite an existing file unless ``force=True`` — that's
        the safety belt against silent destruction of in-progress
        enrichments. Callers pass ``force=True`` only on an explicit admin
        confirmation.

        Does NOT touch OpenSearch / runtime. Publishing to runtime stays
        the explicit ``Publish`` action on the Graph page.
        """
        try:
            raw = load_yaml_text(yaml_content)
        except Exception as exc:  # noqa: BLE001 — boundary
            raise ValueError(f"Could not parse YAML: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError("YAML root must be a mapping")

        layer = (raw.get("layer") or "").lower()
        if layer not in {"bronze", "silver", "gold"}:
            raise ValueError(f"Unsupported layer '{layer}'. Expected one of: bronze, silver, gold.")

        # Normalization pass — fill the mechanical scaffolding (ids, version,
        # source_system_no/id, entity_role, grain, field_role, canonical types,
        # Gold composed_of) BEFORE validation, so hand-authored + DDL+AI YAMLs
        # that omit derivable fields still validate. Non-destructive: only
        # absent/empty fields are filled; the single rewrite is field
        # `type` → canonical. Uses the SAME EntityDeriver the SAP parser
        # delegates to (DIP) — see ITERATION_ENTITY_CREATION_REDESIGN.md.
        from ask_knowledge_graph.domain.entity_deriver import EntityDeriver

        deriver = EntityDeriver()
        completed = deriver.complete(dict(raw), layer=layer)
        self._apply_completion_to_commented_map(raw, completed)
        self._drop_blank_field_sources(raw)

        # Semantic guard (D1 hybrid): the deriver fills mechanical + innocuous
        # fields, but the genuinely-semantic ones it never invents
        # (classification / module / Silver composed_of) must be present. Raise a
        # friendlier ValueError than the raw Pydantic error before validation so
        # the DDL loop surfaces an actionable per-doc reason.
        deriver.assert_semantic_complete(completed, layer=layer)

        # Strict schema validation per layer (raises pydantic.ValidationError
        # which the router maps to HTTP 422 with a readable detail).
        if layer == "bronze":
            from ask_knowledge_graph.domain.nodes import BronzeNode

            BronzeNode.model_validate(raw)
        elif layer == "silver":
            from ask_knowledge_graph.domain.nodes import SilverNode

            SilverNode.model_validate(raw)
        else:  # gold
            from ask_knowledge_graph.domain.nodes import GoldNode

            GoldNode.model_validate(raw)

        source = (raw.get("source_system") or "").lower()
        name = (raw.get("name") or "").lower()
        entity_id = raw.get("id") or ""
        if not (source and name and entity_id):
            raise ValueError(
                "YAML must carry non-empty `id`, `source_system` and `name` "
                "(used to derive the workspace file path)."
            )

        if layer == "bronze":
            rel = Path(source) / layer / f"{name}.yaml"
        else:
            module_raw = raw.get("module")
            module = module_raw[0] if isinstance(module_raw, list) and module_raw else module_raw
            if not isinstance(module, str) or not module:
                raise ValueError(
                    f"Silver/Gold '{entity_id}' must have a non-empty `module` "
                    f"(used to derive the workspace file path)."
                )
            rel = Path(source) / layer / module.lower() / f"{name}.yaml"

        abs_path = self.workspace / rel
        if abs_path.exists() and not force:
            raise FileExistsError(
                f"File '{self._rel_posix(abs_path)}' already exists. Pass "
                f"`force=true` to overwrite (will replace any in-place "
                f"enrichments)."
            )

        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(self._serialize(raw), encoding="utf-8")
        self._invalidate_cache()
        rel_path = self._rel_posix(abs_path)
        logger.info("Imported YAML %s into workspace at %s", entity_id, abs_path)

        if git_service is not None and author_email:
            action = "overwrite" if force else "import"
            git_service.commit(
                [rel_path],
                f"viz: {action} {entity_id} from manual upload",
                author_name or author_email.split("@")[0],
                author_email,
            )

        return self.get_yaml(entity_id)

    def delete_yaml(
        self,
        entity_id: str,
        *,
        git_service=None,
        author_name: str | None = None,
        author_email: str | None = None,
    ) -> str | None:
        """Remove a workspace YAML file (+ optional git audit commit).

        Part of the full DataProduct delete: without this the file lingers in the
        workspace and the entity keeps showing in the catalog. Returns the
        repo-relative path removed, or ``None`` if it wasn't present.
        """
        try:
            node = self.get_yaml(entity_id)
        except YAMLNotFoundError:
            return None
        rel_path = node.file_path
        abs_path = self.repo_root / rel_path
        try:
            abs_path.unlink()
        except FileNotFoundError:
            return None
        self._invalidate_cache()
        logger.info("Deleted workspace YAML %s (%s)", entity_id, rel_path)
        if git_service is not None and author_email:
            try:
                git_service.commit(
                    [rel_path],
                    f"viz: delete {entity_id}",
                    author_name or author_email.split("@")[0],
                    author_email,
                )
            except Exception:  # noqa: BLE001 — audit-only, never blocks the delete
                logger.warning("delete_yaml git commit failed for %s", entity_id, exc_info=True)
        return rel_path

    def create_yaml_from_parsed(self, node) -> str:
        """Write a SAP-parsed Bronze/Silver/Gold domain node as a draft YAML.

        Used by the merge flow when a SAP JSON payload references an entity
        that does not yet exist in the workspace ("first ingest"). The YAML
        body stays clean — provenance (enrichments / conflicts) lives in
        sidecars under ``.sap_baseline/`` and is empty for a fresh draft.

        Returns the POSIX path relative to ``repo_root`` (matches the
        ``file_path`` shape produced elsewhere in this service).
        """
        raw = node.model_dump(exclude_none=True)
        # No inline `_meta` block — sidecars (.sap_baseline/<id>.{conflicts,
        # enrichments}.json) carry that state.
        raw.pop("_meta", None)
        # `SilverField.source` defaults to "" (not None), so `exclude_none` alone
        # would still emit the empty key for a field with no bronze origin.
        self._drop_blank_field_sources(raw)
        layer = (raw.get("layer") or "").lower()
        source = (raw.get("source_system") or "").lower()
        name = (raw.get("name") or raw.get("id") or "").lower()
        if not name or not source or layer not in {"bronze", "silver", "gold"}:
            raise ValueError(
                f"Cannot derive file path for node: layer={layer} source={source} name={name}"
            )

        if layer == "bronze":
            rel = Path(source) / layer / f"{name}.yaml"
        else:
            module_raw = raw.get("module")
            module = module_raw[0] if isinstance(module_raw, list) and module_raw else module_raw
            if not isinstance(module, str) or not module:
                raise ValueError(f"Silver/Gold node {raw.get('id')} missing module")
            rel = Path(source) / layer / module.lower() / f"{name}.yaml"

        abs_path = self.workspace / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(self._serialize(raw), encoding="utf-8")
        self._invalidate_cache()
        logger.info("Created new %s YAML %s", layer, abs_path)
        return self._rel_posix(abs_path)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _load_raw(self, path: Path) -> dict | None:
        """Load a YAML file in round-trip mode (preserves comments + order).

        Returned object is a ``CommentedMap`` from ruamel.yaml which is dict-
        compatible (``isinstance(x, dict)`` is True). Callers may freely mutate
        it; downstream :meth:`_serialize` will round-trip the result back to a
        comment-preserving YAML string.
        """
        content = path.read_text(encoding="utf-8")
        data = load_yaml_text(content)
        return data if isinstance(data, dict) else None

    def _serialize(self, raw: dict) -> str:
        return AskYamlSerializer().to_yaml(raw)

    @staticmethod
    def _apply_completion_to_commented_map(target: dict, completed: dict) -> None:
        """Write EntityDeriver completions into the round-trip ``CommentedMap``
        in place, preserving author comments / key order / quote styles.

        Rules (mirror the deriver's non-destructive contract):
          * a top-level key the deriver DROPPED → removed from ``target`` too;
          * top-level key absent/empty in ``target`` → set from ``completed``;
          * keys in ``_DERIVED_ALWAYS`` → always overwritten (the deriver owns them);
          * ``grain`` sub-keys filled only when absent/empty;
          * per-field ``type`` is always overwritten with the canonical encoding
            (the single allowed rewrite); ``field_role`` filled only when absent.
        Author-provided scalars are left byte-identical.
        """
        # DROPPED keys: `complete()` starts from `dict(raw)` and only ever ADDS —
        # except for the keys a layer's contract forbids (today: `composed_of` and
        # `join_graph` at Gold). So "in target, absent from completed" is exactly
        # that forbidden set, and mirroring the deletion here keeps the two write
        # paths honest: without it the author's key survives into the written YAML
        # even though the model drops it on load, and we would keep minting dead
        # keys on every save. Deriving the set instead of hardcoding it means a
        # future contract removal needs no change here.
        for key in [k for k in list(target) if k not in completed]:
            del target[key]
        # DERIVED keys: the deriver is authoritative and always overwrites.
        # Bronze `primary_key` is normalized there (dedup + union with the
        # key_field flags). Filling it only when absent would let a declared,
        # duplicated primary_key reach `BronzeNode.model_validate()` untouched,
        # so /import would 422 even though the deriver had already repaired it —
        # `import_yaml` validates `raw`, not `completed`.
        _DERIVED_ALWAYS = {"primary_key"}

        for key, val in completed.items():
            if key == "fields":
                YAMLFileService._apply_fields(target.get("fields"), val, target)
                continue
            if key in _DERIVED_ALWAYS:
                # Written even when EMPTY: `primary_key: []` is a legitimate
                # completion since keyless Bronze became warn-not-reject
                # (2026-08-03) — BronzeNode requires the key PRESENT, and
                # skipping empties here would 422 the exact case the contract
                # now accepts. (Under the old contract the empty case never
                # reached this line: assert_semantic_complete raised first.)
                target[key] = val
                continue
            if key == "grain":
                cur = target.get("grain")
                if not isinstance(cur, dict):
                    target["grain"] = val
                else:
                    for gk, gv in (val or {}).items():
                        if cur.get(gk) in (None, "", []):
                            cur[gk] = gv
                continue
            if key not in target or target.get(key) in (None, "", []):
                target[key] = val

    @staticmethod
    def _drop_blank_field_sources(raw: dict) -> None:
        """Remove Silver/Gold field ``source`` keys that carry no lineage.

        Runs on every write of this service, so a blank one is neither minted nor
        round-tripped: a file that already carries it is cleaned by the next save.

        A blank ``source`` is not inert noise. The measure fan-out derivation reads
        the table out of this value to decide `non_additive_over`
        (``EntityDeriver.fanout_dims_by_table``), so the key is consumed — an empty
        one only survives because "" resolves to no table. Anything that fabricated
        a placeholder there would be read as a real source table.

        Bronze is skipped: its field shape is a mapping and has no ``source``.
        """
        fields = raw.get("fields")
        if not isinstance(fields, list):
            return
        for fdef in fields:
            if isinstance(fdef, dict) and not str(fdef.get("source") or "").strip():
                fdef.pop("source", None)

    @staticmethod
    def _fill_field(tf: dict, cf: dict) -> None:
        """Merge one completed field ``cf`` into the round-trip field ``tf``.

        Mirrors the deriver's non-destructive contract: ``type`` is always
        overwritten with the canonical encoding (the single allowed rewrite);
        every other key the deriver produced (``alias`` / ``description`` /
        ``key_field`` / ``field_role`` / ``source``) is filled ONLY when absent
        or empty in ``tf`` — so author values stay byte-identical while the
        innocuous placeholders (D1 hybrid) reach the validated object."""
        for k, v in cf.items():
            if k == "type":
                tf["type"] = v
            elif k not in tf or tf.get(k) in (None, "", []):
                tf[k] = v

    @staticmethod
    def _apply_fields(target_fields, completed_fields, parent: dict) -> None:
        """Apply field-level completions for both bronze (dict) + silver/gold
        (list) field shapes."""
        if completed_fields is None:
            return
        if target_fields is None or not target_fields:
            parent["fields"] = completed_fields
            return
        # Bronze: fields is a mapping {name: {type, alias, key_field, ...}}.
        if isinstance(target_fields, dict) and isinstance(completed_fields, dict):
            for name, cf in completed_fields.items():
                tf = target_fields.get(name)
                if not isinstance(tf, dict):
                    target_fields[name] = cf
                elif isinstance(cf, dict):
                    YAMLFileService._fill_field(tf, cf)
            return
        # Silver/Gold: fields is a list of field dicts (deriver preserves order).
        if isinstance(target_fields, list) and isinstance(completed_fields, list):
            for i, cf in enumerate(completed_fields):
                if i >= len(target_fields):
                    target_fields.append(cf)
                    continue
                tf = target_fields[i]
                if isinstance(tf, dict) and isinstance(cf, dict):
                    YAMLFileService._fill_field(tf, cf)

    def _rel_posix(self, abs_path: Path) -> str:
        try:
            return abs_path.resolve().relative_to(self.repo_root).as_posix()
        except ValueError:
            return abs_path.as_posix()

    def _parse_layer(self, layer_str: str) -> VizLayer | None:
        try:
            return VizLayer(layer_str)
        except ValueError:
            return None

    def _extract_module(self, raw: dict) -> str | None:
        m = raw.get("module")
        if isinstance(m, list):
            return m[0] if m else None
        return m or None

    def _extract_meta(self, raw: dict, yaml_id: str | None = None) -> VizMeta:
        """Hydrate ``VizMeta`` from the sidecars + tolerate legacy inline ``_meta``.

        After Pass H (conflicts) + the enrichments sidecar refactor, both
        ``conflicts`` and ``field_enrichments``/``entity_enrichments`` live
        in JSON files under ``.sap_baseline/``. The YAML body should be
        clean. Legacy entries inside ``raw["_meta"]`` are still honoured at
        read time so the migration doesn't lose data — the next ``update_yaml``
        rewrites the YAML without the inline block.
        """
        legacy_meta = raw.get("_meta") or {}

        conflicts_sidecar: list = []
        sidecar_entity_enr: list[str] = []
        sidecar_field_enr: dict[str, list[str]] = {}
        if yaml_id:
            conflicts_sidecar = self._conflict_store.list_for(yaml_id, include_resolved=True)
            sidecar_entity_enr, sidecar_field_enr = self._enrichments_store.read(yaml_id)

        # Sidecar wins; fall back to any legacy _meta values for the migration
        # window (zero if the YAML has been re-saved under the new code path).
        legacy_conflicts = legacy_meta.get("conflicts") or []
        legacy_entity_enr = legacy_meta.get("entity_enrichments") or []
        legacy_field_enr = legacy_meta.get("field_enrichments") or {}

        return VizMeta(
            field_enrichments=sidecar_field_enr or legacy_field_enr,
            entity_enrichments=sidecar_entity_enr or legacy_entity_enr,
            conflicts=conflicts_sidecar if conflicts_sidecar else legacy_conflicts,
        )

    def _extract_fields(self, raw: dict, layer: VizLayer) -> list[VizField]:
        if layer == VizLayer.bronze:
            fields_raw = raw.get("fields") or {}
            if not isinstance(fields_raw, dict):
                return []
            return [
                VizField(
                    name=fname,
                    type=fdata.get("type") if isinstance(fdata, dict) else None,
                    alias=fdata.get("alias") if isinstance(fdata, dict) else None,
                    key_field=bool(fdata.get("key_field", False))
                    if isinstance(fdata, dict)
                    else False,
                    description=fdata.get("description") if isinstance(fdata, dict) else None,
                    synonyms=(fdata.get("synonyms") or []) if isinstance(fdata, dict) else [],
                    normalization_flag=fdata.get("normalization_flag")
                    if isinstance(fdata, dict)
                    else None,
                )
                for fname, fdata in fields_raw.items()
            ]
        else:  # silver, gold
            fields_raw = raw.get("fields") or []
            if not isinstance(fields_raw, list):
                return []
            return [
                VizField(
                    name=f.get("name", ""),
                    source=f.get("source"),
                    field_role=f.get("field_role"),
                    type=f.get("type"),
                    description=f.get("description"),
                    aggregation_behavior=f.get("aggregation_behavior"),
                    additivity=f.get("additivity"),
                    non_additive_over=f.get("non_additive_over") or [],
                    synonyms=f.get("synonyms") or [],
                    normalization_flag=f.get("normalization_flag"),
                )
                for f in fields_raw
                if isinstance(f, dict)
            ]

    def _extract_join_graph(self, raw: dict) -> list[VizJoinCondition]:
        jg = raw.get("join_graph") or []
        if not isinstance(jg, list):
            return []
        result = []
        for j in jg:
            if not isinstance(j, dict):
                continue
            try:
                result.append(
                    VizJoinCondition(
                        left_table=j.get("left_table", ""),
                        right_table=j.get("right_table", ""),
                        join_type=j.get("join_type", "INNER"),
                        condition=j.get("condition", ""),
                        sequence=int(j.get("sequence", 1)),
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        return result

    def _extract_relationships(self, raw: dict) -> list[VizRelationship]:
        rels = raw.get("relationships") or []
        if not isinstance(rels, list):
            return []
        result: list[VizRelationship] = []
        for r in rels:
            if not isinstance(r, dict) or not r.get("target_entity"):
                continue
            try:
                result.append(
                    VizRelationship(
                        target_entity=r["target_entity"],
                        relationship_type=r.get("relationship_type"),
                        join_condition=r.get("join_condition"),
                        semantic_label=r.get("semantic_label"),
                        traversal_cost=r.get("traversal_cost"),
                        aggregation_safety=r.get("aggregation_safety"),
                        cross_module=r.get("cross_module"),
                        description=r.get("description"),
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        return result

    def _extract_grain(self, raw: dict) -> VizGrain | None:
        g = raw.get("grain")
        if not isinstance(g, dict):
            return None
        eg = g.get("entity_grain")
        return VizGrain(
            entity_grain=[str(x) for x in eg] if isinstance(eg, list) else [],
            business_grain=g.get("business_grain"),
        )

    @staticmethod
    def _header_common(raw: dict) -> dict:
        """The §3.1 header keys, normalised — shared by the summary and the node.

        Five of these (``business_process``, ``source_system``, ``version``,
        ``internal_id``, ``tag1``/``tag2``) never left this service before, so no
        client could render them even though the models have always carried them
        and the contract declares the tags specifically for catalog faceting.
        """
        instance_no = raw.get("source_system_no")
        if instance_no in (None, ""):
            # Bronze spells it `source_system_id` (BronzeNode); Silver/Gold
            # `source_system_no`. One field out, so the UI never branches on layer.
            instance_no = raw.get("source_system_id")
        version = raw.get("version")
        return {
            "description": raw.get("description"),
            "business_process": raw.get("business_process") or None,
            "entity_role": raw.get("entity_role"),
            "classification": raw.get("classification"),
            "db_table_name": raw.get("db_table_name"),
            "source_system": raw.get("source_system"),
            "source_system_no": instance_no if isinstance(instance_no, int) else None,
            # `version` is typed `str` in the models but a hand-authored YAML may
            # carry it unquoted, which ruamel loads as an int.
            "version": str(version) if version not in (None, "") else None,
            "internal_id": raw.get("internal_id") or None,
            "tag1": raw.get("tag1") or None,
            "tag2": raw.get("tag2") or None,
        }

    @staticmethod
    def _count_fields(raw: dict, layer: VizLayer) -> tuple[int, int]:
        """``(field_count, measure_count)`` for either layer's field shape.

        Bronze columns carry no ``field_role`` (that taxonomy starts at Silver), so
        its measure count is 0 by construction, not by omission.
        """
        fields = raw.get("fields")
        if layer == VizLayer.bronze:
            return (len(fields) if isinstance(fields, dict) else 0), 0
        if not isinstance(fields, list):
            return 0, 0
        measures = sum(
            1 for f in fields if isinstance(f, dict) and f.get("field_role") == "measure"
        )
        return len(fields), measures

    def _raw_to_node(self, raw: dict, yaml_file: Path) -> VizYAMLNode:
        layer = self._parse_layer(raw.get("layer", "")) or VizLayer.bronze
        return VizYAMLNode(
            id=raw["id"],
            layer=layer,
            module=self._extract_module(raw),
            name=raw.get("name") or raw.get("alias") or raw["id"],
            alias=raw.get("alias"),
            primary_key=[str(k) for k in raw.get("primary_key") or []],
            grain=self._extract_grain(raw),
            file_path=self._rel_posix(yaml_file),
            fields=self._extract_fields(raw, layer),
            join_graph=self._extract_join_graph(raw),
            composed_of=raw.get("composed_of") or [],
            relationships=self._extract_relationships(raw),
            normalization=raw.get("normalization")
            if isinstance(raw.get("normalization"), dict)
            else None,
            meta=self._extract_meta(raw, yaml_id=raw.get("id")),
            **self._header_common(raw),
        )

    @staticmethod
    def _fields_by_name(raw: dict, layer: VizLayer) -> dict[str, dict]:
        """Return ``{field_name: field_dict}`` for either layer's field shape
        (Bronze dict-of-dicts, Silver/Gold list-of-dicts). Used to diff a
        field's enrichable props across a structural (edit-in-full) replace."""
        if layer == VizLayer.bronze:
            fields = raw.get("fields") or {}
            if not isinstance(fields, dict):
                return {}
            return {k: v for k, v in fields.items() if isinstance(v, dict)}
        return {
            f["name"]: f for f in (raw.get("fields") or []) if isinstance(f, dict) and "name" in f
        }

    def _apply_field_updates(
        self, raw: dict, updates: list[VizFieldUpdate], layer: VizLayer
    ) -> None:
        if layer == VizLayer.bronze:
            fields_dict = raw.get("fields") or {}
            if not isinstance(fields_dict, dict):
                return
            for upd in updates:
                if upd.name not in fields_dict:
                    continue
                f = fields_dict[upd.name]
                if not isinstance(f, dict):
                    continue
                if upd.alias is not None:
                    f["alias"] = upd.alias
                if upd.description is not None:
                    f["description"] = upd.description
                if upd.synonyms is not None:
                    f["synonyms"] = upd.synonyms
                if upd.normalization_flag is not None:
                    f["normalization_flag"] = upd.normalization_flag
        else:  # silver, gold
            fields_list = raw.get("fields") or []
            if not isinstance(fields_list, list):
                return
            by_name = {f["name"]: f for f in fields_list if isinstance(f, dict) and "name" in f}
            for upd in updates:
                if upd.name not in by_name:
                    continue
                f = by_name[upd.name]
                if upd.field_role is not None:
                    f["field_role"] = upd.field_role
                if upd.description is not None:
                    f["description"] = upd.description
                if upd.aggregation_behavior is not None:
                    f["aggregation_behavior"] = upd.aggregation_behavior
                if upd.additivity is not None:
                    f["additivity"] = upd.additivity
                if upd.non_additive_over is not None:
                    # An explicit [] clears it — the caller is moving the field
                    # off `semi_additive`, and leaving a stale dimension list
                    # behind would fail the SilverField contract on save.
                    if upd.non_additive_over:
                        f["non_additive_over"] = list(upd.non_additive_over)
                    else:
                        f.pop("non_additive_over", None)
                if upd.synonyms is not None:
                    f["synonyms"] = upd.synonyms
                if upd.normalization_flag is not None:
                    f["normalization_flag"] = upd.normalization_flag

    def _apply_structural_replace(self, raw: dict, req, layer: VizLayer) -> None:
        """Wholesale-replace fields / composed_of / grain / module, then normalize
        (EntityDeriver) + validate. Used for full structural edits (add/remove/
        rename/retype columns, keys, etc.). A structural edit intentionally drops
        per-field inline comments — the body is re-assembled."""
        from ask_knowledge_graph.domain.entity_deriver import EntityDeriver
        from ask_knowledge_graph.domain.nodes import BronzeNode, GoldNode, SilverNode

        if req.module is not None:
            raw["module"] = req.module
        if req.composed_of is not None:
            raw["composed_of"] = list(req.composed_of)
        if req.grain is not None:
            cur = raw.get("grain") if isinstance(raw.get("grain"), dict) else {}
            raw["grain"] = {
                "entity_grain": list(req.grain.entity_grain or cur.get("entity_grain") or []),
                "business_grain": req.grain.business_grain or cur.get("business_grain") or "",
            }
        if req.fields_full is not None:
            raw["fields"] = self._build_fields_shape(req.fields_full, layer)
            # Bronze primary_key is derived from key_field flags — clear it so the
            # deriver recomputes from the new field set (it only fills when absent).
            if layer == VizLayer.bronze:
                raw.pop("primary_key", None)

        completed = EntityDeriver().complete(dict(raw), layer=layer.value)
        for key in (
            "fields",
            "primary_key",
            "grain",
            "composed_of",
            "join_graph",
            "entity_role",
            "version",
            "internal_id",
            "source_system_no",
            "source_system_id",
            "business_process",
            "module",
        ):
            if key in completed:
                raw[key] = completed[key]
            else:
                # The deriver dropped it because the layer's contract forbids it
                # (Gold: `composed_of` / `join_graph`). Same reasoning as in
                # `_apply_completion_to_commented_map` — a copy-only loop would
                # leave the author's forbidden key in the written YAML.
                raw.pop(key, None)

        model = {
            VizLayer.bronze: BronzeNode,
            VizLayer.silver: SilverNode,
            VizLayer.gold: GoldNode,
        }[layer]
        try:
            model.model_validate(dict(raw))
        except Exception as exc:  # noqa: BLE001 — surfaced as 422 by the router
            raise ValueError(f"Invalid entity after structural edit: {exc}") from exc

    def _finalize_silver_gold(self, raw: dict, layer: VizLayer) -> None:
        """Recompute the DERIVED Silver/Gold fields after any edit.

        These are never authored by the client — they follow mechanically from the
        inputs, so we recompute them on every save (per-field patch OR structural)
        to guarantee they can't drift:

          * ``entity_role`` (**Silver only**) — from ``classification`` + whether
            the entity is item-level / has a measure (Standards §5.1, via
            :meth:`EntityDeriver.entity_role`). **Gold is AUTHORED**: the
            derivation rule's inputs (SAP ``CONTFLAG``, "all tables",
            item-level-ness) are Bronze/SAP artefacts that do not exist at Gold,
            so running it there decided the role on absent evidence — a
            measure-less Gold silently became a ``dimension``. Gold now defaults
            to ``fact`` on the model and the author owns any deviation.
          * ``grain.entity_grain`` (**Silver only**) — the logical names of the
            ``field_role: identifier`` fields (Standards §5; keys = identifier).
            Gold's grain is the *aggregation* grain (dimension columns, no
            identifier fields) and stays author-defined — recomputing it from
            identifiers would wrongly empty it.

        Targeted guard: a Silver left with NO identifier field has an undefined
        grain (violates ``Grain.min_length=1``); raise so the router returns 422
        instead of writing an invalid YAML. We deliberately do NOT run a full
        layer-model validation here — the per-field patch path may operate on a
        partial/legacy YAML that omits other derivable header fields, and forcing
        them would 422 a simple description edit. The structural path still does
        its own full validate via :meth:`_apply_structural_replace`.
        """
        from ask_knowledge_graph.domain.entity_deriver import EntityDeriver

        # Gold: nothing is derived. `entity_role` is authored (model default
        # `fact`), and Gold's grain is the aggregation grain, not the identifier
        # set — see the docstring.
        if layer != VizLayer.silver:
            return

        deriver = EntityDeriver()
        fields = raw.get("fields") if isinstance(raw.get("fields"), list) else []
        name = (raw.get("name") or "").lower()
        has_measure = any(isinstance(f, dict) and f.get("field_role") == "measure" for f in fields)

        raw["entity_role"] = deriver.entity_role(
            classification=raw.get("classification"),
            is_item="item" in name,
            has_measure=has_measure,
            relations_present=None,  # YAML carries no SAP relations
            all_relations_config=False,
        )

        # The join graph is passed so this path runs the SAME structural derivation
        # as the ingestion path (N:1 tables contribute nothing; join-equal columns
        # collapse to one). Without it the result is every identifier field — a
        # superkey that satisfies prompt rule 7's uniqueness clause but falsifies
        # its "a subset returns MANY rows" clause.
        join_graph = raw.get("join_graph") if isinstance(raw.get("join_graph"), list) else None
        entity_grain = deriver.recompute_entity_grain(fields, join_graph=join_graph)
        if not entity_grain:
            raise ValueError(
                "Silver entity needs at least one field with field_role "
                "'identifier' (it defines grain.entity_grain)."
            )
        cur = raw.get("grain") if isinstance(raw.get("grain"), dict) else {}
        business_grain = cur.get("business_grain") or f"{name or 'entity'}_item"
        # Preserve the ruamel CommentedMap when present (keeps comments/order).
        if isinstance(cur, dict) and cur:
            cur["entity_grain"] = entity_grain
            cur["business_grain"] = business_grain
            raw["grain"] = cur
        else:
            raw["grain"] = {
                "entity_grain": entity_grain,
                "business_grain": business_grain,
            }

    @staticmethod
    def _build_fields_shape(fields_full: list, layer: VizLayer):
        """Build the per-layer fields shape from the flat VizFieldFull list:
        Bronze = mapping {name: {type, alias, key_field, description}}; Silver/Gold
        = list of field dicts. Types/roles are normalized later by the deriver."""
        if layer == VizLayer.bronze:
            out: dict = {}
            for f in fields_full:
                if not f.name:
                    continue
                out[f.name] = {
                    "type": f.type or "STRING",
                    "alias": f.alias or f.name.lower(),
                    "key_field": bool(f.key_field),
                    "description": f.description or "",
                }
            return out
        lst: list = []
        for f in fields_full:
            if not f.name:
                continue
            item: dict = {"name": f.name}
            # `source` is OPTIONAL lineage-only metadata: real bronze lineage at
            # Silver, nothing at all on a Gold or a flat Silver (see
            # `EntityDeriver._complete_silver_gold`). An omitted value is therefore
            # not a missing default to fill in — writing `source: ''` states a
            # lineage the author never claimed, and every layer's example set
            # carries no such key. Emitted only when it actually says something.
            if str(f.source or "").strip():
                item["source"] = f.source
            item["type"] = f.type or "STRING"
            item["description"] = f.description or ""
            # Leave field_role absent when the caller didn't set it, so the deriver
            # derives it from the canonical type (DECIMAL→measure, DATE→timestamp…).
            if f.field_role:
                item["field_role"] = f.field_role
            # Keep an explicit "none": on a `field_role: measure` it is NOT a
            # no-op default, it is the NON-ADDITIVE signal (already-cumulative
            # totals, projected balances) that SQL-generation rule 8 reads to
            # decide "never SUM this". Dropping it makes the key ABSENT, which
            # rule 8 reads as "assume additive" — silently turning a running
            # total into a summable measure. Only a caller-omitted value (None
            # / empty) is skipped.
            if f.aggregation_behavior:
                item["aggregation_behavior"] = f.aggregation_behavior
            # Axis 2 (REQ_ADDITIVITY_CONTRACT). `additive` is never written —
            # absence already means additive, so only a deliberate
            # semi_additive / non_additive is persisted.
            if f.additivity:
                item["additivity"] = f.additivity
            if f.non_additive_over:
                item["non_additive_over"] = list(f.non_additive_over)
            if f.synonyms:
                item["synonyms"] = list(f.synonyms)
            lst.append(item)
        return lst


# ── Commit message builder ──────────────────────────────────────────────────


def _build_commit_message(yaml_id: str, source: str, req: VizYAMLUpdateRequest) -> str:
    """Pick a commit message prefix based on the request source.

    Keeps the legacy ``viz: update <id>`` for manual edits (default) so that
    pre-existing dashboards / hooks that grep history don't break. AI-assisted
    enrichments and other automated paths get distinct prefixes for audit
    purposes.

    The message also includes a short tally so ``git log --oneline`` is
    scan-friendly without opening the diff.
    """
    parts: list[str] = []
    if req.description is not None or req.alias is not None:
        parts.append("entity")
    if req.fields:
        parts.append(f"{len(req.fields)} field{'s' if len(req.fields) != 1 else ''}")
    if req.join_graph is not None:
        parts.append("join_graph")
    if req.relationships is not None:
        parts.append("relationships")
    if req.normalization is not None:
        parts.append("normalization")
    detail = " · ".join(parts) if parts else "no-op"

    if source == "ai_assist":
        return f"ai-enrich({yaml_id}): {detail} — applied via AI Assist"
    if source == "ai_suggest_relationship":
        # Caveats (LLM decision rationale + confidence hints) ride along in
        # the commit message body instead of polluting the YAML. ``git log``
        # one-line still scans clean; ``git show`` exposes the audit trail.
        title = f"ai-suggest-rel({yaml_id}): {detail} — applied via AI Suggest"
        notes = list(req.commit_notes or [])
        if not notes:
            return title
        body_lines = ["", "Caveats:"] + [f"  - {n}" for n in notes]
        return "\n".join([title] + body_lines)
    if source == "import":
        return f"viz-import({yaml_id}): {detail}"
    if source == "merge":
        return f"viz-merge({yaml_id}): {detail}"
    if source == "history_restore":
        return f"viz-restore({yaml_id}): {detail}"
    return f"viz: update {yaml_id}"
