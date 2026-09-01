/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { Outlet, NavLink } from 'react-router-dom'
import {
  Activity,
  // BookMarked, // TODO(dictionary): restore with the Dictionary nav item (hidden 2026-06-17)
  BookOpen,
  Building2,
  Clock,
  LayoutGrid,
  Library,
  LogOut,
  Rocket,
  Settings2,
} from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { authConfig } from '@/auth/config'
import { useTranslation } from '@/hooks/useTranslation'
import { LanguageSelector } from '@/components/LanguageSelector'
import onibexLogo from '@/assets/Onibex_logo-azul2.png'

// ── Types ─────────────────────────────────────────────────────────────────────

interface NavItem {
  to: string
  label: string
  icon: React.ReactNode
  badge?: number
  end?: boolean
}

interface NavSection {
  title: string
  items: NavItem[]
}

// ── Nav item component ────────────────────────────────────────────────────────

function SideNavItem({ item }: { item: NavItem }) {
  return (
    <NavLink
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
      {item.badge != null && item.badge > 0 && (
        <span className="ml-auto min-w-[18px] h-[18px] text-[10px] font-bold bg-warning text-warning-foreground rounded-full flex items-center justify-center px-1 shrink-0">
          {item.badge}
        </span>
      )}
    </NavLink>
  )
}

// ── IDP chip ──────────────────────────────────────────────────────────────────

function IdpChip() {
  const label =
    authConfig.mode === 'keycloak'
      ? 'SSO'
      : authConfig.mode === 'xsuaa'
        ? 'XSUAA'
        : 'Dev'

  const colorClass =
    authConfig.mode === 'keycloak'
      ? 'bg-brand/10 text-brand'
      : authConfig.mode === 'xsuaa'
        ? 'bg-warning/15 text-warning'
        : 'bg-muted text-muted-foreground'

  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${colorClass}`}>
      {label}
    </span>
  )
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

function Sidebar() {
  const { user, logout } = useAuthStore()
  const { t } = useTranslation()

  // Nav layout: this SPA is dedicated to the semantic-layer curator, so Workspaces
  // and Organization are first-class. System configuration pages (SAP Connection,
  // MCP, Contracts) are not here — they live in the ASK Setup SPA.
  const sections: NavSection[] = [
    {
      title: t('section_help'),
      items: [
        {
          to: '/getting-started',
          label: t('nav_getting_started'),
          icon: <Rocket className="h-4 w-4" />,
        },
      ],
    },
    {
      title: t('section_semantic_layer'),
      items: [
        // "Graph" tab removed (design-spec §10#03 "no separate Graph tab"): the
        // graph now lives inside a domain (open a domain → its canvas). The
        // global GraphPage stays reachable at /graph as an internal fallback.
        // SAP-merge conflict resolution moved INTO Semantic Knowledge (the
        // "Conflicts" filter + per-row ⚠ badge): a conflict is an orthogonal
        // attribute of a catalog entity, not its own destination. The old
        // standalone "ASK Merge" page was retired — its ingest half lives in
        // New data product → From OneConnect, its resolver in the catalog.
        {
          to: '/semantic-knowledge',
          label: t('nav_semantic_knowledge'),
          icon: <Library className="h-4 w-4" />,
        },
        { to: '/history', label: t('nav_history'), icon: <Clock className="h-4 w-4" /> },
      ],
    },
    {
      title: t('section_organization'),
      items: [
        { to: '/workspaces', label: t('nav_workspaces'), icon: <LayoutGrid className="h-4 w-4" /> },
        { to: '/organization', label: t('nav_organization'), icon: <Building2 className="h-4 w-4" /> },
      ],
    },
    {
      title: t('section_curator'),
      items: [
        // TODO(dictionary): hidden until the needs_clarification clarify subnode lands
        // — see internal design doc (ITERATION_DICTIONARY_CLARIFY). Re-enable this
        // line + the BookMarked import above + the route in App.tsx.
        // { to: '/admin/dictionary', label: 'Dictionary', icon: <BookMarked className="h-4 w-4" /> },
        { to: '/admin/docs', label: t('nav_docs'), icon: <BookOpen className="h-4 w-4" /> },
        { to: '/admin/setup', label: t('nav_setup'), icon: <Settings2 className="h-4 w-4" /> },
      ],
    },
    {
      title: t('section_system'),
      items: [
        { to: '/health', label: t('nav_health'), icon: <Activity className="h-4 w-4" /> },
      ],
    },
  ]

  const displayEmail = user?.email ?? 'User'
  const primaryRole = user?.roles?.[0]

  return (
    <aside className="w-56 shrink-0 bg-sidebar border-r border-sidebar-border flex flex-col h-screen">
      {/* Brand */}
      <div className="flex items-center px-4 py-5 border-b border-sidebar-border">
        <img
          src={onibexLogo}
          alt="Onibex"
          className="w-40 h-auto object-contain"
        />
      </div>

      {/* Nav sections */}
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-4">
        {sections.map((section) => (
          <div key={section.title}>
            <p className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {section.title}
            </p>
            <div className="space-y-0.5">
              {section.items.map((item) => (
                <SideNavItem key={item.to} item={item} />
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* Language selector */}
      <div className="shrink-0 border-t border-sidebar-border px-3 py-2">
        <LanguageSelector />
      </div>

      {/* User footer */}
      <div className="shrink-0 border-t border-sidebar-border px-3 py-3 space-y-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <IdpChip />
          {primaryRole && (
            <span className="rounded-full bg-brand/10 px-2 py-0.5 text-[10px] font-semibold text-brand">
              {primaryRole}
            </span>
          )}
        </div>
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
    </aside>
  )
}

// ── Layout ────────────────────────────────────────────────────────────────────

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
