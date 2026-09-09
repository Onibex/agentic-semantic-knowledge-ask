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
# --legacy-peer-deps: TS 6 is newer than openapi-typescript's declared peer
# (^5.x). The package still works fine with TS 6 — only the codegen output is
# generated and validation happens at our tsc level, not theirs.
RUN npm ci --prefer-offline --legacy-peer-deps && chmod -R +x node_modules/.bin/

COPY . .

# No VITE_* build arguments. The auth configuration and the cross-app links are
# runtime values now: the entrypoint renders them into /config.js from the
# environment when the container starts. Baking them in made three SPAs times
# three cloud targets nine image builds, and every change of cluster domain a
# rebuild. Docker's own linter flagged them as SecretsUsedInArgOrEnv too.
#
# This image is therefore identical for EKS, AKS and Kyma.
RUN node node_modules/vite/bin/vite.js build

# ── Stage 2: serve ──────────────────────────────────────────────────────────
FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Rendered at container start into /usr/share/nginx/html/config.js and
# /etc/nginx/ask/security-headers.conf, both of which nginx.conf expects.
COPY config.template.js /etc/nginx/ask/config.template.js
COPY docker-entrypoint-ask.sh /docker-entrypoint-ask.sh
RUN sed -i 's/\r//' /docker-entrypoint-ask.sh && chmod +x /docker-entrypoint-ask.sh

EXPOSE 80
# Validates, renders, then hands over to nginx's own entrypoint, so the stock
# behaviour (the /docker-entrypoint.d hooks) is preserved.
ENTRYPOINT ["/docker-entrypoint-ask.sh"]
CMD ["nginx", "-g", "daemon off;"]
