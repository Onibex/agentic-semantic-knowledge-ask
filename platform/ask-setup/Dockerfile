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

# No VITE_* build arguments. The auth configuration is a runtime value now: the
# entrypoint renders it into /config.js from the environment when the container
# starts. Baking it in made three SPAs times three cloud targets nine image
# builds, and every change of cluster domain a rebuild. Docker's own linter
# flagged them as SecretsUsedInArgOrEnv too.
#
# This image is therefore identical for EKS, AKS and Kyma.

# Call vite directly (skip the `tsc -b` in `npm run build`) — same as ask-studio.
# Type-checking stays a dev/CI concern; the image build only needs the bundle.
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
