#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

# =============================================================================
# package-ec2.sh — Build (and optionally ship) the EC2 deploy tarball.
#
# Runs ON YOUR DEV MACHINE (Git Bash / WSL / macOS / Linux). Produces a single
# .tar.gz of the repo working tree with the heavy build artifacts stripped, ready
# to scp to an EC2 box and extract into ~/onibex-ask/.
#
# EC2 and local run the SAME docker-compose.yml — the only difference is .env —
# so there is nothing EC2-specific to package: this ships the whole tree minus
# what the host rebuilds itself (SPAs are built ON the host; Python packages are
# installed INTO the images). See redeploy.sh for the on-box rebuild step.
#
# WHAT IS DELIBERATELY EXCLUDED
#   node_modules, dist        the SPAs are (re)built on the host from source
#   .venv / venv / __pycache__ / *.pyc     Python is installed into the images
#   .git                      the box builds from the working tree, not history
#   .env                      SECRETS — never leave your machine. The box has its
#                             own .env (cp .env.ec2.example .env). The templates
#                             .env.ec2.example / .env.example ARE included.
#   config/aicore_config.json SAP AI Core creds — a secret; provision on the host
#                             (or use Bedrock IAM / the ASK Setup UI). settings.json
#                             and api-config.json still ship.
#   config/chats|profiles|artifacts   RUNTIME state, not deploy input: chat
#                             transcripts, user profiles and generated artifacts
#                             from whoever ran the stack locally. `./config` is a
#                             bind mount, so shipping these makes the box SERVE
#                             one developer's conversations as if they were its
#                             own. Each directory is created on demand at
#                             runtime, so its absence is a no-op.
#   logs/, scratch/, caches   local-only noise
#
# Usage:
#   ./scripts/package-ec2.sh                       # -> ../onibex-ask-deploy.tar.gz
#   OUT=/tmp/ask.tar.gz ./scripts/package-ec2.sh   # custom output path
#   ./scripts/package-ec2.sh --upload \            # build + scp to the box
#       --host ec2-user@<EC2-IP> --key ~/keys/dev.pem
#   EC2_HOST=ec2-user@<IP> EC2_KEY=~/keys/dev.pem ./scripts/package-ec2.sh --upload
#
# After upload, on the host:
#   mkdir -p ~/onibex-ask && tar -xzf ~/onibex-ask-deploy.tar.gz -C ~/onibex-ask/
#   cd ~/onibex-ask && cp .env.ec2.example .env && nano .env   # first time only
#   ./redeploy.sh                                                # build + start
# =============================================================================
set -euo pipefail

# ── Resolve repo root (this script lives in <root>/scripts/) ─────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_NAME="$(basename "$REPO_ROOT")"

# ── Args / env ───────────────────────────────────────────────────────────────
OUT="${OUT:-$(dirname "$REPO_ROOT")/${REPO_NAME}-deploy.tar.gz}"
UPLOAD=0
EC2_HOST="${EC2_HOST:-}"
EC2_KEY="${EC2_KEY:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --upload)  UPLOAD=1; shift ;;
    --host)    EC2_HOST="$2"; shift 2 ;;
    --key)     EC2_KEY="$2"; shift 2 ;;
    --out)     OUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,40p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

# ── Sanity: is this the repo we think it is? ─────────────────────────────────
if [[ ! -f "$REPO_ROOT/docker-compose.yml" ]]; then
  echo "ERROR: $REPO_ROOT/docker-compose.yml not found — is scripts/ in the repo root?" >&2
  exit 1
fi

# ── GNU tar on Windows reads "C:/path" as host:path; --force-local fixes it. ──
# Only add it for a drive-letter OUT (harmless on Linux GNU tar; absent on the
# box where paths are POSIX). Prefer a POSIX OUT (/c/…) to avoid needing it.
TAR_LOCAL=()
[[ "$OUT" =~ ^[A-Za-z]: ]] && TAR_LOCAL=(--force-local)

