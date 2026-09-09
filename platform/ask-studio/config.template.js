/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/*
 * Template for /config.js, rendered by docker-entrypoint-ask.sh with envsubst
 * at container start and served before the app bundle.
 *
 * This is what replaced the VITE_* build arguments. Vite substituted those
 * into the bundle at build time, so three SPAs times three cloud targets was
 * nine image builds and every change of cluster domain was a rebuild.
 *
 * Nothing here has a default. The entrypoint refuses to start when a required
 * variable is missing, so an empty string never reaches this file.
 */
window.__ENV__ = {
  AUTH_MODE: '${ASK_AUTH_MODE}',
  KEYCLOAK_URL: '${ASK_KEYCLOAK_URL}',
  KEYCLOAK_REALM: '${ASK_KEYCLOAK_REALM}',
  KEYCLOAK_CLIENT_ID: '${ASK_KEYCLOAK_CLIENT_ID}',
  XSUAA_URL: '${ASK_XSUAA_URL}',
  XSUAA_CLIENT_ID: '${ASK_XSUAA_CLIENT_ID}',
  // Cross-app links. Optional: when empty, ASK Studio hides the link rather
  // than rendering one that goes nowhere.
  SETUP_SPA_URL: '${ASK_SETUP_SPA_URL}',
  CHAT_URL: '${ASK_CHAT_URL}',
}
