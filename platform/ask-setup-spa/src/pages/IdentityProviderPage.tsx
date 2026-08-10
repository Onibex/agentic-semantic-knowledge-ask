import {
  ShieldCheck,
  RefreshCw,
  Clock,
  AlertTriangle,
  Lock,
  Info,
} from 'lucide-react'
import { authConfig } from '@/auth/config'
import { useAuthStore } from '@/store/authStore'
import { useTranslation } from '@/hooks/useTranslation'

type Mode = 'keycloak' | 'xsuaa' | 'none'

const PROVIDER_META: Record<Mode, { label: string; color: string; bg: string }> = {
  keycloak: {
    label: 'Keycloak',
    color: '#2f6df6',
    bg: '#e8effc',
  },
  xsuaa: {
    label: 'SAP BTP — Cloud Identity (IAS / XSUAA)',
    color: '#0a6ed1',
    bg: '#e6f4fc',
  },
  none: {
    label: 'Dev bypass (no authentication)',
    color: '#64748b',
    bg: '#f1f5f9',
  },
}

function IdpMark({ mode, size = 22 }: { mode: Mode; size?: number }) {
  if (mode === 'xsuaa') {
    return (
      <svg width={size * 1.4} height={size * 0.65} viewBox="0 0 48 20" aria-hidden>
        <text
          x="24"
          y="15"
          textAnchor="middle"
          fontFamily="Arial, sans-serif"
          fontSize="15"
          fontWeight={800}
          letterSpacing="0.5"
          fill="currentColor"
        >
          SAP
        </text>
      </svg>
    )
  }
  if (mode === 'none') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
        <path d="M12 2 4 6v6c0 5 3.5 7.5 8 9 4.5-1.5 8-4 8-9V6l-8-4Z" />
        <path d="M9.5 12h5" />
      </svg>
    )
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M12 2a7 7 0 0 0-7 7v2.2A3 3 0 0 0 3 14v5a3 3 0 0 0 3 3h12a3 3 0 0 0 3-3v-5a3 3 0 0 0-2-2.8V9a7 7 0 0 0-7-7Zm-5 7a5 5 0 0 1 10 0v2H7V9Zm5 6.2a1.6 1.6 0 0 1 .8 3l.5 2.3h-2.6l.5-2.3a1.6 1.6 0 0 1 .8-3Z" />
    </svg>
  )
}

function alpha(hex: string): string {
  return hex + '26'
}

function realmFromIssuer(issuer: string): string | null {
  const m = issuer.match(/\/realms\/([^/]+)/)
  return m ? m[1] : null
}

function pathOf(url: string): string {
  try {
    return new URL(url).pathname
  } catch {
    return url
  }
}

function initials(email: string): string {
  const name = email.split('@')[0] ?? email
  const parts = name.split(/[.\-_]/).filter(Boolean)
  const chars = parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2)
  return chars.toUpperCase()
}

const KNOWN_ROLES = new Set(['ask-admin', 'ask-user'])

