import { Check, Copy } from 'lucide-react'
import { useState } from 'react'

import type { ConfigFieldRO } from '@/api/types'

/**
 * Renders one row inside a ConfigCard.
 *
 *  - Sensitive values get a fixed-length opaque mask (●●●●●●●●●●). We never
 *    leak length so attackers can't infer entropy.
 *  - Long URLs / IDs (>50 chars) truncate with ellipsis + click-to-copy.
 *  - Source badge sits at the right edge: ENV (green) > FILE (blue) > DEFAULT (gray).
 *
 * The component is intentionally dumb — it doesn't know about providers,
 * just renders whatever the backend chose to expose.
 */

const SOURCE_BADGE: Record<ConfigFieldRO['source'], { label: string; className: string }> = {
  environment: {
    label: 'ENV',
    className: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  },
  file: {
    label: 'FILE',
    className: 'bg-blue-50 text-blue-700 border-blue-200',
  },
  encrypted: {
    label: 'ENCRYPTED',
    className: 'bg-amber-50 text-amber-700 border-amber-200',
  },
  plain: {
    label: 'STORED',
    className: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  },
  default: {
    label: 'DEFAULT',
    className: 'bg-gray-50 text-gray-500 border-gray-200',
  },
}

const SOURCE_TITLE: Record<ConfigFieldRO['source'], string> = {
  environment: 'Loaded from a process env var (K8s Secret in prod, shell in dev)',
  file: 'Loaded from config/settings.json',
  encrypted: 'Fernet-encrypted in OpenSearch (ask-system-settings-v1) — value never leaves the server',
  plain: 'Stored in OpenSearch (ask-system-settings-v1) as a non-sensitive value',
  default: 'No value set — using internal default',
}

const MASK = '●●●●●●●●●●●●'
const TRUNCATE_AT = 50

function formatLabel(name: string, override?: string | null): string {
  if (override) return override
  // snake_case → Title Case ("api_base" → "API base", "AWS_BEARER_TOKEN_BEDROCK"
  // stays uppercase because users recognize it as an env var)
  if (name === name.toUpperCase() && name.includes('_')) return name
  return name
    .split('_')
    .map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(' ')
}

// Fallback badge when the backend ships a future source value the SPA does not know.
// Keeps the UI from crashing on schema evolution.
const UNKNOWN_BADGE = {
  label: 'UNKNOWN',
  className: 'bg-gray-50 text-gray-500 border-gray-200',
}

export function ConfigField({ field }: { field: ConfigFieldRO }) {
  const [copied, setCopied] = useState(false)
  const badge = SOURCE_BADGE[field.source] ?? UNKNOWN_BADGE
  const titleText = SOURCE_TITLE[field.source] ?? `Source: ${field.source}`
  const isEmpty = field.source === 'default' && !field.value
  const display = field.sensitive ? MASK : field.value || '—'
  const truncate = display.length > TRUNCATE_AT
  const visibleValue = truncate ? `${display.slice(0, TRUNCATE_AT)}…` : display

  async function handleCopy() {
    if (field.sensitive || !field.value) return
    try {
      await navigator.clipboard.writeText(field.value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard not allowed (insecure context); silent fail is OK
    }
  }

  return (
    <div className="flex items-start gap-3 py-2 border-b border-gray-100 last:border-b-0">
      <div className="w-56 shrink-0 text-sm font-medium text-gray-700 break-words">
        {formatLabel(field.name, field.label)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <code
            className={`text-sm font-mono ${
              isEmpty ? 'text-gray-400 italic' : 'text-gray-900'
            } ${truncate ? 'cursor-pointer hover:underline' : ''}`}
            title={truncate ? display : undefined}
            onClick={truncate ? handleCopy : undefined}
          >
            {visibleValue}
          </code>
          {!field.sensitive && field.value && !truncate && (
            <button
              type="button"
              onClick={handleCopy}
              className="opacity-0 hover:opacity-100 group-hover:opacity-100 text-gray-400 hover:text-gray-700 transition-opacity"
              aria-label="Copy"
              title="Copy"
            >
              {copied ? <Check size={12} className="text-emerald-600" /> : <Copy size={12} />}
            </button>
          )}
          {copied && truncate && (
            <span className="text-xs text-emerald-600">copied</span>
          )}
        </div>
        {field.help_text && (
          <p className="text-xs text-gray-500 mt-0.5">{field.help_text}</p>
        )}
      </div>
      <span
        className={`shrink-0 text-[10px] font-semibold tracking-wider px-2 py-0.5 rounded border ${badge.className}`}
        title={titleText}
      >
        {badge.label}
      </span>
    </div>
  )
}
