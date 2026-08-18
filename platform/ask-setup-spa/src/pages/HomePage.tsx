/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Settings,
  Database,
  BrainCircuit,
  ShieldCheck,
  Plug,
  Server,
  FileCode,
  CheckCircle2,
  AlertCircle,
  ChevronRight,
  RefreshCw,
  Loader2,
  Activity,
  BookOpen,
  ExternalLink,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { configApi, llmConnApi, dbApi, setupApi } from '@/api/client'
import { authConfig } from '@/auth/config'
import { useTranslation } from '@/hooks/useTranslation'
import type { AppConfig } from '@/api/types'

// ── helpers ────────────────────────────────────────────────

function isSapConfigured(c: AppConfig): boolean {
  const s4 = c.sap_s4hana as Record<string, unknown> | undefined
  return !!(s4?.host && s4?.username)
}

function isMcpConfigured(c: AppConfig): boolean {
  const s4 = c.sap_s4hana as Record<string, unknown> | undefined
  return !!(s4?.mcp_url)
}

function isLlmConfigured(c: AppConfig): boolean {
  return !!(c.model_name || (c.deployments as Record<string, unknown> | undefined)?.llm)
}

// ── types ──────────────────────────────────────────────────

interface CardDef {
  to: string
  icon: React.ElementType
  label: string
  description: string
  color: string
  bgColor: string
  borderColor: string
  check: (c: AppConfig) => boolean
  checkLabel?: { ok: string; missing: string }
}

// Card style + check logic (no translatable text — text injected in component via t())
const CARDS_CONFIG = [
  { to: '/setup',          icon: Settings,    check: () => false,       labelKey: 'card_setup_label',     descKey: 'card_setup_desc',     okKey: 'card_setup_ok',     missingKey: 'card_setup_missing' },
  { to: '/database',       icon: Database,    check: () => false,       labelKey: 'card_database_label',  descKey: 'card_database_desc',  okKey: 'card_database_ok',  missingKey: 'card_database_missing' },
  { to: '/llm-providers',  icon: BrainCircuit, check: isLlmConfigured,  labelKey: 'card_llm_label',       descKey: 'card_llm_desc',       okKey: 'card_llm_ok',       missingKey: 'card_llm_missing' },
  { to: '/identity',       icon: ShieldCheck, check: () => false,       labelKey: 'card_identity_label',  descKey: 'card_identity_desc',  okKey: 'card_identity_ok',  missingKey: 'card_identity_missing' },
  { to: '/sap-connection', icon: Plug,        check: isSapConfigured,   labelKey: 'card_sap_label',       descKey: 'card_sap_desc',       okKey: 'card_sap_ok',       missingKey: 'card_sap_missing' },
  { to: '/mcp-server',     icon: Server,      check: isMcpConfigured,   labelKey: 'card_mcp_label',       descKey: 'card_mcp_desc',       okKey: 'card_mcp_ok',       missingKey: 'card_mcp_missing' },
  { to: '/contracts',      icon: FileCode,    check: () => false,       labelKey: 'card_contracts_label', descKey: 'card_contracts_desc', okKey: 'card_contracts_ok', missingKey: 'card_contracts_missing' },
] as const

// ── main component ─────────────────────────────────────────

