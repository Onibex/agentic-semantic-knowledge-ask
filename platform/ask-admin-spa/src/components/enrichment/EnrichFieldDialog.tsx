import { Loader2, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'

import { previewFieldEnrichment, updateYaml } from '@/api/client'
import type { EnrichFieldResponse, YAMLNode } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useAuthStore } from '@/store/authStore'

/**
 * Single-field AI enrichment — one LLM call, one diff, accept or cancel.
 *
 * Opens with a spinner while the backend builds the prompt + invokes the
 * LLM. On success shows the before/after for description + synonyms; on
 * Apply, persists through ``PATCH /v1/viz/yamls/{id}`` (same write path as
 * the manual editor).
 */

interface Props {
  open: boolean
  entity: YAMLNode
  fieldName: string
  onClose: () => void
  onApplied: () => void
}

export function EnrichFieldDialog({
  open,
  entity,
  fieldName,
  onClose,
  onApplied,
}: Props) {
  const user = useAuthStore((s) => s.user)
  const [diff, setDiff] = useState<EnrichFieldResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setDiff(null)
    previewFieldEnrichment({ entity_id: entity.id, field_name: fieldName })
      .then((r) => {
        if (!cancelled) setDiff(r)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const msg = err instanceof Error ? err.message : 'Enrichment failed'
        setError(msg)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, entity.id, fieldName])

  const handleApply = useCallback(async () => {
    if (!diff) return
    setApplying(true)
    setError(null)
    try {
      const fieldUpdate: { name: string; description?: string; synonyms?: string[] } = {
        name: diff.field_name,
      }
      if (diff.diff.description) fieldUpdate.description = diff.diff.description.new
      if (diff.diff.synonyms) fieldUpdate.synonyms = diff.diff.synonyms.new
      await updateYaml(entity.id, {
        author_email: user?.email,
        fields: [fieldUpdate],
        source: 'ai_assist',
      })
      toast.success('Field enriched')
      onApplied()
      onClose()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Apply failed'
      setError(msg)
      toast.error(msg)
    } finally {
      setApplying(false)
    }
  }, [diff, entity.id, user?.email, onApplied, onClose])

  const hasChange = Boolean(
    diff && (diff.diff.description || diff.diff.synonyms),
  )

  return (
    <Dialog open={open} onOpenChange={(o) => !o && !applying && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles size={16} className="text-blue-600" />
            AI Assist — {fieldName}
          </DialogTitle>
        </DialogHeader>

        {loading && (
          <div className="flex flex-col items-center justify-center py-12 text-gray-500 gap-2">
            <Loader2 size={18} className="animate-spin" />
            <div className="text-sm">Generating…</div>
          </div>
        )}

        {!loading && diff && (
          <div className="space-y-3 py-2">
            <div className="text-[11px] text-gray-500">
              {diff.provider} · {diff.model || '—'} ·{' '}
              {diff.tokens_used.toLocaleString()} tokens · {diff.elapsed_ms} ms
            </div>

            {diff.diff.description ? (
              <DiffRow
                label="description"
                oldText={diff.diff.description.old}
                newText={diff.diff.description.new}
              />
            ) : (
              <p className="text-[11px] text-gray-400 italic">
                description: no change proposed
              </p>
            )}

            {diff.diff.synonyms ? (
              <DiffRow
                label="synonyms"
                oldText={renderSynonyms(diff.diff.synonyms.old)}
                newText={renderSynonyms(diff.diff.synonyms.new)}
              />
            ) : (
              <p className="text-[11px] text-gray-400 italic">
                synonyms: no change proposed
              </p>
            )}

            {!hasChange && (
              <p className="text-xs text-gray-500 italic text-center py-3">
                The model returned no changes for this field.
              </p>
            )}
          </div>
        )}

        {error && (
          <div className="px-3 py-2 mt-2 rounded-md bg-red-50 border border-red-200 text-sm text-red-900">
            {error}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={applying}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleApply()}
            disabled={!hasChange || applying || loading}
          >
            {applying ? (
              <>
                <Loader2 size={12} className="animate-spin mr-1.5" /> Applying…
              </>
            ) : (
              'Apply'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DiffRow({
  label,
  oldText,
  newText,
}: {
  label: string
  oldText: string
  newText: string
}) {
  return (
    <div className="text-[11px] grid grid-cols-[80px_1fr] gap-2">
      <span className="text-gray-500 font-mono">{label}</span>
      <div className="space-y-1">
        <div className="flex gap-1.5">
          <span className="text-gray-400 shrink-0">old</span>
          <span className="text-gray-700 line-through decoration-red-300/60">
            {oldText || <em className="text-gray-300">empty</em>}
          </span>
        </div>
        <div className="flex gap-1.5">
          <span className="text-emerald-700 shrink-0">new</span>
          <span className="text-gray-900 font-medium">{newText}</span>
        </div>
      </div>
    </div>
  )
}

function renderSynonyms(list: string[]): string {
  return list.length ? `[${list.join(', ')}]` : ''
}
