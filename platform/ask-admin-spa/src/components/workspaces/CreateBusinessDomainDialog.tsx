import { useState } from 'react'
import { toast } from 'sonner'

import { createBusinessDomain } from '@/api/client'
import type { BusinessDomain, Workspace } from '@/api/types'
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
import { Label } from '@/components/ui/label'
import { useTranslation } from '@/hooks/useTranslation'

interface Props {
  open: boolean
  workspace: Workspace
  onClose: () => void
  onCreated: (bd: BusinessDomain) => void
}

function nameToSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64)
}

export function CreateBusinessDomainDialog({ open, workspace, onClose, onCreated }: Props) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugDirty, setSlugDirty] = useState(false)
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)

  function reset() {
    setName('')
    setSlug('')
    setSlugDirty(false)
    setDescription('')
  }

  function handleNameChange(value: string) {
    setName(value)
    if (!slugDirty) setSlug(nameToSlug(value))
  }

  async function handleCreate() {
    if (!name.trim() || !slug.trim()) {
      toast.error(t('bd_create_required'))
      return
    }
    setSaving(true)
    try {
      const bd = await createBusinessDomain(workspace.id, {
        name: name.trim(),
        slug: slug.trim(),
        description: description.trim(),
        data_product_ids: [],
      })
      reset()
      onCreated(bd)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Could not create business domain'
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          reset()
          onClose()
        }
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('bd_create_title')}</DialogTitle>
          <DialogDescription>
            {t('bd_create_desc')}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div className="space-y-1">
            <Label>{t('bd_create_name_label')}</Label>
            <Input
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder={t('bd_create_name_ph')}
              autoFocus
            />
          </div>
          <div className="space-y-1">
            <Label>{t('bd_create_slug_label')}</Label>
            <Input
              value={slug}
              onChange={(e) => {
                setSlug(e.target.value)
                setSlugDirty(true)
              }}
              placeholder={t('bd_create_slug_ph')}
            />
          </div>
          <div className="space-y-1">
            <Label>{t('bd_create_description_label')}</Label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('bd_create_description_ph')}
              rows={4}
              className="w-full px-3 py-2 rounded-md border border-gray-300 bg-white text-sm resize-none"
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              reset()
              onClose()
            }}
            disabled={saving}
          >
            {t('common_cancel')}
          </Button>
          <Button onClick={() => void handleCreate()} disabled={saving}>
            {saving ? t('common_creating') : t('bd_create_btn')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
