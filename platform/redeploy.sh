#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

# =============================================================================
# redeploy.sh — Rebuild + recreate the full ASK stack from the current source.
#
# Bakes in whatever is in the working tree. The backend packages (ask-admin-api,
# ask-orchestrator, …) are installed INTO the image at build time — there is NO
# source bind-mount — so a rebuild is REQUIRED for any backend code change to
# take effect. `restart` alone reuses the old image and does nothing.
#
# Run this ON THE HOST that serves the stack, after a `git pull` (or after
# extracting a deploy tarball). The Docker build context is this repo, so the
# host must already contain the sources you want in the images.
#
# Every host runs the SAME compose file — the only difference is what's in .env
# (EXTERNAL_HOST, port remaps, CHAT_AUTH_MODE). There is no per-host overlay.
#
# Usage:
#   ./redeploy.sh                       # rebuild + recreate the full stack
#   ONLY=ask-admin-api ./redeploy.sh    # rebuild/recreate a single service
#   NO_CACHE=1 ./redeploy.sh            # force a clean rebuild (slower)
#
# Does NOT touch volumes — OpenSearch indices + the semantic-layer git repo are
# preserved. For a destructive wipe, run `docker compose down -v` yourself.
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found in $(pwd)." >&2
  echo "       Copy .env.ec2.example -> .env and fill it in first." >&2
  exit 1
fi

# Compose v2 comes in two shapes and a box may have only one: the CLI plugin
# (`docker compose`) or the standalone binary (`docker-compose`). They take the
# same flags, so either will do — but hardcoding the plugin form fails on a box
# that has only the standalone one in a way that accuses the wrong tool: with no
# `compose` subcommand the Docker CLI keeps parsing the rest as GLOBAL flags and
# reports `unknown shorthand flag: 'f' in -f` against docker's own usage, naming
# neither compose nor the real cause.
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose -f docker-compose.yml)
elif command -v docker-compose >/dev/null 2>&1; then
  # Reject the legacy Python v1: it silently disagrees with this compose file
  # (healthcheck conditions, build args, service profiles) instead of failing
  # cleanly, which is far more expensive to diagnose than this message.
  if [[ "$(docker-compose version --short 2>/dev/null)" == 1.* ]]; then
    echo "ERROR: docker-compose $(docker-compose version --short) is the legacy v1." >&2
    echo "       This stack needs Compose v2. Install the CLI plugin, or symlink an" >&2
    echo "       existing v2 binary: ln -sf \"\$(command -v docker-compose)\" \\" >&2
    echo "       ~/.docker/cli-plugins/docker-compose" >&2
    exit 1
  fi
  COMPOSE=(docker-compose -f docker-compose.yml)
else
  echo "ERROR: no Compose found — neither 'docker compose' (CLI plugin) nor" >&2
  echo "       'docker-compose' (standalone v2) is available on PATH." >&2
  exit 1
fi
echo "==> Compose: ${COMPOSE[*]}"

BUILD_ARGS=()
[[ "${NO_CACHE:-0}" == "1" ]] && BUILD_ARGS+=(--no-cache)

SERVICES="${ONLY:-}"

echo "==> Building images ${SERVICES:+for [$SERVICES]}..."
# `"${BUILD_ARGS[@]+...}"` and not a plain `"${BUILD_ARGS[@]}"`: under `set -u`,
# bash BEFORE 4.4 treats expanding an EMPTY array as an unbound variable and
# aborts. Amazon Linux 2 ships bash 4.2, so the plain form worked on every dev
# machine and failed on the box the moment NO_CACHE was unset — which is the
# default path. The `+` form expands to nothing when the array is empty and to
# its elements otherwise, on every version.
"${COMPOSE[@]}" build "${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"}" ${SERVICES}

echo "==> Recreating containers ${SERVICES:+for [$SERVICES]}..."
"${COMPOSE[@]}" up -d --force-recreate ${SERVICES}

echo "==> Status:"
"${COMPOSE[@]}" ps

echo
echo "==> Done. Tail the admin-api logs with:"
echo "    docker logs -f agenticai-admin-api"
