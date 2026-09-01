/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useLocation } from 'react-router-dom'
import { Clock } from 'lucide-react'

const labels: Record<string, string> = {
  '/':               'Home',
  '/setup':          'Setup',
  '/database':       'Database',
  '/llm-providers':  'LLM Providers',
  '/knowledge':      'Knowledge',
  '/mcp-server':     'MCP Server',
  '/semantic-admin': 'Semantic Admin',
  '/access-control': 'Access Control',
  '/contracts':      'Contracts',
}

export function ComingSoonPage() {
  const { pathname } = useLocation()
  const name = labels[pathname] ?? 'This section'

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center px-6">
      <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center mb-4">
        <Clock size={22} className="text-slate-400" />
      </div>
      <h2 className="text-base font-semibold text-slate-700 mb-1">{name}</h2>
      <p className="text-sm text-slate-400 max-w-xs">
        This page is under development and will be available in a future release.
      </p>
    </div>
  )
}
