/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { create } from 'zustand'
import { authConfig } from '../auth/config'
import { handleCallback as pkceHandleCallback, logout as pkceLogout, refreshToken as pkceRefreshToken } from '../auth/pkceFlow'

// ─── Types ────────────────────────────────────────────────────────────────────

interface AuthUser {
  sub: string
  email: string
  roles: string[]
  issuer: string
}

interface AuthState {
  accessToken: string | null
  user: AuthUser | null
  isAuthenticated: boolean
  isLoading: boolean

  initAuth(): Promise<void>
  handleCallback(): Promise<void>
  /** Silently refresh the access token from the stored refresh token. Returns true on success. */
  refreshSession(): Promise<boolean>
  /** Clear local auth state + sessionStorage WITHOUT an IdP redirect (used on dead-session 401s). */
  clearSession(): void
  logout(): void
  getAuthHeader(): { Authorization: string } | Record<string, never>
}

// ─── JWT helpers ──────────────────────────────────────────────────────────────

/** Decode a JWT payload WITHOUT verifying the signature (server-side validates). */
function decodeJwtPayload(token: string): Record<string, unknown> {
  try {
    const parts = token.split('.')
    if (parts.length < 2) return {}
    // Add padding back so atob works
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64 + '=='.slice(0, (4 - (base64.length % 4)) % 4)
    const json = atob(padded)
    return JSON.parse(json) as Record<string, unknown>
  } catch {
    return {}
  }
}

function extractUser(token: string): AuthUser | null {
  try {
    const payload = decodeJwtPayload(token)
    const sub = (payload['sub'] as string | undefined) ?? ''
    const email =
      (payload['email'] as string | undefined) ??
      (payload['preferred_username'] as string | undefined) ??
      sub

    // Keycloak puts roles in realm_access.roles; XSUAA puts them in scope or xs.saml.attributes
    let roles: string[] = []
    const realmAccess = payload['realm_access'] as { roles?: string[] } | undefined
    if (realmAccess?.roles) {
      roles = realmAccess.roles
    } else if (Array.isArray(payload['roles'])) {
      roles = payload['roles'] as string[]
    } else if (typeof payload['scope'] === 'string') {
      roles = (payload['scope'] as string).split(' ')
    }

    const issuer = (payload['iss'] as string | undefined) ?? authConfig.issuerUrl

    return { sub, email, roles, issuer }
  } catch {
    return null
  }
}

/** Returns true if the token expires more than 30 s in the future */
function isTokenValid(expiresAt: number): boolean {
  return expiresAt > Date.now() + 30_000
}

// ─── SessionStorage keys ──────────────────────────────────────────────────────

const KEYS = {
  accessToken: 'auth_access_token',
  idToken: 'auth_id_token',
  refreshToken: 'auth_refresh_token',
  expiresAt: 'auth_expires_at',
} as const

// ─── Store ────────────────────────────────────────────────────────────────────

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  user: null,
  isAuthenticated: false,
  isLoading: true, // stays true until initAuth() completes — prevents ProtectedRoute from redirecting before session is restored

  async initAuth() {
    set({ isLoading: true })

    try {
      // 1. Try to restore existing session from sessionStorage
      // NOTE: callback exchange (?code=&state=) is handled exclusively by
      // LoginCallback — initAuth must NOT consume the code, otherwise
      // LoginCallback gets a null pkce_state on its own handleCallback call.
      const storedToken = sessionStorage.getItem(KEYS.accessToken)
      const storedExpiresAt = sessionStorage.getItem(KEYS.expiresAt)

      if (storedToken && storedExpiresAt) {
        const expiresAt = parseInt(storedExpiresAt, 10)

        if (isTokenValid(expiresAt)) {
          const user = extractUser(storedToken)
          set({
            accessToken: storedToken,
            user,
            isAuthenticated: true,
            isLoading: false,
          })
          return
        }

        // Token expired — attempt a silent refresh (shared with the 401 path).
        if (await get().refreshSession()) return
        // Refresh failed/absent — drop the dead session and continue.
        get().clearSession()
      }

      // 3. In 'none' mode, mark as authenticated with a mock admin user (dev bypass)
      if (authConfig.mode === 'none') {
        set({
          isAuthenticated: true,
          isLoading: false,
          user: { sub: 'dev', email: 'dev@local', roles: ['ask-admin', 'ask-user'], issuer: 'dev' },
        })
        return
      }

      // 4. No valid session
      set({ isAuthenticated: false, isLoading: false })
    } catch {
      set({ isAuthenticated: false, isLoading: false })
    }
  },

  async handleCallback() {
    set({ isLoading: true })

    try {
      const url = new URL(window.location.href)
      const code = url.searchParams.get('code')
      const state = url.searchParams.get('state')
      const errorParam = url.searchParams.get('error')

      if (errorParam) {
        const description = url.searchParams.get('error_description') ?? errorParam
        throw new Error(description)
      }

      if (!code || !state) {
        throw new Error('Missing callback parameters (code or state).')
      }

      const tokenSet = await pkceHandleCallback(code, state)

      // Persist to sessionStorage
      sessionStorage.setItem(KEYS.accessToken, tokenSet.accessToken)
      sessionStorage.setItem(KEYS.expiresAt, String(tokenSet.expiresAt))
      if (tokenSet.idToken) {
        sessionStorage.setItem(KEYS.idToken, tokenSet.idToken)
      }
      if (tokenSet.refreshToken) {
        sessionStorage.setItem(KEYS.refreshToken, tokenSet.refreshToken)
      }

      const user = extractUser(tokenSet.accessToken)

      // Clean URL without triggering a page reload
      window.history.replaceState({}, document.title, window.location.pathname)

      set({
        accessToken: tokenSet.accessToken,
        user,
        isAuthenticated: true,
        isLoading: false,
      })
    } catch (err) {
      set({ isAuthenticated: false, isLoading: false })
      throw err // re-throw so LoginCallback can surface the error
    }
  },

  async refreshSession() {
    const storedRefresh = sessionStorage.getItem(KEYS.refreshToken)
    if (!storedRefresh) return false
    try {
      const tokenSet = await pkceRefreshToken(storedRefresh)
      sessionStorage.setItem(KEYS.accessToken, tokenSet.accessToken)
      sessionStorage.setItem(KEYS.expiresAt, String(tokenSet.expiresAt))
      if (tokenSet.idToken) {
        sessionStorage.setItem(KEYS.idToken, tokenSet.idToken)
      }
      if (tokenSet.refreshToken) {
        sessionStorage.setItem(KEYS.refreshToken, tokenSet.refreshToken)
      }
      const user = extractUser(tokenSet.accessToken)
      set({
        accessToken: tokenSet.accessToken,
        user,
        isAuthenticated: true,
        isLoading: false,
      })
      return true
    } catch {
      return false
    }
  },

  clearSession() {
    sessionStorage.removeItem(KEYS.accessToken)
    sessionStorage.removeItem(KEYS.idToken)
    sessionStorage.removeItem(KEYS.refreshToken)
    sessionStorage.removeItem(KEYS.expiresAt)
    set({
      accessToken: null,
      user: null,
      isAuthenticated: false,
      isLoading: false,
    })
  },

  logout() {
    set({
      accessToken: null,
      user: null,
      isAuthenticated: false,
      isLoading: false,
    })
    pkceLogout()
  },

  getAuthHeader() {
    const { accessToken } = get()
    if (!accessToken) return {} as Record<string, never>
    return { Authorization: `Bearer ${accessToken}` }
  },
}))
