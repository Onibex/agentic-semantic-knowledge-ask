import { CheckCircle2, ExternalLink, Loader2, Pencil, XCircle, Zap } from 'lucide-react'

import type { ConfigSection } from '@/api/types'
import { ProviderLogo } from '@/components/ProviderLogo'
import { Button } from '@/components/ui/button'

import { ConfigField } from './ConfigField'

/**
 * One card per system concern (LLM, Embedder, OpenSearch).
 *
 * Visual language mirrors ASK Setup's provider cards (colored rail + provider
 * monogram + slate surface) so the LLM/Embedder experience feels the same in
 * both apps. The card is layout-only — provider details come from the backend
 * ``fields[]`` array. The inline Test button (when ``test_target`` is set) shows
 * the latest result until a new test runs.
 *
 *   ┌▏[BR] LLM ───── AWS Bedrock ──── [ Manage in ASK Setup ↗ ] [ Test ] ┐
 *   │   model: bedrock/…nova-lite-v1:0                              plain  │
 *   │   AWS_BEARER_TOKEN_BEDROCK: ●●●●●●●●●●                     encrypt.  │
 *   │   ✓ Last test: 142 ms                                                │
 *   └──────────────────────────────────────────────────────────────────────┘
 */

export interface TestResult {
  success: boolean
  detail: string
  latency_ms: number
  error?: string | null
}

type Accent = 'violet' | 'cyan' | 'slate'

const RAIL: Record<Accent, string> = {
  violet: 'bg-violet-600',
  cyan: 'bg-cyan-600',
  slate: 'bg-slate-400',
}

interface Props {
  section: ConfigSection
  /** Latest test result for this card. Survives until the next test runs. */
  testResult?: TestResult
  /** True while a test is in flight. */
  testing?: boolean
  /** Triggered when the user clicks Test. Only invoked when test_target is set. */
  onTest?: () => void
  /** Triggered when the user clicks Edit. When omitted, the Edit button is hidden. */
  onEdit?: () => void
  /** Small pill next to the provider label (e.g. "Shared"). */
  badge?: string
  /**
   * "Managed elsewhere" affordance for read-only cards. When ``href`` is set it
   * renders an external link; otherwise a muted text hint (graceful degrade
   * when the target app URL is not configured).
   */
  manage?: { href?: string; label: string }
  /** Colored left rail — the card's identity accent. */
  accent?: Accent
  /** Provider brand mark shown before the title (matches ASK Setup). */
  avatar?: { provider: string; color: string }
  /**
   * Summary mode: show a clean ``model`` line instead of the credential field
   * rows. Used for LLM + Embedder so the card reads like ASK Setup (identity +
   * model), not a credential dump.
   */
  summaryOnly?: boolean
  /** Model string shown in summary mode. */
  summaryModel?: string
}

export function ConfigCard({
  section,
  testResult,
  testing = false,
  onTest,
  onEdit,
  badge,
  manage,
  accent,
  avatar,
  summaryOnly = false,
  summaryModel,
}: Props) {
  const hasTest = Boolean(section.test_target && onTest)

  return (
    <section className="relative border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden">
      {accent && <div className={`absolute left-0 top-0 bottom-0 w-1 ${RAIL[accent]}`} />}

      {/* Header */}
      <header className="flex items-center justify-between gap-3 px-4 py-3 pl-5 bg-slate-50 border-b border-slate-100">
        <div className="flex items-center gap-3 min-w-0">
          {avatar && (
            <div
              className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
              style={{ backgroundColor: `${avatar.color}22`, color: avatar.color }}
            >
              <ProviderLogo id={avatar.provider} size={20} />
            </div>
          )}
          <div className="flex items-baseline gap-2.5 flex-wrap min-w-0">
            <h3 className="text-base font-semibold text-slate-900">{section.title}</h3>
            {section.provider_label && (
              <span className="text-sm text-slate-500 font-medium">{section.provider_label}</span>
            )}
            {badge && (
              <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-cyan-50 text-cyan-700 border border-cyan-200">
                {badge}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {manage &&
            (manage.href ? (
              <a
                href={manage.href}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 h-7 px-2.5 text-sm rounded-md border border-slate-200 text-slate-600 hover:bg-slate-100"
              >
                <span>{manage.label}</span>
                <ExternalLink size={12} />
              </a>
            ) : (
              <span className="text-xs text-slate-400 italic">{manage.label}</span>
            ))}
          {onEdit && (
            <Button variant="outline" size="sm" onClick={onEdit} className="h-7 gap-1.5">
              <Pencil size={12} />
              <span>Edit</span>
            </Button>
          )}
          {hasTest && (
            <Button
              variant="outline"
              size="sm"
              onClick={onTest}
              disabled={testing}
              className="h-7 gap-1.5"
            >
              {testing ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Zap size={12} />
              )}
              <span>{testing ? 'Testing…' : 'Test'}</span>
            </Button>
          )}
        </div>
      </header>

      {/* Body — clean model summary (LLM/Embedder) or the credential rows */}
      <div className="px-5 py-2">
        {summaryOnly ? (
          <div className="py-2.5 text-sm font-mono text-slate-600">{summaryModel || '—'}</div>
        ) : section.fields.length === 0 ? (
          <p className="text-sm text-slate-400 italic py-3">
            No fields configured for this provider.
          </p>
        ) : (
          section.fields.map((f) => <ConfigField key={f.name} field={f} />)
        )}
      </div>

      {/* Info / hint */}
      {section.info && (
        <div className="px-5 py-2 text-xs text-slate-500 italic border-t border-slate-100">
          {section.info}
        </div>
      )}

      {/* Test result */}
      {testResult && (
        <div
          className={`px-5 py-2 text-sm border-t flex items-start gap-2 ${
            testResult.success
              ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
              : 'border-red-200 bg-red-50 text-red-800'
          }`}
        >
          {testResult.success ? (
            <CheckCircle2 size={14} className="mt-0.5 shrink-0" />
          ) : (
            <XCircle size={14} className="mt-0.5 shrink-0" />
          )}
          <div className="min-w-0 flex-1">
            <div className="font-medium">
              {testResult.success
                ? `${testResult.detail} · ${testResult.latency_ms} ms`
                : `Test failed · ${testResult.latency_ms} ms`}
            </div>
            {!testResult.success && testResult.error && (
              <div className="text-xs mt-1 font-mono break-words">
                {testResult.error}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
