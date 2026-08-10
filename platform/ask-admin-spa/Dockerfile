# ── Stage 1: build ──────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

COPY package*.json ./
# --legacy-peer-deps: TS 6 is newer than openapi-typescript's declared peer
# (^5.x). The package still works fine with TS 6 — only the codegen output is
# generated and validation happens at our tsc level, not theirs.
RUN npm ci --prefer-offline --legacy-peer-deps && chmod -R +x node_modules/.bin/

COPY . .

# Vite bakes estos valores en el bundle en build time.
# Para cambiarlos en otro entorno, rebuildeá con --build-arg.
# Default matches docker-compose's host port mapping (8180:8080). Anyone doing
# a plain `docker build` (no --build-arg) gets the URL the BROWSER can reach.
ARG VITE_AUTH_MODE=keycloak
ARG VITE_KEYCLOAK_URL=http://localhost:8180
ARG VITE_KEYCLOAK_REALM=ask-platform
# Cross-app link target: ASK Setup (setup-spa) — LLM is managed there, shown
# read-only here. Must be the URL the BROWSER can reach (not the Docker net).
ARG VITE_SETUP_SPA_URL=http://localhost:5175

ENV VITE_AUTH_MODE=$VITE_AUTH_MODE
ENV VITE_KEYCLOAK_URL=$VITE_KEYCLOAK_URL
ENV VITE_KEYCLOAK_REALM=$VITE_KEYCLOAK_REALM
ENV VITE_SETUP_SPA_URL=$VITE_SETUP_SPA_URL

RUN node node_modules/vite/bin/vite.js build

# ── Stage 2: serve ──────────────────────────────────────────────────────────
FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
