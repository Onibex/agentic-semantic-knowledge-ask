# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""One-shot migration: ``settings.json`` + ``.env`` → encrypted OpenSearch docs.

Reads the current LLM + Embedder config from ``config/settings.json`` and any
override env vars (per the provider registry), encrypts the sensitive fields
with Fernet, and writes two singleton docs into the ``ask-system-settings-v1``
index. Idempotent: docs that already exist are SKIPPED — re-run safely.

Run AFTER setting ``ONIBEX_ENCRYPTION_KEY`` in the environment.

Usage::

    # 1. Generate the master key (save somewhere safe)
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    # 2. Add to .env (dev) or K8s Secret (prod)
    echo "ONIBEX_ENCRYPTION_KEY=<paste-here>" >> .env

    # 3. Run the migration
    python scripts/migrate_secrets_to_opensearch.py

    # 4. Verify via the SPA Setup page or:
    curl http://localhost:8081/v1/admin/secrets/llm
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ask_llm_gateway.infrastructure.secrets import (
    SecretsRepository,
    provider_fields,
)
from ask_llm_gateway.infrastructure.secrets.crypto import validate_master_key

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
    for target in ("llm", "embedder"):
        section = cfg.get(target) or {}
        provider = (section.get("provider") or "").strip()
        if not provider:
            print(f"[skip] {target}: no provider configured in settings.json")
            continue

        existing = repo.get_raw(target)
        if existing is not None:
            print(f"[skip] {target}: already in OpenSearch (run with care)")
            continue

        # Merge section + section.params + env-var overrides per the registry.
        combined: dict[str, str] = {}
        for fname, _sensitive in provider_fields(provider):
            if fname in section:
                combined[fname] = str(section[fname])
        for k, v in (section.get("params") or {}).items():
            combined[str(k)] = str(v)
        for fname, _sensitive in provider_fields(provider):
            env_val = os.environ.get(fname)
            if env_val:
                combined[fname] = env_val
        # Legacy convenience: LLM_API_KEY-style env vars too.
        prefix = "LLM_" if target == "llm" else "EMBEDDER_"
        for fname, _sensitive in provider_fields(provider):
            if fname in ("api_key", "api_base", "api_version", "deployment_id"):
                env_val = os.environ.get(f"{prefix}{fname.upper()}")
                if env_val:
                    combined[fname] = env_val

        repo.upsert(
            target,
            provider=provider,
            model=str(section.get("model") or ""),
            fields=combined,
            updated_by="migration-script",
        )
        migrated_any = True
        plain_count = sum(1 for n, s in provider_fields(provider) if not s and n in combined)
        encrypted_count = sum(1 for n, s in provider_fields(provider) if s and n in combined)
        print(
            f"[ok]   {target}: provider={provider} model={section.get('model')} "
            f"plain={plain_count} encrypted={encrypted_count}"
        )

    if migrated_any:
        # Strip the migrated sections from settings.json (canonical source moves
        # to OpenSearch). Domain tuning stays.
        cfg.pop("llm", None)
        cfg.pop("embedder", None)
        cfg.pop("opensearch", None)
        SETTINGS_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[ok]   {SETTINGS_PATH} cleaned (llm/embedder/opensearch sections removed)")
    else:
        print("[ok]   nothing to migrate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
