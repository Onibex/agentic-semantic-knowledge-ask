/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { Loader2, ShieldOff } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'

const CHAT_URL = import.meta.env.VITE_CHAT_URL as string | undefined

interface Props {
  requiredRole?: string
  children: ReactNode
}

export function ProtectedRoute({ requiredRole, children }: Props) {
  const { isLoading, isAuthenticated, user } = useAuthStore()

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  if (requiredRole && !user?.roles.includes(requiredRole)) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-8 w-full max-w-md text-center space-y-4">
          <div className="flex justify-center text-amber-400">
            <ShieldOff className="h-12 w-12" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Access restricted</h2>
            <p className="text-sm text-gray-500 mt-1">
              This section requires the{' '}
              <code className="text-xs font-mono bg-gray-100 px-1 py-0.5 rounded">
                {requiredRole}
              </code>{' '}
              role. Your account ({user?.email ?? 'unknown'}) has:{' '}
              <code className="text-xs font-mono bg-gray-100 px-1 py-0.5 rounded">
                {user?.roles.join(', ') || 'no roles'}
              </code>
              .
            </p>
          </div>
          {CHAT_URL && (
            <a
              href={CHAT_URL}
              className="inline-block text-sm text-blue-600 hover:text-blue-700 font-medium underline underline-offset-2"
            >
              Go to the Chat application →
            </a>
          )}
          <p className="text-xs text-gray-400">
            Contact your administrator to request access.
          </p>
        </div>
      </div>
    )
  }

  return <>{children}</>
}
