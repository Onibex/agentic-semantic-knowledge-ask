/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { Info, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'

import {
  getSetupEffective,
  testOpenSearchConnection,
  testSecrets,
} from '@/api/client'
import type { ConfigSection } from '@/api/types'
import { ConfigCard, type TestResult } from '@/components/admin/setup/ConfigCard'
import { EmbedderDrawer } from '@/components/admin/setup/EmbedderDrawer'
import { providerColor } from '@/components/admin/setup/providerMeta'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/hooks/useTranslation'

function cardAccent(id: string): 'violet' | 'cyan' | 'slate' {
  if (id === 'llm') return 'violet'
  if (id === 'embedder') return 'cyan'
  return 'slate'
}

function cardAvatar(section: { id: string; provider?: string }): { provider: string; color: string } {
  const p = section.id === 'opensearch' ? 'opensearch' : section.provider ?? ''
  return { provider: p, color: providerColor(p) }
}

function sectionModel(section: ConfigSection): string {
  return section.fields.find((f) => f.name === 'model')?.value ?? ''
}

/**
 * System Setup — provider-aware view with inline editing for LLM + Embedder.
 *
 * The SPA owns the write path for the two cards backed by the encrypted
 * secrets store (``ask-system-settings-v1`` in OpenSearch). OpenSearch
 * connection itself stays read-only — its credentials must live in env
 * vars (K8s Secret) because the encrypted store needs them to boot.
 *
 *   ┌─ LLM ────────────────── AWS Bedrock ─── [ Edit ] [ Test ] ┐
 *   │ model: bedrock/converse/us.amazon.nova-lite-v1:0    plain │
 *   │ AWS_BEARER_TOKEN_BEDROCK: ***                    encrypt. │
 *   │ AWS_REGION: us-east-2                              plain  │
 *   │ ✓ Last test: 142 ms                                       │
 *   └───────────────────────────────────────────────────────────┘
 */

export default function SetupPage() {
  const { t } = useTranslation()
  const [sections, setSections] = useState<ConfigSection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({})
  const [testingId, setTestingId] = useState<string | null>(null)
  const [editingEmbedder, setEditingEmbedder] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getSetupEffective()
      setSections(data.sections)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load setup'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const handleTest = useCallback(async (section: ConfigSection) => {
    if (!section.test_target) return
    setTestingId(section.id)
    const target = section.test_target
    try {
      let result: TestResult
      if (target === 'opensearch') {
        const r = await testOpenSearchConnection()
        result = {
          success: r.success,
          detail: r.detail,
          latency_ms: r.latency_ms,
          error: r.error,
        }
      } else {
        // LLM / Embedder — call the new secrets/test endpoint which runs
        // against the stored encrypted config (no payload override).
        const r = await testSecrets({ target })
        result = {
          success: r.success,
          detail: r.detail,
          latency_ms: r.latency_ms,
          error: r.error,
        }
      }
      setTestResults((prev) => ({ ...prev, [section.id]: result }))
      if (!result.success) {
        toast.error(`${section.title} test failed`)
      } else {
        toast.success(`${section.title} ok · ${result.latency_ms} ms`)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Network error'
      setTestResults((prev) => ({
        ...prev,
        [section.id]: {
          success: false,
          detail: 'Network error',
          latency_ms: 0,
          error: msg,
        },
      }))
      toast.error(msg)
    } finally {
      setTestingId(null)
    }
  }, [])

  // Cross-app link to ASK Setup's LLM Providers page. Falls back to a muted
  // text hint when the deployment does not set the URL (no broken link).
  const setupSpaUrl = (import.meta.env.VITE_SETUP_SPA_URL as string | undefined)?.replace(/\/$/, '')
  const llmManageHref = setupSpaUrl ? `${setupSpaUrl}/llm-providers` : undefined

  return (
    <div className="max-w-3xl mx-auto p-6">
      {/* Header */}
      <header className="flex items-start justify-between mb-2">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">{t('setup_title')}</h1>
          <p className="text-sm text-gray-500 mt-1">{t('setup_subtitle')}</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          <span className="ml-1.5">{t('common_refresh')}</span>
        </Button>
      </header>

      {/* OpenSearch read-only banner */}
      <div className="flex items-start gap-2 px-3 py-2.5 rounded-md bg-slate-50 border border-slate-200 mb-6 text-sm text-slate-700">
        <Info size={14} className="mt-0.5 shrink-0" />
        <div className="flex-1">{t('setup_os_banner')}</div>
      </div>

      {/* Body */}
      {loading && sections.length === 0 && (
        <div className="flex items-center justify-center py-12 text-gray-500">
          <RefreshCw size={14} className="animate-spin mr-2" />
          {t('common_loading')}
        </div>
      )}

      {error && !loading && (
        <div className="px-3 py-2.5 rounded-md bg-red-50 border border-red-200 text-sm text-red-900">
          {t('setup_load_error').replace('{error}', error)}
        </div>
      )}

      <div className="space-y-4">
        {sections.map((s) => (
          <ConfigCard
            key={s.id}
            section={s}
            testResult={testResults[s.id]}
            testing={testingId === s.id}
            onTest={() => void handleTest(s)}
            // Edit affordance only on the Embedder (single shared config).
            onEdit={s.id === 'embedder' ? () => setEditingEmbedder(true) : undefined}
            // Embedder is shared across apps; the LLM is managed in ASK Setup.
            badge={s.id === 'embedder' ? 'Shared' : undefined}
            manage={s.id === 'llm' ? { href: llmManageHref, label: 'Manage in ASK Setup' } : undefined}
            accent={cardAccent(s.id)}
            avatar={cardAvatar(s)}
            // LLM + Embedder show a clean model summary, not the credential rows.
            summaryOnly={s.id === 'llm' || s.id === 'embedder'}
            summaryModel={sectionModel(s)}
          />
        ))}

      </div>

      <EmbedderDrawer
        open={editingEmbedder}
        onSaved={() => void load()}
        onClose={() => setEditingEmbedder(false)}
      />
    </div>
  )
}
