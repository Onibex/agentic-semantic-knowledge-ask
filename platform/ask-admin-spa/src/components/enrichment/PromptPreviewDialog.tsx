import { Code2, Copy, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { previewEnrichmentPrompt } from '@/api/client'
import type { EnrichEntityScope, PromptPreviewResponse } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

/**
 * Show the LLM-bound (system, user) prompt pair for an entity + scope.
 *
 * Pure read-only inspection — calls ``/v1/admin/enrich/entity/{id}/prompt-preview``
 * which composes the exact text the model would receive WITHOUT invoking
 * the LLM. Lets the admin audit bias (workspace, organization, standards,
 * system prompt) before spending tokens. The system prompt section is the
 * one editable via ``/v1/admin/prompts/enrichment`` if anything looks off.
 */
interface Props {
  open: boolean
  onClose: () => void
  entityId: string
  scope: EnrichEntityScope
  workspaceId: string | null
}

export function PromptPreviewDialog({ open, onClose, entityId, scope, workspaceId }: Props) {
  const [data, setData] = useState<PromptPreviewResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setData(null)
    previewEnrichmentPrompt(entityId, { scope, workspace_id: workspaceId })
      .then((resp) => {
        if (cancelled) return
        setData(resp)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load prompt preview')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, entityId, scope, workspaceId])

  async function copy(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(`${label} copied to clipboard`)
    } catch {
      toast.error('Could not copy — your browser blocked the clipboard.')
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Code2 size={16} className="text-violet-600" />
            Full prompt — what the AI will see
          </DialogTitle>
          <DialogDescription>
            Exact text composed for this entity + scope + workspace. No LLM call is made
            here. Edit the role/rules section at{' '}
            <code className="font-mono">/v1/admin/prompts/enrichment</code> if the system
            prompt needs to change.
          </DialogDescription>
        </DialogHeader>

        {loading && (
          <div className="flex flex-1 items-center justify-center py-12 text-gray-500 gap-2">
            <Loader2 className="h-4 w-4 animate-spin" /> Composing prompt…
          </div>
        )}

        {error && !loading && (
          <div className="px-3 py-2 rounded-md bg-red-50 border border-red-200 text-sm text-red-900">
            {error}
          </div>
        )}

        {data && !loading && (
          <div className="flex-1 overflow-y-auto -mx-6 px-6 space-y-4">
            <div className="text-[11px] text-gray-500 flex items-center gap-3 flex-wrap">
              <span>
                Target model:{' '}
                <span className="font-mono text-gray-700">
                  {data.provider} · {data.model || '—'}
                </span>
              </span>
              <span>
                System: <span className="font-mono">{data.system_chars.toLocaleString()}</span>{' '}
                chars
              </span>
              <span>
                User: <span className="font-mono">{data.user_chars.toLocaleString()}</span>{' '}
                chars
              </span>
            </div>

            <PromptSection
              label="SYSTEM message"
              hint="Role, rules, output format, standards excerpt, customer context."
              body={data.system_message}
              onCopy={() => void copy(data.system_message, 'System message')}
            />

            <PromptSection
              label="USER message"
              hint="Entity header, workspace context, fields to enrich, other field names."
              body={data.user_message}
              onCopy={() => void copy(data.user_message, 'User message')}
            />
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

interface PromptSectionProps {
  label: string
  hint: string
  body: string
  onCopy: () => void
}

function PromptSection({ label, hint, body, onCopy }: PromptSectionProps) {
  return (
    <section className="border border-gray-200 rounded-md">
      <header className="flex items-center gap-2 px-3 py-2 border-b border-gray-200 bg-gray-50">
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold text-gray-700 uppercase tracking-wider">
            {label}
          </div>
          <div className="text-[10px] text-gray-500">{hint}</div>
        </div>
        <Button variant="outline" size="sm" onClick={onCopy} className="h-7 px-2 text-xs">
          <Copy size={11} className="mr-1" />
          Copy
        </Button>
      </header>
      <pre className="text-[11px] font-mono whitespace-pre-wrap break-words px-3 py-2 max-h-80 overflow-y-auto leading-relaxed text-gray-800">
        {body}
      </pre>
    </section>
  )
}
