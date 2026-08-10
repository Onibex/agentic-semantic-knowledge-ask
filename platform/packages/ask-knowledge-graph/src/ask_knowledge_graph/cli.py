"""
ask_knowledge_graph CLI — batch ingestion + delete tooling.

Usage:
    python -m ask_knowledge_graph.cli ingest <yaml-file>
    python -m ask_knowledge_graph.cli ingest-dir <dir>
    python -m ask_knowledge_graph.cli delete <entity-id>

Or, after `pip install -e packages/ask-knowledge-graph`:
    ask-kg ingest <yaml-file>
    ask-kg ingest-dir <dir>
    ask-kg delete <entity-id>

Configuration is read from `config/settings.json` in the current working
directory (same as the orchestrator). The CLI shares its bootstrap with
the admin API via `ask_knowledge_graph.application.factory`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Service factory — delegates to application.factory (Iter 8 DRY).
# Kept as a module-level function so existing tests can monkey-patch it.
# ─────────────────────────────────────────────────────────────────────────────
def _build_service() -> Any:
    from .application.factory import (
        build_default_ingestion_service,
        load_default_config,
    )

    return build_default_ingestion_service(load_default_config())


# ─────────────────────────────────────────────────────────────────────────────
# Subcommand implementations
# ─────────────────────────────────────────────────────────────────────────────
def cmd_ingest(args: argparse.Namespace) -> int:
    from ask_knowledge_graph.domain.models import IngestionRequest

    path = Path(args.path)
    if not path.is_file():
        print(f"error: {path} is not a file", file=sys.stderr)
        return 2
    yaml_content = path.read_text(encoding="utf-8")

    service = _build_service()
    result = service.ingest_yaml(IngestionRequest(yaml_content=yaml_content))
    if result.error:
        print(f"❌ {path.name}: {result.error}", file=sys.stderr)
        return 1
    print(
        f"✅ {path.name}: id={result.entity_id} layer={result.layer} "
        f"entities={result.entities_indexed} fields={result.fields_indexed} "
        f"edges={result.edges_indexed}"
    )
    return 0


def cmd_ingest_dir(args: argparse.Namespace) -> int:
    from ask_knowledge_graph.domain.models import IngestionRequest

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    yaml_files = sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml"))
    if not yaml_files:
        print(f"warning: no .yaml/.yml files found under {root}", file=sys.stderr)
        return 0

    service = _build_service()
    success = 0
    failed = 0
    for f in yaml_files:
        try:
            result = service.ingest_yaml(
                IngestionRequest(yaml_content=f.read_text(encoding="utf-8"))
            )
        except Exception as exc:  # noqa: BLE001 — boundary
            print(f"❌ {f.relative_to(root)}: {exc}", file=sys.stderr)
            failed += 1
            continue
        if result.error:
            print(f"❌ {f.relative_to(root)}: {result.error}", file=sys.stderr)
            failed += 1
            continue
        success += 1
        print(f"✅ {f.relative_to(root)} → {result.entity_id} ({result.layer})")

    print(f"\nDone — {success} succeeded, {failed} failed")
    return 0 if failed == 0 else 1


def cmd_delete(args: argparse.Namespace) -> int:
    service = _build_service()
    result = service.delete_entity(args.entity_id)
    if result.error:
        print(f"❌ delete failed: {result.error}", file=sys.stderr)
        return 1
    print(
        f"✅ deleted {result.entity_id}: "
        f"entities={result.entities_indexed} fields={result.fields_indexed} "
        f"edges={result.edges_indexed}"
    )
    return 0


def _canonicalize_fields(deriver: Any, ss: Any, fields: Any) -> list[str]:
    """Canonicalize each field's ``type`` in place (bronze dict + silver/gold
    list shapes). Returns the change log. Module-level so the inner helper does
    not close over loop variables (ruff B023)."""
    changes: list[str] = []

    def fix(name: str, fd: dict) -> None:
        t = fd.get("type")
        if not t:
            return
        canon = deriver.canonical_type(t, source_system=ss)
        if canon != t:
            changes.append(f"{name}: {t} -> {canon}")
            fd["type"] = canon

    if isinstance(fields, dict):  # bronze
        for name, fd in fields.items():
            if isinstance(fd, dict):
                fix(str(name), fd)
    elif isinstance(fields, list):  # silver / gold
        for fd in fields:
            if isinstance(fd, dict):
                fix(str(fd.get("name", "?")), fd)
    return changes


def cmd_backfill_types(args: argparse.Namespace) -> int:
    """Re-encode every ``fields[*].type`` to the canonical type system.

    Idempotent (canonical is a fixed point) + ``--dry-run``-able. File-only —
    never touches OpenSearch. Walks a single YAML or a directory tree. Preserves
    comments / key order via the ruamel round-trip serializer.
    """
    from .domain.entity_deriver import EntityDeriver
    from .infrastructure.yaml_serializer import dump_yaml, load_yaml_text

    root = Path(args.path)
    if root.is_file():
        files = [root]
    elif root.is_dir():
        files = sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml"))
    else:
        print(f"error: {root} is not a file or directory", file=sys.stderr)
        return 2

    deriver = EntityDeriver()
    changed_files = 0
    total_changes = 0

    for f in files:
        try:
            data = load_yaml_text(f.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — skip unparseable, keep going
            print(f"⚠ {f}: could not parse ({exc})", file=sys.stderr)
            continue
        if not isinstance(data, dict):
            continue
        changes = _canonicalize_fields(deriver, data.get("source_system"), data.get("fields"))

        if changes:
            changed_files += 1
            total_changes += len(changes)
            tag = "[dry-run] " if args.dry_run else ""
            print(f"{tag}{f}: {len(changes)} change(s)")
            for c in changes:
                print(f"    {c}")
            if not args.dry_run:
                f.write_text(dump_yaml(data), encoding="utf-8")

    verb = "would change" if args.dry_run else "changed"
    print(f"\nDone — {verb} {total_changes} field type(s) across {changed_files} file(s).")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Argparse wiring
# ─────────────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ask-kg",
        description="Knowledge Graph admin CLI — ingest / delete data products.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest one YAML file")
    p_ingest.add_argument("path", help="Path to a YAML file")
    p_ingest.set_defaults(func=cmd_ingest)

    p_ingest_dir = sub.add_parser("ingest-dir", help="Ingest every YAML under a directory")
    p_ingest_dir.add_argument("path", help="Directory containing YAML files")
    p_ingest_dir.set_defaults(func=cmd_ingest_dir)

    p_delete = sub.add_parser("delete", help="Delete an entity by id")
    p_delete.add_argument("entity_id", help="Entity id (e.g. silver_s4h_sd_sales_order)")
    p_delete.set_defaults(func=cmd_delete)

    p_backfill = sub.add_parser(
        "backfill-types", help="Re-encode fields[*].type to canonical types (idempotent)"
    )
    p_backfill.add_argument("path", help="A YAML file or a directory tree of YAMLs")
    p_backfill.add_argument(
        "--dry-run", action="store_true", help="Print intended changes without writing"
    )
    p_backfill.set_defaults(func=cmd_backfill_types)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
