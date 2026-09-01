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
RUN npm ci --prefer-offline --legacy-peer-deps && chmod -R +x node_modules/.bin/

COPY . .

# Vite bakes these into the bundle at build time; rebuild with --build-arg to change.
# VITE_KEYCLOAK_URL must be the URL the BROWSER reaches (host), not the internal
# docker network — hence localhost:8180, not keycloak:8080.
ARG VITE_AUTH_MODE=keycloak
ARG VITE_KEYCLOAK_URL=http://localhost:8180
ARG VITE_KEYCLOAK_REALM=ask-platform

ENV VITE_AUTH_MODE=$VITE_AUTH_MODE
ENV VITE_KEYCLOAK_URL=$VITE_KEYCLOAK_URL
ENV VITE_KEYCLOAK_REALM=$VITE_KEYCLOAK_REALM

# Call vite directly (skip the `tsc -b` in `npm run build`) — same as ask-studio.
# Type-checking stays a dev/CI concern; the image build only needs the bundle.
RUN node node_modules/vite/bin/vite.js build

# ── Stage 2: serve ──────────────────────────────────────────────────────────
FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
