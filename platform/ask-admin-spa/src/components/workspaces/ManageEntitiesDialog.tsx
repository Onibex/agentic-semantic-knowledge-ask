import { Boxes, Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { listYamls, updateBusinessDomain } from '@/api/client'
import type { BusinessDomain, YAMLNodeSummary } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useTranslation } from '@/hooks/useTranslation'

/**
 * Data-product picker for a Business Domain.
 *
 * Lists every workspace YAML grouped by layer (gold → silver → bronze).
 * Bronzes are usually internal masters; we hide them by default and let the
 * admin toggle "include bronzes" if they want to add one explicitly. Most
 * Business Domains only reference golds + silvers.
 */
interface Props {
  open: boolean
  businessDomain: BusinessDomain
  onClose: () => void
  onSaved: (bd: BusinessDomain) => void
}

const LAYER_ORDER: Array<YAMLNodeSummary['layer']> = ['gold', 'silver', 'bronze']

export function ManageEntitiesDialog({ open, businessDomain, onClose, onSaved }: Props) {
  const { t } = useTranslation()
  const [allYamls, setAllYamls] = useState<YAMLNodeSummary[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set(businessDomain.data_product_ids))
  const [filter, setFilter] = useState('')
  const [showBronze, setShowBronze] = useState(false)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  const LAYER_LABELS: Record<YAMLNodeSummary['layer'], string> = {
    gold: t('bd_manage_gold'),
    silver: t('bd_manage_silver'),
    bronze: t('bd_manage_bronze'),
  }

  useEffect(() => {
    if (!open) return
    setSelected(new Set(businessDomain.data_product_ids))
    setLoading(true)
    listYamls()
      .then(setAllYamls)
      .catch((err) =>
        toast.error(err instanceof Error ? err.message : 'Failed to load entities'),
      )
      .finally(() => setLoading(false))
  }, [open, businessDomain])

  const grouped = useMemo(() => {
    const q = filter.trim().toLowerCase()
    const filtered = allYamls.filter((y) => {
      if (!showBronze && y.layer === 'bronze') return false
      if (!q) return true
      return (
        y.id.toLowerCase().includes(q) ||
        y.name.toLowerCase().includes(q) ||
        (y.alias ?? '').toLowerCase().includes(q)
      )
    })
    const byLayer = new Map<YAMLNodeSummary['layer'], YAMLNodeSummary[]>()
    for (const y of filtered) {
      if (!byLayer.has(y.layer)) byLayer.set(y.layer, [])
      byLayer.get(y.layer)!.push(y)
    }
    for (const arr of byLayer.values()) {
      arr.sort((a, b) => a.id.localeCompare(b.id))
    }
    return byLayer
  }, [allYamls, filter, showBronze])

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleSave() {
    setSaving(true)
    try {
      const bd = await updateBusinessDomain(businessDomain.id, {
        data_product_ids: Array.from(selected),
      })
      onSaved(bd)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Could not save'
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('bd_manage_title').replace('{name}', businessDomain.name)}</DialogTitle>
          <DialogDescription>
            {t('bd_manage_desc')}
          </DialogDescription>
        </DialogHeader>

        {/* Filter + bronze toggle */}
        <div className="flex items-center gap-2 py-2">
          <div className="relative flex-1">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <Input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={t('bd_manage_filter_ph')}
              className="pl-8"
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer shrink-0">
            <input
              type="checkbox"
              checked={showBronze}
              onChange={(e) => setShowBronze(e.target.checked)}
              className="h-4 w-4"
            />
            {t('bd_manage_include_bronzes')}
          </label>
        </div>

        {/* Selected count */}
        <div className="text-xs text-gray-500 mb-1">
          <strong>{selected.size}</strong> {t('bd_manage_selected')}
        </div>

        {/* Entity list */}
        <div className="max-h-[400px] overflow-y-auto border border-gray-200 rounded-md">
          {loading ? (
            <div className="px-4 py-8 text-center text-sm text-gray-500">{t('bd_manage_loading')}</div>
          ) : grouped.size === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-gray-500">
              <Boxes size={20} className="mx-auto mb-2 text-gray-300" />
              {t('bd_manage_no_entities')}
            </div>
          ) : (
            LAYER_ORDER.filter((layer) => grouped.has(layer)).map((layer) => (
              <div key={layer} className="border-b border-gray-100 last:border-b-0">
                <div className="px-3 py-1.5 bg-gray-50 text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                  {LAYER_LABELS[layer]} · {grouped.get(layer)!.length}
                </div>
                {grouped.get(layer)!.map((y) => (
                  <label
                    key={y.id}
                    className="flex items-center gap-2 px-3 py-2 hover:bg-blue-50 cursor-pointer border-b border-gray-50 last:border-b-0"
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(y.id)}
                      onChange={() => toggle(y.id)}
                      className="h-4 w-4"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-gray-900 truncate">{y.name}</div>
                      <code className="text-xs text-gray-400 font-mono">{y.id}</code>
                    </div>
                  </label>
                ))}
              </div>
            ))
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {t('common_cancel')}
          </Button>
          <Button onClick={() => void handleSave()} disabled={saving}>
            {saving
              ? t('common_saving')
              : selected.size === 1
                ? t('bd_manage_save_singular').replace('{count}', String(selected.size))
                : t('bd_manage_save_plural').replace('{count}', String(selected.size))}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
