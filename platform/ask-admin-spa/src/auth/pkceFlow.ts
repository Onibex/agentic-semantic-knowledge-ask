/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { authConfig } from './config'

export interface TokenSet {
  accessToken: string
  idToken?: string
  refreshToken?: string
  expiresAt: number // Date.now() + expires_in * 1000
}

// ─── PKCE helpers ────────────────────────────────────────────────────────────

/** Encode a Uint8Array to base64url (no padding, url-safe) */
function base64urlEncode(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let str = ''
  for (const byte of bytes) {
    str += String.fromCharCode(byte)
  }
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
}

/** Generate a cryptographically random code_verifier (64 random bytes → base64url) */
function generateVerifier(): string {
  const randomBytes = new Uint8Array(64)
  crypto.getRandomValues(randomBytes)
  return base64urlEncode(randomBytes.buffer)
}

/** Derive the code_challenge = BASE64URL(SHA-256(verifier)) */
async function deriveChallenge(verifier: string): Promise<string> {
  const encoded = new TextEncoder().encode(verifier)
  const digest = await crypto.subtle.digest('SHA-256', encoded)
  return base64urlEncode(digest)
}

/** Generate a random state parameter */
function generateState(): string {
  const randomBytes = new Uint8Array(16)
  crypto.getRandomValues(randomBytes)
  return base64urlEncode(randomBytes.buffer)
}

// ─── Public API ───────────────────────────────────────────────────────────────

/** Generates a PKCE code_verifier and the corresponding code_challenge */
export async function generatePkceChallenge(): Promise<{ verifier: string; challenge: string }> {
  const verifier = generateVerifier()
  const challenge = await deriveChallenge(verifier)
  return { verifier, challenge }
}

/**
 * Initiates the PKCE authorization code flow.
 * Saves verifier + state in sessionStorage, then redirects to the IDP.
 */
export async function startLoginFlow(): Promise<void> {
  const { verifier, challenge } = await generatePkceChallenge()
  const state = generateState()

  sessionStorage.setItem('pkce_verifier', verifier)
  sessionStorage.setItem('pkce_state', state)

  const params = new URLSearchParams({
    response_type: 'code',
    client_id: authConfig.clientId,
    redirect_uri: authConfig.redirectUri,
    scope: authConfig.scopes.join(' '),
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
  })

  window.location.href = `${authConfig.authorizationEndpoint}?${params.toString()}`
}

/**
 * Handles the authorization code callback.
 * Exchanges the code for tokens and returns the resulting TokenSet.
 */
export async function handleCallback(code: string, state: string): Promise<TokenSet> {
  const storedState = sessionStorage.getItem('pkce_state')
  const verifier = sessionStorage.getItem('pkce_verifier')

  if (!storedState || storedState !== state) {
    throw new Error('Invalid or mismatched PKCE state. Please try signing in again.')
  }

  if (!verifier) {
    throw new Error('PKCE code_verifier not found. Please try signing in again.')
  }

  // Clean up flow state immediately
  sessionStorage.removeItem('pkce_verifier')
  sessionStorage.removeItem('pkce_state')

  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: authConfig.clientId,
    redirect_uri: authConfig.redirectUri,
    code,
    code_verifier: verifier,
  })

  const response = await fetch(authConfig.tokenEndpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  })

  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`Token exchange failed: ${errorText}`)
  }

  const data = (await response.json()) as {
    access_token: string
    id_token?: string
    refresh_token?: string
    expires_in?: number
  }

  return {
    accessToken: data.access_token,
    idToken: data.id_token,
    refreshToken: data.refresh_token,
    expiresAt: Date.now() + (data.expires_in ?? 300) * 1000,
  }
}

/**
 * Uses the refresh_token to obtain a new access token without user interaction.
 */
export async function refreshToken(currentRefreshToken: string): Promise<TokenSet> {
  const body = new URLSearchParams({
    grant_type: 'refresh_token',
    client_id: authConfig.clientId,
    refresh_token: currentRefreshToken,
  })

  const response = await fetch(authConfig.tokenEndpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  })

  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`Token refresh failed: ${errorText}`)
  }

  const data = (await response.json()) as {
    access_token: string
    id_token?: string
    refresh_token?: string
    expires_in?: number
  }

  return {
    accessToken: data.access_token,
    idToken: data.id_token,
    refreshToken: data.refresh_token ?? currentRefreshToken,
    expiresAt: Date.now() + (data.expires_in ?? 300) * 1000,
  }
}

/**
 * Clears local auth data and performs an RP-initiated logout.
 *
 * Clearing sessionStorage alone is NOT enough: the IdP keeps its own SSO
 * session cookie, so the next "Sign in" silently re-authenticates without
 * prompting for credentials. We therefore redirect to the IdP's end-session
 * endpoint (with id_token_hint + post_logout_redirect_uri) so the IdP also
 * drops its session and the next login asks for credentials again.
 */
export function logout(): void {
  const idToken = sessionStorage.getItem('auth_id_token')

  sessionStorage.removeItem('auth_access_token')
  sessionStorage.removeItem('auth_id_token')
  sessionStorage.removeItem('auth_refresh_token')
  sessionStorage.removeItem('auth_expires_at')
  sessionStorage.removeItem('pkce_verifier')
  sessionStorage.removeItem('pkce_state')

  const postLogoutRedirectUri = `${window.location.origin}/login`

  // Dev-bypass mode has no IdP — just go back to the login screen locally.
  if (authConfig.mode === 'none' || !authConfig.endSessionEndpoint) {
    window.location.href = postLogoutRedirectUri
    return
  }

  const params = new URLSearchParams({
    post_logout_redirect_uri: postLogoutRedirectUri,
    client_id: authConfig.clientId,
  })
  if (idToken) params.set('id_token_hint', idToken)

  window.location.href = `${authConfig.endSessionEndpoint}?${params.toString()}`
}
