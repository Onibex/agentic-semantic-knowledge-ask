/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useQuery } from '@tanstack/react-query'
import { getHealth } from '@/api/orchestrator'
import { listWorkspaces } from '@/api/admin'
import { useChatStore } from '@/store/chatStore'
import {
  MessageSquare, FileText, ChevronRight,
  Database, Zap, Target, Brain,
  Globe, Building2, BarChart3, Layers, GitBranch,
  CheckCircle2, XCircle, Loader2, Sparkles,
  BookOpen, ExternalLink,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { OnibexLogo } from '@/components/OnibexLogo'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/hooks/useTranslation'

// ── Mode icon/chip config (non-translatable) ──────────────────────────────────

const MODE_CHIP = {
  flash:   { Icon: Zap,    chip: 'bg-amber-50 text-amber-700 ring-amber-200' },
  precise: { Icon: Target, chip: 'bg-blue-50 text-blue-700 ring-blue-200' },
  smart:   { Icon: Brain,  chip: 'bg-violet-50 text-violet-700 ring-violet-200' },
} as const

// ── Capability icon map (non-translatable) ────────────────────────────────────

const CAP_ICONS = [Database, GitBranch, Layers, Globe, Building2, BarChart3, Sparkles]

// ── Feature card style config (non-translatable) ─────────────────────────────

const FEATURE_STYLE = [
  {
    to: '/chat' as const,
    Icon: MessageSquare,
    iconBg: 'bg-blue-600',
    tagClass: 'bg-blue-50 text-blue-600',
    hoverBorder: 'hover:border-blue-200',
    hoverGrad: 'group-hover:from-blue-50/60 group-hover:to-blue-100/30',
    hoverTitle: 'group-hover:text-blue-700',
    hoverArrow: 'group-hover:text-blue-500',
  },
  {
    to: '/artifacts' as const,
    Icon: FileText,
    iconBg: 'bg-indigo-600',
    tagClass: 'bg-indigo-50 text-indigo-600',
    hoverBorder: 'hover:border-indigo-200',
    hoverGrad: 'group-hover:from-indigo-50/60 group-hover:to-violet-100/30',
    hoverTitle: 'group-hover:text-indigo-700',
    hoverArrow: 'group-hover:text-indigo-500',
  },
]

// ── Page ──────────────────────────────────────────────────────────────────────

export default function HomePage() {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { workspaceId, env, mode, workspaceChats } = useChatStore()

  const { data: health, isLoading: healthLoading, isError: healthError } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    retry: 1,
  })

  const { data: workspaces = [] } = useQuery({
    queryKey: ['workspaces'],
    queryFn: listWorkspaces,
    staleTime: 1000 * 60 * 5,
  })

  const currentWorkspace = workspaces.find((ws) => ws.slug === workspaceId)
  const totalChats = Object.values(workspaceChats).reduce((sum, c) => sum + c.length, 0)

  const MODE_META = {
    flash:   { ...MODE_CHIP.flash,   label: t('mode_flash_label'),   desc: t('mode_flash_desc') },
    precise: { ...MODE_CHIP.precise, label: t('mode_precise_label'), desc: t('mode_precise_desc') },
    smart:   { ...MODE_CHIP.smart,   label: t('mode_smart_label'),   desc: t('mode_smart_desc') },
  }
  const modeMeta = MODE_META[mode]

  const CAPABILITIES = [
    { label: t('cap_text_to_sql'),      Icon: CAP_ICONS[0] },
    { label: t('cap_knowledge_graph'),  Icon: CAP_ICONS[1] },
    { label: t('cap_semantic_layer'),   Icon: CAP_ICONS[2] },
    { label: t('cap_hybrid_search'),    Icon: CAP_ICONS[3] },
    { label: t('cap_sap_native'),       Icon: CAP_ICONS[4] },
    { label: t('cap_auto_charts'),      Icon: CAP_ICONS[5] },
    { label: t('cap_ai_reports'),       Icon: CAP_ICONS[6] },
  ]

  const FEATURES = [
    {
      ...FEATURE_STYLE[0],
      title: t('feature_chat_title'),
      description: t('feature_chat_desc'),
      tags: [t('feature_chat_tag1'), t('feature_chat_tag2'), t('feature_chat_tag3')],
    },
    {
      ...FEATURE_STYLE[1],
      title: t('feature_artifacts_title'),
      description: t('feature_artifacts_desc'),
      tags: [t('feature_artifacts_tag1'), t('feature_artifacts_tag2'), t('feature_artifacts_tag3')],
    },
  ]

  return (
    <div className="p-6 md:p-8 max-w-4xl mx-auto space-y-5">

      {/* ── Hero ───────────────────────────────────────────────────────── */}
      <div className="relative overflow-hidden rounded-2xl bg-[#0D2B6E] px-8 py-7 text-white shadow-lg">
        {/* Decorative blobs */}
        <div className="pointer-events-none absolute -right-20 -top-20 h-72 w-72 rounded-full bg-blue-500/10" />
        <div className="pointer-events-none absolute right-16 -bottom-16 h-52 w-52 rounded-full bg-indigo-400/10" />

        <div className="relative flex items-center justify-between gap-6 flex-wrap">
          {/* Brand */}
          <div className="flex items-center gap-5">
            <OnibexLogo className="h-16 w-16 shrink-0" />
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-blue-300 mb-0.5">
                Onibex
              </p>
              <h1 className="text-2xl font-bold leading-tight">ASK Chat</h1>
              <p className="mt-1.5 text-sm text-blue-200 max-w-xs leading-relaxed">
                {t('hero_subtitle')}
              </p>
            </div>
          </div>

          {/* Status + stats */}
          <div className="flex flex-col items-end gap-3">
            {/* Orchestrator health */}
            {healthLoading && (
              <div className="flex items-center gap-2 rounded-full bg-white/10 px-3.5 py-1.5 text-xs text-blue-100">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {t('status_connecting')}
              </div>
            )}
            {healthError && (
              <div className="flex items-center gap-2 rounded-full bg-red-500/20 px-3.5 py-1.5 text-xs text-red-200">
                <XCircle className="h-3.5 w-3.5" />
                {t('status_unreachable')}
              </div>
            )}
            {health && (
              <div className="flex items-center gap-2 rounded-full bg-emerald-400/20 px-3.5 py-1.5 text-xs text-emerald-200 font-medium">
                <CheckCircle2 className="h-3.5 w-3.5" />
                Orchestrator · {health.status}
              </div>
            )}

            {/* Quick stats */}
            <div className="flex gap-5">
              <div className="text-right">
                <p className="text-xl font-bold leading-none tabular-nums">{workspaces.length}</p>
                <p className="text-[10px] text-blue-300 mt-0.5 font-medium uppercase tracking-wide">{t('stat_workspaces')}</p>
              </div>
              <div className="w-px bg-white/10 self-stretch" />
              <div className="text-right">
                <p className="text-xl font-bold leading-none tabular-nums">{totalChats}</p>
                <p className="text-[10px] text-blue-300 mt-0.5 font-medium uppercase tracking-wide">{t('stat_conversations')}</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Config status row ──────────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-4">
        {/* Workspace */}
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-2">
            {t('card_active_workspace')}
          </p>
          {currentWorkspace ? (
            <>
              <p className="text-sm font-semibold text-gray-900 truncate leading-snug">
                {currentWorkspace.name}
              </p>
              <p className="text-[11px] text-gray-400 mt-0.5 font-mono truncate">
                {currentWorkspace.slug}
              </p>
            </>
          ) : workspaceId ? (
            <p className="text-sm font-medium text-gray-700 truncate">{workspaceId}</p>
          ) : (
            <p className="text-sm font-medium text-amber-600">{t('card_not_selected')}</p>
          )}
        </div>

        {/* Environment */}
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-2">
            {t('card_environment')}
          </p>
          <div
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold',
              env === 'dev' ? 'bg-blue-50 text-blue-700' : 'bg-orange-50 text-orange-700',
            )}
          >
            <span
              className={cn(
                'h-2 w-2 rounded-full',
                env === 'dev' ? 'bg-blue-500' : 'bg-orange-500',
              )}
            />
            {env === 'dev' ? t('card_env_dev') : t('card_env_prod')}
          </div>
          <p className="mt-1.5 text-[11px] text-gray-400">
            {env === 'dev' ? t('card_env_dev_desc') : t('card_env_prod_desc')}
          </p>
        </div>

        {/* Mode */}
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-2">
            {t('card_sql_mode')}
          </p>
          <div
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold ring-1',
              modeMeta.chip,
            )}
          >
            <modeMeta.Icon className="h-3.5 w-3.5" />
            {modeMeta.label}
          </div>
          <p className="mt-1.5 text-[11px] text-gray-400">{modeMeta.desc}</p>
        </div>
      </div>

      {/* ── First-query guide (new here?) ──────────────────────────────── */}
      <div className="rounded-xl border border-blue-100 bg-blue-50/40 px-5 py-4 shadow-sm">
        <div className="flex items-center justify-between gap-3 mb-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-blue-700/70">
            {t('guide_title')}
          </p>
          <a
            href="https://github.com/Onibex/agentic-semantic-knowledge-ask/tree/main/platform/ask-chat"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 text-[11px] font-medium text-blue-600 hover:text-blue-700 shrink-0"
          >
            <BookOpen className="h-3 w-3" />
            {t('guide_full')}
            <ExternalLink className="h-2.5 w-2.5 opacity-60" />
          </a>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-2 mb-3">
          {[t('guide_step1'), t('guide_step2'), t('guide_step3'), t('guide_step4')].map((text, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="h-5 w-5 rounded-full bg-blue-600 text-white text-[10px] font-bold flex items-center justify-center shrink-0">
                {i + 1}
              </span>
              <p className="text-xs text-gray-600 leading-snug">{text}</p>
            </div>
          ))}
        </div>
        <p className="text-[11px] text-gray-500 leading-relaxed">
          <span className="font-medium text-gray-600">{t('guide_modes_prefix')}</span>{' '}
          {t('guide_modes_body')}
        </p>
      </div>

      {/* ── Feature navigation ─────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-4">
        {FEATURES.map((f) => (
          <button
            key={f.to}
            onClick={() => navigate(f.to)}
            className={cn(
              'group relative overflow-hidden rounded-xl border border-gray-200 bg-white p-6 text-left shadow-sm',
              'transition-all duration-200 hover:shadow-md',
              f.hoverBorder,
            )}
          >
            {/* Hover gradient overlay */}
            <div
              className={cn(
                'absolute inset-0 bg-gradient-to-br from-transparent to-transparent transition-all duration-300',
                f.hoverGrad,
              )}
            />

            <div className="relative">
              {/* Icon */}
              <div
                className={cn(
                  'mb-4 inline-flex h-10 w-10 items-center justify-center rounded-xl text-white shadow-sm',
                  f.iconBg,
                )}
              >
                <f.Icon className="h-5 w-5" />
              </div>

              {/* Title + arrow */}
              <div className="flex items-start justify-between gap-2 mb-2">
                <h2
                  className={cn(
                    'text-base font-semibold text-gray-900 transition-colors',
                    f.hoverTitle,
                  )}
                >
                  {f.title}
                </h2>
                <ChevronRight
                  className={cn(
                    'h-4 w-4 shrink-0 mt-0.5 text-gray-300 transition-all duration-150',
                    f.hoverArrow,
                    'group-hover:translate-x-0.5',
                  )}
                />
              </div>

              {/* Description */}
              <p className="text-xs text-gray-500 leading-relaxed mb-4">{f.description}</p>

              {/* Tags */}
              <div className="flex flex-wrap gap-1.5">
                {f.tags.map((tag) => (
                  <span
                    key={tag}
                    className={cn('rounded-md px-2 py-0.5 text-[10px] font-semibold', f.tagClass)}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          </button>
        ))}
      </div>

      {/* ── Platform capabilities ──────────────────────────────────────── */}
      <div className="rounded-xl border border-gray-200 bg-white px-5 py-4 shadow-sm">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-3">
          {t('cap_section_title')}
        </p>
        <div className="flex flex-wrap gap-2">
          {CAPABILITIES.map(({ label, Icon }) => (
            <div
              key={label}
              className="flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 text-[11px] font-medium text-gray-600"
            >
              <Icon className="h-3.5 w-3.5 text-gray-400" />
              {label}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
