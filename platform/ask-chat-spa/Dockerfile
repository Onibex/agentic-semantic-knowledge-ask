# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

# ── Stage 1: build ──────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

COPY package*.json ./
# npm install (not `npm ci`): Arborist 10.x rejects this otherwise-valid
# lockfile (Node JSON.parse loads it: lockfileVersion 3, 435 pkgs) with a
# spurious "no package-lock.json" EUSAGE. `npm install` resolves the same tree
# and builds reliably. --legacy-peer-deps keeps the peer-conflict tolerance.
RUN npm install --legacy-peer-deps --no-audit --no-fund

COPY . .

ARG VITE_AUTH_MODE=keycloak
ARG VITE_KEYCLOAK_URL=http://localhost:8180
ARG VITE_KEYCLOAK_REALM=ask-platform

ENV VITE_AUTH_MODE=$VITE_AUTH_MODE
ENV VITE_KEYCLOAK_URL=$VITE_KEYCLOAK_URL
ENV VITE_KEYCLOAK_REALM=$VITE_KEYCLOAK_REALM

# vite build directly (skip tsc -b) - same as ask-admin-spa / ask-setup-spa
RUN node node_modules/vite/bin/vite.js build

# ── Stage 2: serve ──────────────────────────────────────────────────────────
FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