# ── Exclude set (see header). Patterns are matched by GNU tar after any '/'. ──
EXCLUDES=(
  --exclude=.git
  --exclude=node_modules
  --exclude=dist
  --exclude=.venv
  --exclude=venv
  --exclude=__pycache__
  --exclude='*.pyc'
  --exclude=.pytest_cache
  --exclude=.mypy_cache
  --exclude=.import_linter_cache
  --exclude=.ruff_cache
  --exclude='*.egg-info'
  --exclude=.claude
  --exclude=logs
  --exclude=scratch
  --exclude=./.env                        # exact local secrets file — templates are kept
  --exclude=./config/aicore_config.json   # SAP AI Core creds — provision on the host
  --exclude=./config/chats                # runtime chat transcripts — see header
  --exclude=./config/profiles             # runtime user profiles
  --exclude=./config/artifacts            # runtime generated artifacts
  --exclude='*.tar.gz'                    # don't nest a previous artifact
)

echo "==> Packaging $REPO_NAME"
echo "    root : $REPO_ROOT"
echo "    out  : $OUT"

rm -f "$OUT"
# -C parents the archive at the repo root so members are ./packages, ./config …
# extracting with `tar -xzf … -C ~/onibex-ask/` drops them in place.
# `"${TAR_LOCAL[@]+...}"`: TAR_LOCAL is EMPTY off Windows, and under `set -u` bash
# before 4.4 (Amazon Linux 2 ships 4.2) aborts on expanding an empty array. Same
# fix as redeploy.sh — see the note there.
tar "${TAR_LOCAL[@]+"${TAR_LOCAL[@]}"}" -czf "$OUT" -C "$REPO_ROOT" "${EXCLUDES[@]}" .

# ── Safety assert: .env must NOT be in the archive; templates MUST be. ────────
# List once into a var (grep -q on a live `tar | grep` pipe would SIGPIPE tar and
# trip `pipefail`, misreporting a real match as a miss).
LISTING="$(tar "${TAR_LOCAL[@]+"${TAR_LOCAL[@]}"}" -tzf "$OUT")"
if grep -qxE '\./\.env' <<<"$LISTING"; then
  echo "FATAL: .env leaked into the archive — aborting." >&2
  rm -f "$OUT"; exit 1
fi
# Same treatment for the two other classes that must never travel: the AI Core
# credentials, and the runtime state under config/. An exclude typo is silent —
# the archive just quietly carries one developer's chat history to a shared box —
# so the check is here rather than left to whoever remembers to list the tarball.
if LEAK="$(grep -nE '^\./config/(aicore_config\.json|chats/|profiles/|artifacts/)' <<<"$LISTING" | head -3)"; [[ -n "$LEAK" ]]; then
  echo "FATAL: local/runtime config leaked into the archive — aborting:" >&2
  echo "$LEAK" >&2
  rm -f "$OUT"; exit 1
fi
grep -qxE '\./\.env\.ec2\.example' <<<"$LISTING" \
  || echo "WARN: .env.ec2.example not found in archive (expected it)." >&2

SIZE="$(du -h "$OUT" | cut -f1)"
echo "==> Built $OUT ($SIZE)"

# ── Optional upload ──────────────────────────────────────────────────────────
if [[ "$UPLOAD" == "1" ]]; then
  [[ -n "$EC2_HOST" ]] || { echo "ERROR: --upload needs --host user@ip (or EC2_HOST)." >&2; exit 1; }
  SCP=(scp)
  [[ -n "$EC2_KEY" ]] && SCP+=(-i "$EC2_KEY")
  echo "==> Uploading to $EC2_HOST:~/"
  "${SCP[@]}" "$OUT" "$EC2_HOST:~/"
  echo "==> Uploaded. On the host:"
  echo "    mkdir -p ~/onibex-ask && tar -xzf ~/$(basename "$OUT") -C ~/onibex-ask/"
  echo "    cd ~/onibex-ask && cp .env.ec2.example .env && nano .env   # first time"
  echo "    ./redeploy.sh"
else
  echo "==> Next: scp it to the box, or re-run with --upload --host user@ip --key key.pem"
fi
