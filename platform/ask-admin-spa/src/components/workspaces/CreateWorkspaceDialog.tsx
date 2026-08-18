/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useState } from 'react'
import { toast } from 'sonner'

import { createWorkspace } from '@/api/client'
import type { Workspace } from '@/api/types'
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

/**
 * "+ New Workspace" modal.
 *
 * Auto-derives the slug from the name on the fly (admin can still override).
 * Slug rules mirror the backend validator: lowercase, digits + single
 * hyphens; the server enforces uniqueness + reserved-word checks and surfaces
 * a clean 409 if the slug clashes.
 */
interface Props {
  open: boolean
  onClose: () => void
  onCreated: (ws: Workspace) => void
}

function nameToSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64)
}

export function CreateWorkspaceDialog({ open, onClose, onCreated }: Props) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugDirty, setSlugDirty] = useState(false)
  const [objective, setObjective] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)

  function reset() {
    setName('')
    setSlug('')
    setSlugDirty(false)
    setObjective('')
    setDescription('')
  }

  function handleNameChange(value: string) {
    setName(value)
    if (!slugDirty) setSlug(nameToSlug(value))
  }

  async function handleCreate() {
    if (!name.trim() || !slug.trim()) {
      toast.error(t('ws_create_required'))
      return
    }
    setSaving(true)
    try {
      const ws = await createWorkspace({
        name: name.trim(),
        slug: slug.trim(),
        objective: objective.trim(),
        description: description.trim(),
      })
      reset()
      onCreated(ws)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Could not create workspace'
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
          <DialogTitle>{t('ws_create_title')}</DialogTitle>
          <DialogDescription>
            {t('ws_create_desc')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <div className="space-y-1">
            <Label htmlFor="ws-name">{t('ws_create_name_label')}</Label>
            <Input
              id="ws-name"
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder={t('ws_create_name_ph')}
              autoFocus
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ws-slug">{t('ws_create_slug_label')}</Label>
            <Input
              id="ws-slug"
              value={slug}
              onChange={(e) => {
                setSlug(e.target.value)
                setSlugDirty(true)
              }}
              placeholder={t('ws_create_slug_ph')}
            />
            <p className="text-xs text-gray-500">
              {t('ws_create_slug_hint')}
            </p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="ws-objective">{t('ws_create_objective_label')}</Label>
            <Input
              id="ws-objective"
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              placeholder={t('ws_create_objective_ph')}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ws-description">{t('ws_create_description_label')}</Label>
            <textarea
              id="ws-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('ws_create_description_ph')}
              rows={3}
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
            {saving ? t('common_creating') : t('ws_create_btn')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
