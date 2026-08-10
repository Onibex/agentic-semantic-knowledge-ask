import { NavLink, Outlet } from 'react-router-dom'
import { cn } from '@/lib/utils'
import {
  Home,
  Settings,
  Database,
  BrainCircuit,
  ShieldCheck,
  Plug,
  Server,
  FileCode,
  LogOut,
} from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { authConfig } from '@/auth/config'
import { useTranslation } from '@/hooks/useTranslation'
import { LanguageSelector } from '@/components/LanguageSelector'
import onibexLogo from '@/assets/Onibex_logo-azul2.png'

// Logged-in user + Sign-out. Hidden in dev-bypass ('none') mode. Mirrors
// ask-admin-spa / ask-chat-spa "User footer" (now the same light, token-driven shell).
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
          <LogOut size={14} />
        </button>
      </div>
    </div>
  )
}

export function Layout() {
  const { t } = useTranslation()

  const nav = [
    { to: '/',               label: t('nav_home'),           icon: Home,         end: true as const },
    { to: '/setup',          label: t('nav_setup'),          icon: Settings },
    { to: '/database',       label: t('nav_database'),       icon: Database },
    { to: '/llm-providers',  label: t('nav_llm_providers'),  icon: BrainCircuit },
    { to: '/identity',       label: t('nav_identity'),       icon: ShieldCheck },
    { to: '/sap-connection', label: t('nav_sap_connection'), icon: Plug },
    { to: '/mcp-server',     label: t('nav_mcp_server'),     icon: Server },
    { to: '/contracts',      label: t('nav_contracts'),      icon: FileCode },
  ]

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="w-56 shrink-0 bg-sidebar border-r border-sidebar-border flex flex-col h-screen">
        {/* Brand */}
        <div className="px-4 py-4 border-b border-sidebar-border">
          <img src={onibexLogo} alt="Onibex" className="w-36 h-auto object-contain" />
          <p className="text-[10px] text-muted-foreground mt-1.5 font-semibold tracking-widest uppercase">ASK Setup</p>
        </div>

        {/* Nav */}
        <nav className="flex-1 p-2 space-y-0.5 overflow-y-auto">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2.5 px-3 py-2 rounded-md text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-sidebar-active text-sidebar-active-foreground'
                    : 'text-sidebar-foreground hover:bg-muted hover:text-foreground',
                )
              }
            >
              <Icon size={15} className="shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Language selector */}
        <div className="shrink-0 border-t border-sidebar-border px-3 py-2">
          <LanguageSelector />
        </div>

        <UserFooter />
      </aside>

      <main className="flex-1 overflow-y-auto bg-content">
        <Outlet />
      </main>
    </div>
  )
}
