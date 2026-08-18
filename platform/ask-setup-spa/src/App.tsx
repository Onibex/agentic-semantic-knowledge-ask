/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'sonner'
import { Layout } from '@/components/Layout'
import { SapConnectionPage } from '@/pages/SapConnectionPage'
import { SetupPage } from '@/pages/SetupPage'
import { DatabasePage } from '@/pages/DatabasePage'
import { LlmProvidersPage } from '@/pages/LlmProvidersPage'
import { IdentityProviderPage } from '@/pages/IdentityProviderPage'
import { McpServerPage } from '@/pages/McpServerPage'
import { ContractsPage } from '@/pages/ContractsPage'
import { HomePage } from '@/pages/HomePage'
import LoginPage, { LoginCallback } from '@/pages/LoginPage'
import { ProtectedRoute } from '@/components/auth/ProtectedRoute'
import { useAuthStore } from '@/store/authStore'

function AuthInitializer() {
  const initAuth = useAuthStore((s) => s.initAuth)
  useEffect(() => {
    void initAuth()
    // run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return null
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthInitializer />
      <Toaster position="top-right" richColors />
      <Routes>
        {/* Standalone auth routes - no layout */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/login/callback" element={<LoginCallback />} />

        {/* App routes - gated behind Keycloak auth */}
        <Route
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route index element={<HomePage />} />
          <Route path="/setup" element={<SetupPage />} />
          <Route path="/database" element={<DatabasePage />} />
          <Route path="/llm-providers" element={<LlmProvidersPage />} />
          <Route path="/identity" element={<IdentityProviderPage />} />
          <Route path="/sap-connection" element={<SapConnectionPage />} />
          <Route path="/mcp-server" element={<McpServerPage />} />
          <Route path="/contracts" element={<ContractsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
