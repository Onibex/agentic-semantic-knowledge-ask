/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { Upload } from 'lucide-react'
import { useState } from 'react'

import { type UploadYamlOutcome } from '@/api/client'
import { UploadYamlPanel } from '@/components/workspaces/UploadYamlPanel'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

/**
 * Standalone multi-file YAML upload dialog (Graph page). The drag-drop +
 * per-file upload flow lives in UploadYamlPanel (shared with the "New data
 * product" → Upload files tab); this is just the dialog chrome around it.
 */

interface Props {
  open: boolean
  onClose: () => void
  /** Triggered when at least one file landed successfully — parent should refetch the catalogue. */
  onUploaded: (outcomes: UploadYamlOutcome[]) => void
}

export function UploadYamlDialog({ open, onClose, onUploaded }: Props) {
  const [busy, setBusy] = useState(false)

  return (
    <Dialog open={open} onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent className="sm:max-w-xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Upload size={16} /> Upload YAMLs to workspace
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto -mx-6 px-6 py-2">
          <UploadYamlPanel onUploaded={onUploaded} onBusyChange={setBusy} />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
