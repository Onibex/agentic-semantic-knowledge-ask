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
import AppLayout from './layouts/AppLayout'
import { GraphPage } from './pages/GraphPage'
import { HistoryPage } from './pages/HistoryPage'
import { HealthPage } from './pages/HealthPage'
import LoginPage, { LoginCallback } from './pages/LoginPage'
// TODO(dictionary): hidden — see internal design doc (ITERATION_DICTIONARY_CLARIFY)
// import DictionaryPage from './pages/admin/DictionaryPage'
import DocsPage from './pages/admin/DocsPage'
import SetupPage from './pages/admin/SetupPage'
// Not routed here — system configuration (SAP connection, MCP server, OpenAPI
// contracts) lives in the ASK Setup SPA. The pages stay on disk; to surface them
// here again, re-add the imports + routes.
// Iter 1 — new pages
import WorkspaceHome from './pages/WorkspaceHome'
// Onboarding — in-product Getting Started launchpad
import GettingStartedPage from './pages/GettingStartedPage'
// Domain Canvas (design-spec §03) — the per-Business-Domain graph
import DomainCanvasPage from './pages/DomainCanvasPage'
import OrganizationPage from './pages/OrganizationPage'
// UX_CHANGES audit (Iter 1) — global DataProduct catalog
import SemanticKnowledgePage from './pages/SemanticKnowledgePage'
// Not routed here — system configuration (SAP connection, MCP server, OpenAPI
// contracts) lives in the ASK Setup SPA. The pages stay on disk; to surface them
// here again, re-add the imports + routes.
import { ProtectedRoute } from './components/auth/ProtectedRoute'
import { useAuthStore } from './store/authStore'

function AuthInitializer() {
  const initAuth = useAuthStore((s) => s.initAuth)

  useEffect(() => {
    void initAuth()
    // Run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return null
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthInitializer />
      <Toaster position="bottom-right" richColors closeButton />
      <Routes>
        {/* Standalone auth routes — no layout */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/login/callback" element={<LoginCallback />} />

        {/* All app routes — require ask-admin role. ask-user sees the access denied screen. */}
        <Route
          element={
            <ProtectedRoute requiredRole="ask-admin">
              <AppLayout />
            </ProtectedRoute>
          }
        >
          {/* Semantic Layer — the domain canvas IS the graph (design-spec §10#03):
              the landing redirects to Workspaces; the global GraphPage stays at
              /graph as an internal fallback only (no longer in the sidebar). */}
          <Route index element={<Navigate to="/workspaces" replace />} />
          <Route path="/getting-started" element={<GettingStartedPage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/health" element={<HealthPage />} />

          {/* Workspaces + Business Domains + Organization — unified rail+cards home */}
          <Route path="/workspaces" element={<WorkspaceHome />} />
          <Route path="/workspaces/:slug" element={<WorkspaceHome />} />
          {/* Domain Canvas (design-spec §03) — open a domain → its scoped graph */}
          <Route path="/workspaces/:slug/domains/:bdSlug" element={<DomainCanvasPage />} />
          <Route path="/organization" element={<OrganizationPage />} />
          {/* UX_CHANGES audit (Iter 1) — global DataProduct catalog */}
          <Route path="/semantic-knowledge" element={<SemanticKnowledgePage />} />

          {/* Curator workflow */}
          {/* TODO(dictionary): hidden — restore with the import above + the AppLayout nav item */}
          {/* <Route path="/admin/dictionary" element={<DictionaryPage />} /> */}
          <Route path="/admin/docs" element={<DocsPage />} />
          <Route path="/admin/setup" element={<SetupPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