export function HomePage() {
  const { t } = useTranslation()
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [contractCount, setContractCount] = useState<number | null>(null)
  const [llmModel, setLlmModel] = useState<string | null>(null)
  const [llmStatus, setLlmStatus] = useState<{ ok: boolean; label: string }>({ ok: false, label: '' })
  const [dbStatus, setDbStatus] = useState<{ ok: boolean; label: string }>({ ok: false, label: '' })
  const [setupStatus, setSetupStatus] = useState<{ ok: boolean; label: string }>({ ok: false, label: '' })
  const [loading, setLoading] = useState(true)

  const CARDS: CardDef[] = CARDS_CONFIG.map((c) => ({
    ...c,
    color: 'text-brand',
    bgColor: 'bg-brand/10',
    borderColor: 'border-brand/20',
    label: t(c.labelKey as Parameters<typeof t>[0]),
    description: t(c.descKey as Parameters<typeof t>[0]),
    checkLabel: {
      ok: t(c.okKey as Parameters<typeof t>[0]),
      missing: t(c.missingKey as Parameters<typeof t>[0]),
    },
  }))

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    try {
      const [cfgRes, llmRes, dbRes, setupRes] = await Promise.allSettled([
        configApi.get(),
        llmConnApi.list(),
        dbApi.list(),
        setupApi.effective(),
      ])
      if (cfgRes.status === 'fulfilled') {
        setConfig(cfgRes.value.config)
        // contracts count from config
        const apis = (cfgRes.value.config as Record<string, unknown>).contracts
        if (Array.isArray(apis)) setContractCount(apis.length)
        else setContractCount(0)
      }
      if (llmRes.status === 'fulfilled') {
        const { connections, active } = llmRes.value
        const activeConn = connections.find((c) => c.id === active.active)
        setLlmModel(activeConn?.model ?? null)
        const n = connections.length
        setLlmStatus({
          ok: !!activeConn,
          label: activeConn
            ? t('home_status_conn_active').replace('{n}', String(n))
            : n > 0
              ? t('home_status_conn_none').replace('{n}', String(n))
              : t('card_llm_missing'),
        })
      }
      if (dbRes.status === 'fulfilled') {
        const { connections, active } = dbRes.value
        const hasActive = !!(active.dev || active.prod)
        const n = connections.length
        setDbStatus({
          ok: hasActive,
          label: hasActive
            ? t('home_status_conn_active').replace('{n}', String(n))
            : n > 0
              ? t('home_status_conn_none').replace('{n}', String(n))
              : t('card_database_missing'),
        })
      }
      if (setupRes.status === 'fulfilled') {
        const os = setupRes.value.sections.find((s) => s.id === 'opensearch')
        const host = os?.fields.find((f) => f.name === 'host')?.value
        setSetupStatus({
          ok: !!host,
          label: host ? t('home_status_opensearch').replace('{host}', host) : t('card_setup_missing'),
        })
      }
    } catch {
      // non-fatal: cards still render
    } finally {
      setLoading(false)
    }
  }

  // Derive per-card status
  function getStatus(card: CardDef): { ok: boolean; label: string } {
    if (!config) return { ok: false, label: card.checkLabel?.missing ?? 'Not set' }
    if (card.to === '/contracts') {
      const ok = (contractCount ?? 0) > 0
      return { ok, label: ok ? t('home_status_contracts').replace('{n}', String(contractCount)) : t('card_contracts_missing') }
    }
    if (card.to === '/setup') {
      return setupStatus
    }
    if (card.to === '/database') {
      return dbStatus
    }
    if (card.to === '/llm-providers') {
      return llmStatus
    }
    if (card.to === '/identity') {
      const active = authConfig.mode !== 'none'
      return {
        ok: active,
        label: active ? t('home_status_mode_active').replace('{mode}', authConfig.mode) : t('card_identity_missing'),
      }
    }
    const ok = card.check(config)
    return {
      ok,
      label: ok ? (card.checkLabel?.ok ?? 'Configured') : (card.checkLabel?.missing ?? 'Not configured'),
    }
  }

  const configuredCount = config
    ? CARDS.filter((c) => getStatus(c).ok).length
    : 0

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      {/* ── Hero ── */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-10 h-10 rounded-xl bg-brand flex items-center justify-center shrink-0">
            <Activity size={18} className="text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900 leading-tight">ASK Setup</h1>
            <p className="text-sm text-slate-500">{t('home_subtitle')}</p>
          </div>
          <button onClick={load} disabled={loading}
            className="ml-auto flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-600 transition-colors py-1 px-2 rounded hover:bg-slate-100">
            <RefreshCw size={12} className={cn(loading && 'animate-spin')} />
            {t('home_refresh')}
          </button>
        </div>

        {/* Progress bar */}
        {loading ? (
          <div className="flex items-center gap-2 text-xs text-slate-400 mt-4">
            <Loader2 size={12} className="animate-spin" />
            {t('home_loading')}
          </div>
        ) : (
          <div className="mt-4 bg-white rounded-xl border border-slate-200 shadow-sm px-5 py-4 flex items-center gap-4">
            <div className="flex-1">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-medium text-slate-600">{t('home_progress_label')}</span>
                <span className="text-xs font-semibold text-slate-800">{configuredCount} / {CARDS.length}</span>
              </div>
              <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden">
                <div
                  className="h-full rounded-full bg-brand transition-all duration-500"
                  style={{ width: `${(configuredCount / CARDS.length) * 100}%` }}
                />
              </div>
            </div>
            {configuredCount === CARDS.length && (
              <div className="flex items-center gap-1.5 text-xs font-medium text-emerald-600 bg-emerald-50 border border-emerald-200 rounded-full px-3 py-1 shrink-0">
                <CheckCircle2 size={12} />
                {t('home_all_configured')}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Cards grid ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {CARDS.map((card) => {
          const { ok, label } = getStatus(card)
          const Icon = card.icon
          return (
            <Link key={card.to} to={card.to}
              className="group bg-white rounded-xl border border-slate-200 shadow-sm hover:shadow-md hover:border-slate-300 transition-all duration-150 flex flex-col overflow-hidden">
              {/* Card header */}
              <div className="flex items-center gap-3 px-5 pt-5 pb-3">
                <div className={cn('w-9 h-9 rounded-lg border flex items-center justify-center shrink-0', card.bgColor, card.borderColor)}>
                  <Icon size={16} className={card.color} />
                </div>
                <span className="text-sm font-semibold text-slate-900">{card.label}</span>
                <ChevronRight size={14} className="ml-auto text-slate-300 group-hover:text-slate-500 transition-colors" />
              </div>

              {/* Description */}
              <p className="px-5 pb-4 text-xs text-slate-500 leading-relaxed flex-1">
                {card.description}
              </p>

              {/* Status strip */}
              <div className={cn(
                'flex items-center gap-1.5 px-5 py-2.5 border-t text-xs font-medium',
                ok
                  ? 'border-emerald-100 bg-emerald-50 text-emerald-700'
                  : 'border-slate-100 bg-slate-50 text-slate-400'
              )}>
                {loading ? (
                  <Loader2 size={11} className="animate-spin text-slate-300" />
                ) : ok ? (
                  <CheckCircle2 size={11} />
                ) : (
                  <AlertCircle size={11} />
                )}
                {loading ? t('home_loading_card') : label}
              </div>
            </Link>
          )
        })}
      </div>

      {/* ── Info footer ── */}
      <div className="mt-6 rounded-xl border border-slate-200 bg-white shadow-sm px-5 py-4">
        <h2 className="text-xs font-semibold text-slate-700 uppercase tracking-wider mb-3">
          {t('home_how_it_works')}
        </h2>
        <div className="space-y-2">
          {[t('how_step1'), t('how_step2'), t('how_step3'), t('how_step4'), t('how_step5')].map((text, i) => (
            <div key={i} className="flex items-start gap-3">
              <span className="w-5 h-5 rounded-full bg-slate-100 text-[10px] font-bold text-slate-500 flex items-center justify-center shrink-0 mt-px">
                {i + 1}
              </span>
              <p className="text-xs text-slate-500 leading-relaxed">{text}</p>
            </div>
          ))}
        </div>
        <a
          href="https://github.com/Onibex/agentic-semantic-knowledge-ask/tree/main/platform/ask-setup"
          target="_blank"
          rel="noreferrer"
          className="mt-3 pt-3 border-t border-slate-100 flex items-center gap-1.5 text-xs font-medium text-blue-600 hover:text-blue-700"
        >
          <BookOpen size={13} />
          {t('home_full_guide')}
          <ExternalLink size={11} className="opacity-60" />
        </a>
      </div>

      {/* LLM model badge */}
      {llmModel && (
        <p className="mt-4 text-center text-xs text-slate-400">
          {t('home_active_model')} <span className="font-mono font-medium text-slate-600">{llmModel}</span>
        </p>
      )}
    </div>
  )
}
