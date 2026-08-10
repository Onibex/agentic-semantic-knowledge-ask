import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import type { Workspace, WorkspaceUpdatePayload } from '@/api/types'
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

interface Props {
  open: boolean
  workspace: Workspace
  onClose: () => void
  onSaved: (ws: Workspace) => void
  onPatch: (payload: WorkspaceUpdatePayload) => Promise<Workspace>
}

export function EditWorkspaceDialog({ open, workspace, onClose, onSaved, onPatch }: Props) {
  const [name, setName] = useState(workspace.name)
  const [slug, setSlug] = useState(workspace.slug)
  const [objective, setObjective] = useState(workspace.objective)
  const [description, setDescription] = useState(workspace.description)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) {
      setName(workspace.name)
      setSlug(workspace.slug)
      setObjective(workspace.objective)
      setDescription(workspace.description)
    }
  }, [open, workspace])

  async function handleSave() {
    if (!name.trim() || !slug.trim()) {
      toast.error('Name and slug are required')
      return
    }
    setSaving(true)
    try {
      const ws = await onPatch({
        name: name.trim(),
        slug: slug.trim(),
        objective: objective.trim(),
        description: description.trim(),
      })
      onSaved(ws)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Could not save workspace'
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Edit workspace</DialogTitle>
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
              Changing the slug updates URLs — bookmarks may break.
            </p>
          </div>
          <div className="space-y-1">
            <Label>Objective</Label>
            <Input value={objective} onChange={(e) => setObjective(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>Description</Label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              className="w-full px-3 py-2 rounded-md border border-gray-300 bg-white text-sm resize-none"
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
