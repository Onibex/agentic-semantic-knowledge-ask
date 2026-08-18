# syntax=docker/dockerfile:1.6
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

# ─────────────────────────────────────────────────────────────────────────────
# ASK Orchestrator — FastAPI image.
# ─────────────────────────────────────────────────────────────────────────────
# Build context: project root (contains config/ + packages/).
# The orchestrator chains typed packages directly. API-only image: it serves
# REST; the React SPAs are separate nginx images.

FROM python:3.12-slim AS builder

WORKDIR /app

# Bring uv from the official image — 10-100x faster than pip. Cache strategy:
#  * requirements.txt (heavy 3rd-party wheels) → cached via the mount, NO
#    --no-cache, so rebuilds don't re-download google/langchain/litellm/etc.
#  * local ask-* packages → installed WITH --no-cache. They all share version
#    0.1.0, so uv would otherwise serve a STALE cached wheel and your source edits
#    would NOT land (a plain `docker compose up -d --build` would look like a no-op
#    — the symptom that led here). Their build is cheap and deps are already
#    satisfied by requirements.txt, so --no-cache just guarantees fresh source.
COPY --from=ghcr.io/astral-sh/uv:0.5.13 /uv /uvx /usr/local/bin/

# System deps for hdbcli, psycopg, opensearch
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        curl \
        && rm -rf /var/lib/apt/lists/*

ENV UV_LINK_MODE=copy

# Install third-party deps shared across the typed packages (langchain,
# langgraph, opensearch-py, hdbcli, gen_ai_hub, etc.).
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt

# Install the typed packages the orchestrator consumes. Editable installs
# preserve source layout so traces resolve cleanly. Order matters: install
# leaf packages first so dependent installs find them.
COPY packages/ask-llm-gateway/pyproject.toml         packages/ask-llm-gateway/
COPY packages/ask-llm-gateway/src                    packages/ask-llm-gateway/src
# litellm + langchain-litellm are BASE deps of ask-llm-gateway (the LiteLLM
# backend serves every non-sap_aicore provider) — installed by the bare package.
# The local offline embedder (langchain-huggingface + sentence-transformers) is
# HEAVY (pulls torch + CUDA, several GB) and most deployments never use it, so it
# is NOT installed by default. To test the `huggingface` embedder, rebuild with:
#   docker compose build --build-arg GATEWAY_EXTRAS="[huggingface]" ask-orchestrator
# (or set GATEWAY_EXTRAS in your env — compose forwards it; see docker-compose.yml).
ARG GATEWAY_EXTRAS=
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache "packages/ask-llm-gateway${GATEWAY_EXTRAS}"

COPY packages/ask-knowledge-graph/pyproject.toml     packages/ask-knowledge-graph/
COPY packages/ask-knowledge-graph/src                packages/ask-knowledge-graph/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache packages/ask-knowledge-graph

# The Flash chunk-RAG backend lives INSIDE this package
# (ask_intent_resolution.flash.infrastructure) — nothing extra to install.
COPY packages/ask-intent-resolution/pyproject.toml   packages/ask-intent-resolution/
COPY packages/ask-intent-resolution/src              packages/ask-intent-resolution/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache packages/ask-intent-resolution

COPY packages/ask-sql-generation/pyproject.toml      packages/ask-sql-generation/
COPY packages/ask-sql-generation/src                 packages/ask-sql-generation/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache packages/ask-sql-generation

COPY packages/ask-sql-executor/pyproject.toml        packages/ask-sql-executor/
COPY packages/ask-sql-executor/src                   packages/ask-sql-executor/src
# Multi-DB drivers are OPTIONAL extras (lite multi-DB, 2026-07). Default build is
# slim (HANA + PostgreSQL only — their drivers come from requirements.txt). To
# test extra backends, pass the extras at build time, e.g.:
#   EXECUTOR_EXTRAS="[snowflake,databricks,clickhouse,bigquery]" docker compose up -d --build
# These four are pure-pip. NOTE: sqlserver / fabric additionally need the system
# "ODBC Driver 18 for SQL Server" (unixodbc + msodbcsql18) and db2 needs the IBM
# clidriver — add those apt packages before enabling those extras.
ARG EXECUTOR_EXTRAS=
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache "packages/ask-sql-executor${EXECUTOR_EXTRAS}"

COPY packages/ask-schema-service/pyproject.toml      packages/ask-schema-service/
COPY packages/ask-schema-service/src                 packages/ask-schema-service/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache packages/ask-schema-service

COPY packages/ask-docs-service/pyproject.toml        packages/ask-docs-service/
COPY packages/ask-docs-service/src                   packages/ask-docs-service/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache packages/ask-docs-service

# ACTION_EXECUTION handler (SAP write ops via MCP) — its own package, required
# by ask-orchestrator routers/query.py.
COPY packages/ask-action-execution/pyproject.toml    packages/ask-action-execution/
COPY packages/ask-action-execution/src               packages/ask-action-execution/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache packages/ask-action-execution

COPY packages/ask-orchestrator/pyproject.toml        packages/ask-orchestrator/
COPY packages/ask-orchestrator/src                   packages/ask-orchestrator/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache packages/ask-orchestrator


# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        && rm -rf /var/lib/apt/lists/*
# `curl` is needed by the healthcheck (CMD curl -f .../v1/health). In Kyma
# the kubelet runs the HTTP probe externally so this dependency was never
# noticed; under docker-compose / Docker HEALTHCHECK, the command runs
# inside the container and `curl` must be present.

# Non-root runtime user
RUN useradd --create-home --uid 1000 app

WORKDIR /app

# Bring across installed Python packages and CLIs from the builder.
# pip install (non-editable) copies each package into site-packages, so
# the runtime stage doesn't need /app/packages — kept only the
# site-packages tree + entrypoints.
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Orchestrator image is backend-only: the typed packages installed above are
# self-contained, so the only project tree the runtime still needs is config/
# (settings.json + api-config.json), overridden by the PVC / bind mount.
COPY config /app/config

ENV PYTHONPATH=/app

# Production posture by default. Kyma ConfigMap MUST keep these as-is.
# WARNING: NEVER set DEV_BYPASS_AUTH=true in any non-local environment.
ENV ENVIRONMENT=production \
    DEV_BYPASS_AUTH=false \
    LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://127.0.0.1:8080/v1/health || exit 1

CMD ["uvicorn", "ask_orchestrator.main:app", "--host", "0.0.0.0", "--port", "8080"]
