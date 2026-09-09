# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""One-shot migration: ``config/api-config.json`` → the API contracts index.

Third of its kind, and deliberately the same shape as
``migrate_db_config_to_opensearch.py`` and ``migrate_secrets_to_opensearch.py``:
read the legacy file, write through the repository, skip a target that already
has data so a re-run is safe.

**Why this one exists when the SAP connection move had no importer.** That was
five form fields, so re-entering them once was cheaper than a script. Contracts
are about 5 KB of hand-authored OData entity sets, keys and field definitions,
and a deployment that loses them loses every tool the MCP server exposes until
somebody reconstructs the file. Writing through the repository costs fifty
lines, so the trade goes the other way here.

Unlike the other two migrations, nothing is encrypted: contracts are a
contract, not a credential.

**Getting the old file.** It is no longer in the tree. Any machine that ran the
stack still has it under ``config/``, and it is in git history regardless::

    git show 0b9cc74:platform/config/api-config.json > /tmp/api-config.json

Usage::

    # dev, from the recovered file
    python scripts/migrate_api_contracts_to_opensearch.py /tmp/api-config.json

    # prod points at a different SAP system, so it gets its own contracts
    python scripts/migrate_api_contracts_to_opensearch.py /tmp/prod.json --env prod

    # Verify (the same surface the MCP server reads):
    curl -H "X-API-Key: $ASK_INGEST_API_KEY" \\
        "http://localhost:8081/v1/internal/api-contracts?env=dev"

Needs ``OPENSEARCH_*`` in the environment, the same as the services.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ask_admin_api.application.contracts_repository import ContractsRepository

_DEFAULT_FILE = Path("config/api-config.json")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        default=_DEFAULT_FILE,
        help=f"Legacy api-config.json (default: {_DEFAULT_FILE})",
    )
    parser.add_argument("--env", default="dev", choices=("dev", "prod"))
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite contracts already stored for this environment",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if not args.file.is_file():
        print(
            f"{args.file} does not exist. Recover it from git history:\n"
            "    git show 0b9cc74:platform/config/api-config.json > /tmp/api-config.json",
            file=sys.stderr,
        )
        return 2

    try:
        config = json.loads(args.file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"{args.file} is not valid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(config, dict):
        print(f"{args.file} does not contain a JSON object.", file=sys.stderr)
        return 2

    repo = ContractsRepository(env=args.env)
    existing = repo.get()
    if existing is not None and not args.force:
        stored = len(existing.get("apis") or [])
        print(
            f"{repo.index} already holds contracts ({stored} api(s)). SKIPPED. "
            "Pass --force to overwrite.",
            file=sys.stderr,
        )
        return 0

    repo.upsert(config, updated_by="migrate_api_contracts_to_opensearch")
    print(
        f"Wrote {len(config.get('apis') or [])} api(s) to {repo.index}. "
        "Restart the MCP server (POST /v1/admin/mcp/restart) to pick them up."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
