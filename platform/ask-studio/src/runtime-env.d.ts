/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * The runtime configuration served as /config.js before the app bundle.
 *
 * It is written by the container entrypoint from the environment, so changing
 * a cluster domain is a restart rather than a rebuild. In `npm run dev` the
 * same file is served by the middleware in vite.config.ts, so there is one
 * mechanism everywhere.
 */
export interface RuntimeEnv {
  AUTH_MODE: 'keycloak' | 'xsuaa' | 'none'
  KEYCLOAK_URL: string
  KEYCLOAK_REALM: string
  KEYCLOAK_CLIENT_ID: string
  XSUAA_URL: string
  XSUAA_CLIENT_ID: string
  /** Cross-app links. Empty means "not deployed"; the link is hidden. */
  SETUP_SPA_URL: string
  CHAT_URL: string
}

declare global {
  interface Window {
    __ENV__?: RuntimeEnv
  }
}
