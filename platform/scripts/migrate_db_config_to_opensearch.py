"""One-shot migration: ``settings.json`` DB config → encrypted OpenSearch docs.

Reads the per-environment DB connection from ``config/settings.json`` (the
``environments.{dev,prod}`` blocks, with the top-level block used as the ``dev``
fallback), encrypts the sensitive fields with Fernet, and writes two singleton
docs — ``db_dev`` / ``db_prod`` — into the ``ask-system-settings-v1`` index.
Idempotent: a target that already exists is SKIPPED — re-run safely.

After a successful migration the DB blocks are stripped from ``settings.json``
(``environments`` + ``db_type`` + every top-level backend block); only the
OpenSearch bootstrap block is meant to remain.

Run AFTER setting ``ONIBEX_ENCRYPTION_KEY`` in the environment.

Usage::

    # (master key already generated for the LLM/Embedder migration — reuse it)
    python scripts/migrate_db_config_to_opensearch.py

    # Verify:
    curl http://localhost:8081/v1/admin/secrets/db/dev
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ask_llm_gateway.infrastructure.secrets import SecretsRepository
from ask_llm_gateway.infrastructure.secrets.crypto import validate_master_key
from ask_llm_gateway.infrastructure.secrets.registry import db_provider_fields, known_db_types
from ask_sql_executor.application.db_target import resolve_db_target

SETTINGS_PATH = Path("config/settings.json")


def main() -> int:
    try:
        validate_master_key()
    except SystemExit as exc:
        print(f"[fatal] {exc}", file=sys.stderr)
        return 1

    if not SETTINGS_PATH.exists():
        print(f"[fatal] {SETTINGS_PATH} not found", file=sys.stderr)
        return 1
    cfg = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))

    repo = SecretsRepository()
    repo.ensure_index()

    migrated_any = False
    for env in ("dev", "prod"):
        target = f"db_{env}"
        db_type, db_config = resolve_db_target(cfg, env)
        if not db_config:
            print(f"[skip] {target}: no usable DB block in settings.json")
            continue

        if repo.get_raw(target) is not None:
            print(f"[skip] {target}: already in OpenSearch (run with care)")
            continue

        # Keep only fields the DB registry declares for this backend; stringify
        # (the store keeps everything as strings — read-side coerces types back).
        declared = {name for name, _sensitive, _kind in db_provider_fields(db_type)}
        fields = {
            str(k): str(v) for k, v in db_config.items() if k in declared and v not in (None, "")
        }
        unknown = sorted(set(db_config) - declared)
        if unknown:
            print(f"[warn] {target}: dropping fields not in the {db_type} registry: {unknown}")

        repo.upsert(
            target,
            provider=db_type,
            model="",
            fields=fields,
            updated_by="migration-script",
        )
        migrated_any = True
        enc = sum(1 for n, s, _k in db_provider_fields(db_type) if s and n in fields)
        plain = len(fields) - enc
        print(f"[ok]   {target}: db_type={db_type} plain={plain} encrypted={enc}")

    if migrated_any:
        # Strip the migrated DB plane from settings.json. Domain tuning +
        # the opensearch bootstrap block stay.
        cfg.pop("environments", None)
        cfg.pop("db_type", None)
        for db_type in known_db_types():
            cfg.pop(db_type, None)
        SETTINGS_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[ok]   {SETTINGS_PATH} cleaned (environments + db_type + backend blocks removed)")
    else:
        print("[ok]   nothing to migrate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