function ReadField({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  const { t } = useTranslation()
  return (
    <div>
      <dt className="text-[10.5px] font-semibold text-slate-500 uppercase tracking-wide mb-1">{label}</dt>
      <dd className={'text-sm text-slate-800 break-all' + (mono ? ' font-mono text-slate-700 text-[12.5px]' : '')}>
        {value || <span className="text-slate-400 italic">{t('common_not_set')}</span>}
      </dd>
    </div>
  )
}

export function IdentityProviderPage() {
  const { t } = useTranslation()
  const { user, isAuthenticated } = useAuthStore()
  const mode = authConfig.mode as Mode
  const meta = PROVIDER_META[mode] ?? PROVIDER_META.none
  const realm = mode === 'keycloak' ? realmFromIssuer(authConfig.issuerUrl) : null
  const configured = mode !== 'none'

  // Translated descriptions for each provider
  const providerDesc: Record<Mode, string> = {
    keycloak: t('idp_keycloak_desc'),
    xsuaa: t('idp_xsuaa_desc'),
    none: t('idp_none_desc'),
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="w-8 h-8 rounded-lg bg-blue-50 border border-blue-200 flex items-center justify-center">
              <ShieldCheck size={16} className="text-blue-600" />
            </div>
            <h1 className="text-lg font-semibold text-slate-900">{t('idp_title')}</h1>
          </div>
          <p className="text-sm text-slate-500 ml-10 max-w-xl">
            {t('idp_desc')}
          </p>
        </div>
        <button
          onClick={() => window.location.reload()}
          className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700 transition-colors py-1 px-2 rounded hover:bg-slate-100"
        >
          <RefreshCw size={13} />
          {t('common_refresh')}
        </button>
      </div>

      {/* Active provider */}
      <div className="relative bg-white rounded-xl border border-slate-200 shadow-sm px-4 py-3.5 overflow-hidden mb-4">
        <div className="absolute left-0 top-0 bottom-0 w-1" style={{ background: meta.color }} />
        <div className="flex items-center justify-between mb-2.5 pl-1.5">
          <span
            className="text-[11px] font-bold uppercase tracking-wider flex items-center gap-1.5"
            style={{ color: meta.color }}
          >
            <ShieldCheck size={12} />
            {t('idp_active_provider')}
            <span className="text-slate-400 font-semibold normal-case tracking-normal">
              {t('idp_authenticates_every')}
            </span>
          </span>
          <span className="text-[11px] font-semibold rounded-full px-2.5 py-0.5 bg-slate-100 text-slate-500 border border-slate-200">
            {configured ? t('idp_oidc_pkce') : t('idp_disabled')}
          </span>
        </div>
        <div className="flex items-center gap-3 pl-1.5">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
            style={{ backgroundColor: alpha(meta.color), color: meta.color }}
          >
            <IdpMark mode={mode} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-slate-800 truncate">{meta.label}</div>
            <div className="text-xs text-slate-500 font-mono truncate">
              {mode === 'keycloak' && `realm: ${realm ?? '?'} · client: ${authConfig.clientId}`}
              {mode === 'xsuaa' && `client: ${authConfig.clientId || '—'}`}
              {mode === 'none' && t('idp_no_provider_bound')}
            </div>
          </div>
          <span className="text-[11px] font-mono rounded px-1.5 py-0.5 bg-slate-100 text-slate-500 shrink-0">
            mode: {mode}
          </span>
        </div>
      </div>

      {/* OIDC configuration (read-only) */}
      {configured ? (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden mb-4">
          <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
              {t('idp_section_oidc')}
            </span>
            <span className="flex items-center gap-1.5 text-[11px] font-medium text-slate-400">
              <Lock size={11} />
              {t('idp_baked_at_build')}
            </span>
          </div>
          <div className="px-5 py-5">
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="sm:col-span-2">
                <ReadField label={t('idp_field_issuer')} value={authConfig.issuerUrl} mono />
              </div>
              <ReadField label={t('idp_field_client_id')} value={authConfig.clientId} mono />
              <ReadField label={t('idp_field_scopes')} value={authConfig.scopes.join(' · ')} />
              <ReadField label={t('idp_field_auth_endpoint')} value={pathOf(authConfig.authorizationEndpoint)} mono />
              <ReadField label={t('idp_field_token_endpoint')} value={pathOf(authConfig.tokenEndpoint)} mono />
              <ReadField label={t('idp_field_end_session')} value={pathOf(authConfig.endSessionEndpoint)} mono />
            </dl>
            <div className="mt-5 flex items-start gap-2.5 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-3 text-xs text-indigo-900 leading-relaxed">
              <Info size={14} className="mt-0.5 shrink-0 text-indigo-500" />
              <div>
                {t('idp_callout')}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-amber-200 shadow-sm px-5 py-4 mb-4 flex items-start gap-2.5 text-sm text-amber-800">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-500" />
          <div>
            {t('idp_dev_warning')}
          </div>
        </div>
      )}

      {/* Your session */}
      {configured && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden mb-6">
          <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">{t('idp_section_session')}</span>
            <span className="text-[11px] font-medium text-slate-400">{t('idp_decoded_from_token')}</span>
          </div>
          <div className="px-5 py-5">
            {isAuthenticated && user ? (
              <>
                <div className="flex items-center gap-3 mb-4">
                  <span className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold text-white shrink-0 bg-gradient-to-br from-indigo-600 to-violet-600">
                    {initials(user.email)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-slate-800 truncate">{user.email}</div>
                    <div className="text-xs text-slate-500 font-mono truncate">sub: {user.sub || '—'}</div>
                  </div>
                  <span className="text-[11px] font-semibold rounded-full px-2.5 py-0.5 bg-blue-50 text-blue-700 border border-blue-200 shrink-0">
                    {t('idp_signed_in')}
                  </span>
                </div>
                <dt className="text-[10.5px] font-semibold text-slate-500 uppercase tracking-wide mb-1.5">
                  {t('idp_roles_label')}
                </dt>
                {user.roles.length > 0 ? (
                  <div className="flex gap-1.5 flex-wrap">
                    {user.roles.map((r) => (
                      <span
                        key={r}
                        className={
                          'text-[11px] font-semibold rounded-full px-2.5 py-0.5 border ' +
                          (KNOWN_ROLES.has(r)
                            ? 'bg-blue-50 text-blue-700 border-blue-200'
                            : 'bg-slate-100 text-slate-500 border-slate-200')
                        }
                      >
                        {r}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="text-sm text-slate-400 italic">{t('idp_no_roles')}</span>
                )}
              </>
            ) : (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <Clock size={15} />
                {t('idp_no_session')}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Supported providers */}
      <div className="flex items-center justify-between mb-3 px-0.5">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">{t('idp_section_supported')}</h2>
        <span className="text-xs text-slate-400 font-semibold">{t('idp_supported_count')}</span>
      </div>
      <div className="space-y-2.5">
        {(['keycloak', 'xsuaa'] as const).map((m) => {
          const pm = PROVIDER_META[m]
          const active = mode === m
          return (
            <div
              key={m}
              className="bg-white rounded-xl border border-slate-200 shadow-sm px-4 py-3.5 flex items-center gap-4"
            >
              <div
                className="w-11 h-11 rounded-lg flex items-center justify-center shrink-0"
                style={{ backgroundColor: alpha(pm.color), color: pm.color }}
              >
                <IdpMark mode={m} size={24} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-semibold text-slate-900">{pm.label}</span>
                  <span className="text-[11px] font-mono text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">
                    {m}
                  </span>
                  {active ? (
                    <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-blue-50 text-blue-700 border border-blue-200">
                      {t('common_active')}
                    </span>
                  ) : (
                    <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-slate-100 text-slate-500 border border-slate-200">
                      {t('idp_badge_available')}
                    </span>
                  )}
                </div>
                <div className="text-xs text-slate-500 mt-1">{providerDesc[m]}</div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
