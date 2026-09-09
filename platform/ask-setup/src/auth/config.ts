/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * Where this app's authentication configuration comes from.
 *
 * `window.__ENV__`, set by /config.js, which the container entrypoint renders
 * from the environment at start. It used to come from `import.meta.env.VITE_*`,
 * baked into the bundle by Vite at build time, which made three SPAs times
 * three cloud targets nine image builds and turned every change of cluster
 * domain into a rebuild.
 *
 * There is deliberately NO fallback to the old build-time variables. Two
 * configuration paths is precisely how a production SPA ends up pointing at
 * localhost, and a fallback guarantees the two drift.
 */

import type { RuntimeEnv } from '../runtime-env'

export interface AuthConfig {
  mode: 'keycloak' | 'xsuaa' | 'none'
  issuerUrl: string
  authorizationEndpoint: string
  tokenEndpoint: string
  /** RP-initiated logout (end-session) endpoint — terminates the IdP SSO session. */
  endSessionEndpoint: string
  clientId: string
  redirectUri: string
  scopes: string[]
}

/**
 * The runtime configuration, or a loud failure.
 *
 * Reaching this without /config.js means the page was served without it, which
 * is a deployment fault rather than a user one. Throwing here surfaces it on
 * the first paint instead of letting the app render a login button that
 * silently points nowhere.
 */
export function runtimeEnv(): RuntimeEnv {
  const env = window.__ENV__
  if (!env || !env.AUTH_MODE) {
    throw new Error(
      'ASK Setup: /config.js did not load, so there is no runtime configuration. ' +
        'It is rendered by the container entrypoint from ASK_AUTH_MODE and the ' +
        'variables that go with it, and index.html must load it before the app bundle.',
    )
  }
  return env
}

function buildKeycloakConfig(env: RuntimeEnv): AuthConfig {
  const issuerUrl = `${env.KEYCLOAK_URL.replace(/\/$/, '')}/realms/${env.KEYCLOAK_REALM}`

  return {
    mode: 'keycloak',
    issuerUrl,
    authorizationEndpoint: `${issuerUrl}/protocol/openid-connect/auth`,
    tokenEndpoint: `${issuerUrl}/protocol/openid-connect/token`,
    endSessionEndpoint: `${issuerUrl}/protocol/openid-connect/logout`,
    clientId: env.KEYCLOAK_CLIENT_ID,
    redirectUri: `${window.location.origin}/login/callback`,
    scopes: ['openid', 'profile', 'email'],
  }
}

function buildXsuaaConfig(env: RuntimeEnv): AuthConfig {
  const baseUrl = env.XSUAA_URL.replace(/\/$/, '')

  return {
    mode: 'xsuaa',
    issuerUrl: baseUrl,
    authorizationEndpoint: `${baseUrl}/oauth/authorize`,
    tokenEndpoint: `${baseUrl}/oauth/token`,
    endSessionEndpoint: `${baseUrl}/logout`,
    clientId: env.XSUAA_CLIENT_ID,
    redirectUri: `${window.location.origin}/login/callback`,
    scopes: ['openid'],
  }
}

function buildNoneConfig(): AuthConfig {
  return {
    mode: 'none',
    issuerUrl: '',
    authorizationEndpoint: '',
    tokenEndpoint: '',
    endSessionEndpoint: '',
    clientId: '',
    redirectUri: `${window.location.origin}/login/callback`,
    scopes: [],
  }
}

function resolveAuthConfig(): AuthConfig {
  const env = runtimeEnv()

  if (env.AUTH_MODE === 'keycloak') {
    return buildKeycloakConfig(env)
  }

  if (env.AUTH_MODE === 'xsuaa') {
    return buildXsuaaConfig(env)
  }

  // 'none' only, and only because somebody set it. An unknown value never
  // reaches here: the entrypoint rejects it before nginx starts.
  return buildNoneConfig()
}

export const authConfig: AuthConfig = resolveAuthConfig()
