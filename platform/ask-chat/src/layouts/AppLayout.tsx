/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { Outlet, NavLink } from 'react-router-dom'
import { MessageSquare, FileText, Home, ChevronDown, LogOut } from 'lucide-react'
import onibexLogo from '@/assets/Onibex_logo-azul2.png'
import { useQuery } from '@tanstack/react-query'
import { listWorkspaces } from '@/api/admin'
import { useChatStore } from '@/store/chatStore'
import { useAuthStore } from '@/store/authStore'
import { authConfig } from '@/auth/config'
import { useTranslation } from '@/hooks/useTranslation'
import { LanguageSelector } from '@/components/LanguageSelector'
import type { Mode, Env } from '@/api/orchestrator'

// Logged-in user + Sign-out. Hidden in dev-bypass ('none') mode where there is
// no real principal. Mirrors ask-studio's AppLayout "User footer".
function UserFooter() {
  const { user, logout } = useAuthStore()
  const { t } = useTranslation()
  if (authConfig.mode === 'none') return null
  const displayEmail = user?.email ?? 'User'
  const primaryRole = user?.roles?.[0]
  return (
    <div className="shrink-0 border-t border-sidebar-border px-3 py-3 space-y-2">
      {primaryRole && (
        <span className="rounded-full bg-brand/10 px-2 py-0.5 text-[10px] font-semibold text-brand">
          {primaryRole}
        </span>
      )}
      <div className="flex items-center gap-2">
        <span className="flex-1 text-xs text-muted-foreground truncate min-w-0">{displayEmail}</span>
        <button
          onClick={logout}
          title={t('sign_out')}
          className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
        >
          <LogOut className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}

const MODE_OPTIONS: { value: Mode; label: string }[] = [
  { value: 'flash', label: 'Flash' },
  { value: 'precise', label: 'Precise' },
  { value: 'smart', label: 'Smart' },
]

function Sidebar() {
  const { workspaceId, env, mode, setWorkspaceId, setEnv, setMode } = useChatStore()
  const { t } = useTranslation()

  const { data: workspaces = [] } = useQuery({
    queryKey: ['workspaces'],
    queryFn: listWorkspaces,
    staleTime: 1000 * 60 * 5,
  })

  const navItems = [
    { to: '/', label: t('nav_home'), icon: <Home className="h-4 w-4" />, end: true },
    { to: '/chat', label: t('nav_chat'), icon: <MessageSquare className="h-4 w-4" /> },
    { to: '/artifacts', label: t('nav_artifacts'), icon: <FileText className="h-4 w-4" /> },
  ]

  return (
    <aside className="w-56 shrink-0 bg-sidebar border-r border-sidebar-border flex flex-col h-screen">
      {/* Brand */}
      <div className="flex flex-col px-4 py-4 border-b border-sidebar-border gap-0.5">
        <img src={onibexLogo} alt="Onibex" className="w-36 h-auto object-contain" />
        <span className="text-[11px] font-medium text-muted-foreground tracking-wide pl-0.5">ASK Chat</span>
      </div>

      {/* Navigation */}
      <nav className="py-3 px-2 space-y-0.5 border-b border-sidebar-border">
        <p className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {t('section_navigation')}
        </p>
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `relative flex items-center gap-2.5 px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                isActive
                  ? 'bg-sidebar-active text-sidebar-active-foreground'
                  : 'text-sidebar-foreground hover:text-foreground hover:bg-muted'
              }`
            }
          >
            <span className="shrink-0">{item.icon}</span>
            <span className="truncate">{item.label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Settings */}
      <div className="flex-1 py-3 px-2 space-y-4 overflow-y-auto">
        {/* Workspace */}
        <div>
          <p className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {t('section_workspace')}
          </p>
          <div className="relative px-1">
            <select
              value={workspaceId}
              onChange={(e) => setWorkspaceId(e.target.value)}
              className="w-full appearance-none rounded-md border border-input bg-background px-3 py-1.5 pr-8 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            >
              <option value="">{t('select_workspace')}</option>
              {workspaces.map((ws) => (
                <option key={ws.slug} value={ws.slug}>
                  {ws.name}
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-2 h-4 w-4 text-muted-foreground" />
          </div>
        </div>

        {/* Environment */}
        <div>
          <p className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {t('section_environment')}
          </p>
          <div className="flex gap-1 px-1">
            {(['dev', 'prod'] as Env[]).map((e) => (
              <button
                key={e}
                onClick={() => setEnv(e)}
                className={`flex-1 rounded-md px-2 py-1.5 text-xs font-medium transition-colors capitalize ${
                  env === e
                    ? 'bg-sidebar-active text-sidebar-active-foreground border border-brand/30'
                    : 'text-sidebar-foreground hover:bg-muted border border-transparent'
                }`}
              >
                {e}
              </button>
            ))}
          </div>
        </div>

        {/* SQL Mode */}
        <div>
          <p className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {t('section_mode')}
          </p>
          <div className="flex flex-col gap-0.5 px-1">
            {MODE_OPTIONS.map((m) => (
              <button
                key={m.value}
                onClick={() => setMode(m.value)}
                className={`text-left rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  mode === m.value
                    ? 'bg-sidebar-active text-sidebar-active-foreground'
                    : 'text-sidebar-foreground hover:bg-muted'
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Language selector */}
      <div className="shrink-0 border-t border-sidebar-border px-3 py-2">
        <LanguageSelector />
      </div>

      <UserFooter />
    </aside>
  )
}

export default function AppLayout() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-auto bg-content">
        <Outlet />
      </main>
    </div>
  )
}
