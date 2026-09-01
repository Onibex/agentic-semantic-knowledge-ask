/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { authConfig } from '@/auth/config'
import { startLoginFlow } from '@/auth/pkceFlow'
import { useAuthStore } from '@/store/authStore'
import onibexLogo from '@/assets/Onibex_logo-azul2.png'

// ─── Shared login design line (kept identical across ask-studio/chat/setup SPAs;
// only APP_ROLE differs). Until the `@ask/spa-auth` package lands (BACKLOG M),
// this block is duplicated verbatim in each SPA's LoginPage.tsx. ──────────────
const APP_ROLE = 'ASK Chat'

const PAGE_BG =
  'min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0A1535] via-[#0D1B4B] to-[#1A2E6B] p-4'
const PRIMARY_BTN =
  'w-full rounded-md bg-blue-600 text-white text-sm font-medium py-2.5 hover:bg-blue-700 disabled:opacity-50 inline-flex items-center justify-center transition-colors'

// ─── LoginCallback — handles /login/callback after the IdP redirects back ──────
export function LoginCallback() {
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const handleCallback = useAuthStore((s) => s.handleCallback)

  useEffect(() => {
    let cancelled = false
    handleCallback()
      .then(() => {
        if (!cancelled) navigate('/', { replace: true })
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
    // run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className={PAGE_BG}>
      {error ? (
        <div className="bg-white rounded-lg border border-gray-200 shadow-xl p-8 w-full max-w-sm text-center">
          <div className="mb-4 text-red-600">
            <svg className="mx-auto h-12 w-12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.072 16.5c-.77.833.193 2.5 1.732 2.5z"
              />
            </svg>
          </div>
          <h2 className="text-lg font-semibold text-gray-900 mb-2">Authentication error</h2>
          <p className="text-sm text-gray-500 mb-6">{error}</p>
          <button className={PRIMARY_BTN} onClick={() => (window.location.href = '/login')}>
            Try again
          </button>
        </div>
      ) : (
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin text-blue-300 mx-auto mb-4" />
          <p className="text-sm text-blue-100">Processing sign-in…</p>
        </div>
      )}
    </div>
  )
}

// ─── LoginPage ─────────────────────────────────────────────────────────────────
export default function LoginPage() {
  const [busy, setBusy] = useState(false)
  const initAuth = useAuthStore((s) => s.initAuth)
  const navigate = useNavigate()

  async function handleNoAuth() {
    setBusy(true)
    await initAuth()
    navigate('/', { replace: true })
  }

  async function handleLogin() {
    setBusy(true)
    try {
      await startLoginFlow() // redirects the browser
    } catch {
      setBusy(false)
    }
  }

  const noAuth = authConfig.mode === 'none'

  return (
    <div className={PAGE_BG}>
      <div className="bg-white rounded-lg border border-gray-200 shadow-xl p-8 w-full max-w-sm text-center">
        <img src={onibexLogo} alt="Onibex" className="mx-auto mb-4 h-12 w-auto object-contain" />
        <h1 className="text-lg font-semibold text-gray-900">Agentic Semantic Knowledge</h1>
        <p className="text-sm text-gray-500 mb-6">{APP_ROLE}</p>
        <button className={PRIMARY_BTN} onClick={noAuth ? handleNoAuth : handleLogin} disabled={busy}>
          {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {noAuth
            ? busy
              ? 'Signing in…'
              : 'Continue without authentication'
            : busy
              ? 'Redirecting…'
              : 'Sign in'}
        </button>
      </div>
    </div>
  )
}
