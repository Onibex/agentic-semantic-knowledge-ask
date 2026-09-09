#!/bin/sh
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.
#
# Renders /config.js and the security headers from the environment, then hands
# over to the stock nginx entrypoint.
#
# THE FAILING IS THE FEATURE. A missing variable stops the container with a
# message naming it. It must never substitute an empty string and never fall
# back to localhost: the old build-time default was http://localhost:8180, so a
# deployment that forgot a build argument did not fail, it shipped a login page
# pointing at a host that does not exist, with no error anywhere.

set -e

APP_NAME="ASK Chat"
HTML_DIR=/usr/share/nginx/html
TEMPLATE=/etc/nginx/ask/config.template.js
OUTPUT="$HTML_DIR/config.js"
HEADERS=/etc/nginx/ask/security-headers.conf

fail() {
  echo "[ask-config] FATAL: $1" >&2
  echo "[ask-config] $APP_NAME cannot start. Set it and try again." >&2
  exit 1
}

require() {
  eval "_value=\${$1:-}"
  [ -n "$_value" ] || fail "$1 is not set."
}

# ── Validate ────────────────────────────────────────────────────────────────
require ASK_AUTH_MODE

case "$ASK_AUTH_MODE" in
  keycloak)
    require ASK_KEYCLOAK_URL
    require ASK_KEYCLOAK_REALM
    require ASK_KEYCLOAK_CLIENT_ID
    IDP_ORIGIN=$(echo "$ASK_KEYCLOAK_URL" | sed -E 's#^([a-zA-Z]+://[^/]+).*#\1#')
    ;;
  xsuaa)
    require ASK_XSUAA_URL
    require ASK_XSUAA_CLIENT_ID
    IDP_ORIGIN=$(echo "$ASK_XSUAA_URL" | sed -E 's#^([a-zA-Z]+://[^/]+).*#\1#')
    ;;
  none)
    echo "[ask-config] WARNING: ASK_AUTH_MODE=none. There is no login on this deployment."
    IDP_ORIGIN=""
    ;;
  *)
    fail "ASK_AUTH_MODE is '$ASK_AUTH_MODE'; expected keycloak, xsuaa or none."
    ;;
esac

export ASK_KEYCLOAK_URL="${ASK_KEYCLOAK_URL:-}"
export ASK_KEYCLOAK_REALM="${ASK_KEYCLOAK_REALM:-}"
export ASK_KEYCLOAK_CLIENT_ID="${ASK_KEYCLOAK_CLIENT_ID:-}"
export ASK_XSUAA_URL="${ASK_XSUAA_URL:-}"
export ASK_XSUAA_CLIENT_ID="${ASK_XSUAA_CLIENT_ID:-}"

# ── Render /config.js ───────────────────────────────────────────────────────
[ -f "$TEMPLATE" ] || fail "$TEMPLATE is missing from the image."
envsubst < "$TEMPLATE" > "$OUTPUT"
echo "[ask-config] wrote $OUTPUT (mode=$ASK_AUTH_MODE)"

# ── Render the security headers ─────────────────────────────────────────────
# connect-src carries the identity provider's origin because it is a runtime
# value: a static nginx.conf cannot know it, and the alternative, a wildcard,
# would remove the one protection that matters most for a token-holding SPA.
mkdir -p "$(dirname "$HEADERS")"
cat > "$HEADERS" <<EOF
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self' ${IDP_ORIGIN}; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header X-Frame-Options "DENY" always;
EOF

exec /docker-entrypoint.sh "$@"
