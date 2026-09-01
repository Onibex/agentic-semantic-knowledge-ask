/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { updateBusinessDomain } from '@/api/client'
import type { BusinessDomain } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/**
 * Edit name / slug / description of an existing Business Domain. The
 * ``data_product_ids`` set is managed separately via ManageEntitiesDialog —
 * keeping the two concerns split so this dialog stays simple (rename + retype,
 * no checkbox tree) and the manage dialog stays focused (no text inputs
 * polluting the picker).
 */
interface Props {
  open: boolean
  businessDomain: BusinessDomain
  onClose: () => void
  /** Called with the freshly-patched BD so the parent can swap it into state. */
  onSaved: (bd: BusinessDomain) => void
}

export function EditBusinessDomainDialog({ open, businessDomain, onClose, onSaved }: Props) {
  const [name, setName] = useState(businessDomain.name)
  const [slug, setSlug] = useState(businessDomain.slug)
  const [description, setDescription] = useState(businessDomain.description ?? '')
  const [saving, setSaving] = useState(false)

  // Re-hydrate every time the dialog opens — the parent may have refreshed
  // the underlying BD between opens (e.g. after another patch).
  useEffect(() => {
    if (open) {
      setName(businessDomain.name)
      setSlug(businessDomain.slug)
      setDescription(businessDomain.description ?? '')
    }
  }, [open, businessDomain])

  async function handleSave() {
    if (!name.trim() || !slug.trim()) {
      toast.error('Name and slug are required')
      return
    }
    setSaving(true)
    try {
      const bd = await updateBusinessDomain(businessDomain.id, {
        name: name.trim(),
        slug: slug.trim(),
        description: description.trim(),
      })
      onSaved(bd)
      toast.success('Business domain updated')
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Could not save business domain'
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Edit business domain</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div className="space-y-1">
            <Label>Name *</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>Slug *</Label>
            <Input value={slug} onChange={(e) => setSlug(e.target.value)} />
            <p className="text-xs text-gray-500">
              Changing the slug updates references — pipelines or links pointing
              to the previous slug may break.
            </p>
          </div>
          <div className="space-y-1">
            <Label>Description</Label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              className="w-full px-3 py-2 rounded-md border border-gray-300 bg-white text-sm resize-none"
              placeholder="What business question does this domain answer?"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={() => void handleSave()} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
