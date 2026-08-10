import { useEffect, useState } from 'react'
import { Pencil, Trash2, Plus, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from 'sonner'
import { listPhrases, upsertPhrase, deletePhrase } from '@/api/client'
import type { PhraseEntry, SapModule } from '@/api/types'

// ── Constants ────────────────────────────────────────────────────────────────

const MODULES: SapModule[] = ['SD', 'MM', 'PP', 'FI', 'CO']

const MODULE_COLORS: Record<SapModule, string> = {
  SD: '#3b82f6',
  MM: '#22c55e',
  PP: '#f97316',
  FI: '#a855f7',
  CO: '#ec4899',
}

const EMPTY_FORM: Omit<PhraseEntry, 'type' | 'technical_name'> = {
  canonical_label: '',
  module: 'SD',
  source_system: 's4h',
  synonyms: '',
  context_clues: '',
  disambiguation_hint: '',
  description: '',
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function trunc(str: string, max: number): string {
  if (!str) return ''
  return str.length > max ? str.slice(0, max) + '…' : str
}

// ── Sub-components ───────────────────────────────────────────────────────────

function ModuleBadge({ module }: { module: string }) {
  const color = MODULE_COLORS[module as SapModule] ?? '#6b7280'
  return (
    <span
      className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold text-white"
      style={{ backgroundColor: color }}
    >
      {module}
    </span>
  )
}

function SkeletonRow() {
  return (
    <TableRow>
      {[1, 2, 3, 4, 5].map((i) => (
        <TableCell key={i}>
          <div className="h-4 rounded bg-gray-200 animate-pulse" style={{ width: i === 5 ? '4rem' : '80%' }} />
        </TableCell>
      ))}
    </TableRow>
  )
}

// ── Phrase Form Dialog (T17) ─────────────────────────────────────────────────

interface PhraseDialogProps {
  open: boolean
  entry: PhraseEntry | null
  onClose: () => void
  onSaved: () => void
}

function PhraseDialog({ open, entry, onClose, onSaved }: PhraseDialogProps) {
  const isEdit = entry !== null
  const [form, setForm] = useState<Omit<PhraseEntry, 'type' | 'technical_name'>>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [validationErrors, setValidationErrors] = useState<Partial<Record<keyof typeof EMPTY_FORM, string>>>({})

  // Pre-load values when editing
  useEffect(() => {
    if (open) {
      setError(null)
      setValidationErrors({})
      if (entry) {
        setForm({
          id: entry.id,
          canonical_label: entry.canonical_label,
          module: entry.module,
          source_system: entry.source_system || 's4h',
          synonyms: entry.synonyms || '',
          context_clues: entry.context_clues || '',
          disambiguation_hint: entry.disambiguation_hint || '',
          description: entry.description || '',
        })
      } else {
        setForm({ ...EMPTY_FORM })
      }
    }
  }, [open, entry])

  function validate(): boolean {
    const errs: Partial<Record<keyof typeof EMPTY_FORM, string>> = {}
    if (!form.canonical_label.trim()) errs.canonical_label = 'Term is required'
    if (!form.module) errs.module = 'Module is required'
    setValidationErrors(errs)
    return Object.keys(errs).length === 0
  }

  async function handleSave() {
    if (!validate()) return
    setSaving(true)
    setError(null)
    try {
      const payload: PhraseEntry = {
        ...form,
        type: 'phrase',
        technical_name: '',
      }
      const result = await upsertPhrase(payload)
      if (!result.success) {
        setError(result.message || 'Server returned failure — check server logs.')
        return
      }
      onSaved()
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : typeof err === 'object' && err !== null && 'response' in err
            ? (err as { response?: { data?: { detail?: string; message?: string } } }).response?.data?.detail ??
              (err as { response?: { data?: { detail?: string; message?: string } } }).response?.data?.message ??
              'Failed to save'
            : 'Failed to save'
      setError(msg)
    } finally {
      setSaving(false)
    }
  }

  function field(key: keyof typeof EMPTY_FORM, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }))
    if (validationErrors[key]) {
      setValidationErrors((prev) => ({ ...prev, [key]: undefined }))
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v && !saving) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit phrase' : 'New phrase'}</DialogTitle>
          <DialogDescription>
            {isEdit ? 'Update the semantic phrase details.' : 'Register a new term in the semantic dictionary.'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* canonical_label */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium leading-none">
              Term / Phrase <span className="text-red-500">*</span>
            </label>
            <Input
              value={form.canonical_label}
              onChange={(e) => field('canonical_label', e.target.value)}
              placeholder="e.g. monthly sales, pending orders"
              disabled={saving}
            />
            {validationErrors.canonical_label && (
              <p className="text-xs text-red-500">{validationErrors.canonical_label}</p>
            )}
          </div>

          {/* module */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium leading-none">
              SAP Module <span className="text-red-500">*</span>
            </label>
            <Select
              value={form.module}
              onValueChange={(v) => field('module', v as SapModule)}
              disabled={saving}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select module" />
              </SelectTrigger>
              <SelectContent>
                {MODULES.map((m) => (
                  <SelectItem key={m} value={m}>{m}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {validationErrors.module && (
              <p className="text-xs text-red-500">{validationErrors.module}</p>
            )}
          </div>

          {/* source_system */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium leading-none">Source system</label>
            <Input
              value={form.source_system}
              onChange={(e) => field('source_system', e.target.value)}
              placeholder="s4h"
              disabled={saving}
            />
          </div>

          {/* synonyms */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium leading-none">Synonyms</label>
            <Input
              value={form.synonyms}
              onChange={(e) => field('synonyms', e.target.value)}
              placeholder="e.g. sales, revenue, billing"
              disabled={saving}
            />
          </div>

          {/* context_clues */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium leading-none">Context clues</label>
            <Input
              value={form.context_clues}
              onChange={(e) => field('context_clues', e.target.value)}
              placeholder="ej: orders, billing, sales"
              disabled={saving}
            />
          </div>

          {/* disambiguation_hint */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium leading-none">Disambiguation hint</label>
            <textarea
              value={form.disambiguation_hint}
              onChange={(e) => field('disambiguation_hint', e.target.value)}
              placeholder="Describe when to use this term…"
              rows={2}
              disabled={saving}
              className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-none"
            />
          </div>

          {/* description */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium leading-none">Description</label>
            <textarea
              value={form.description}
              onChange={(e) => field('description', e.target.value)}
              placeholder="Describe the term in a business context…"
              rows={2}
              disabled={saving}
              className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-none"
            />
          </div>

          {/* API error */}
          {error && (
            <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={() => void handleSave()} disabled={saving}>
            {saving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Saving…
              </>
            ) : (
              'Save'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Delete Confirm Dialog (T18) ──────────────────────────────────────────────

interface DeleteDialogProps {
  open: boolean
  entry: PhraseEntry | null
  onClose: () => void
  onDeleted: (id: string) => void
}

function DeleteDialog({ open, entry, onClose, onDeleted }: DeleteDialogProps) {
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setError(null)
      setDeleting(false)
    }
  }, [open])

  async function handleDelete() {
    if (!entry?.id) return
    setDeleting(true)
    setError(null)
    try {
      await deletePhrase(entry.id)
      onDeleted(entry.id)
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : typeof err === 'object' && err !== null && 'response' in err
            ? (err as { response?: { data?: { detail?: string; message?: string } } }).response?.data?.detail ??
              (err as { response?: { data?: { detail?: string; message?: string } } }).response?.data?.message ??
              'Failed to delete'
            : 'Failed to delete'
      setError(msg)
      setDeleting(false)
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={(v) => { if (!v && !deleting) onClose() }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete phrase?</AlertDialogTitle>
          <AlertDialogDescription>
            You are about to delete <span className="font-semibold text-foreground">"{entry?.canonical_label}"</span>.
            This action cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>

        {error && (
          <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={deleting} onClick={onClose}>
            Cancel
          </AlertDialogCancel>
          <button
            onClick={() => void handleDelete()}
            disabled={deleting}
            className="inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 bg-red-600 text-white hover:bg-red-700 h-10 px-4 py-2"
          >
            {deleting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Deleting…
              </>
            ) : (
              'Delete'
            )}
          </button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

// ── Main Page (T16) ──────────────────────────────────────────────────────────

type ModuleFilter = SapModule | 'All'

export default function DictionaryPage() {
  const [phrases, setPhrases] = useState<PhraseEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [moduleFilter, setModuleFilter] = useState<ModuleFilter>('All')

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editEntry, setEditEntry] = useState<PhraseEntry | null>(null)

  // Delete state
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteEntry, setDeleteEntry] = useState<PhraseEntry | null>(null)

  // Disappearing rows animation
  const [deletingId, setDeletingId] = useState<string | null>(null)

  async function loadPhrases() {
    setLoading(true)
    try {
      const data = await listPhrases()
      setPhrases(data)
    } catch {
      toast.error('Failed to load dictionary')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadPhrases()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function openCreate() {
    setEditEntry(null)
    setDialogOpen(true)
  }

  function openEdit(entry: PhraseEntry) {
    setEditEntry(entry)
    setDialogOpen(true)
  }

  function openDelete(entry: PhraseEntry) {
    setDeleteEntry(entry)
    setDeleteOpen(true)
  }

  function handleSaved() {
    setDialogOpen(false)
    void loadPhrases()
    toast.success('Phrase saved')
  }

  function handleDeleted(id: string) {
    setDeleteOpen(false)
    setDeletingId(id)
    setTimeout(() => {
      setPhrases((prev) => prev.filter((p) => p.id !== id))
      setDeletingId(null)
    }, 300)
    toast.success('Phrase deleted')
  }

  const filtered =
    moduleFilter === 'All'
      ? phrases
      : phrases.filter((p) => p.module === moduleFilter)

  const filterOptions: ModuleFilter[] = ['All', ...MODULES]

  return (
    <div className="p-8 max-w-5xl">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Semantic Dictionary</h1>
          <p className="text-sm text-gray-500 mt-1">
            Manage business terms in natural language that guide semantic resolution.
          </p>
        </div>
        <Button onClick={openCreate} className="flex items-center gap-2 shrink-0">
          <Plus className="h-4 w-4" />
          New phrase
        </Button>
      </div>

      {/* Module filter pills */}
      <div className="flex flex-wrap gap-2 mb-5">
        {filterOptions.map((m) => (
          <button
            key={m}
            onClick={() => setModuleFilter(m)}
            className={`px-3 py-1 rounded-full text-sm font-medium transition-colors border ${
              moduleFilter === m
                ? 'bg-gray-900 text-white border-gray-900'
                : 'bg-white text-gray-600 border-gray-200 hover:border-gray-400'
            }`}
          >
            {m}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Term</TableHead>
              <TableHead className="w-24">Module</TableHead>
              <TableHead className="w-56">Synonyms</TableHead>
              <TableHead className="w-64">Hint</TableHead>
              <TableHead className="w-24 text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} />)
            ) : filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-gray-500 py-12">
                  No phrases found{moduleFilter !== 'All' ? ` for module ${moduleFilter}` : ''}.
                </TableCell>
              </TableRow>
            ) : (
              filtered.map((phrase) => (
                <TableRow
                  key={phrase.id ?? phrase.canonical_label}
                  className={`transition-all duration-300 ${
                    deletingId === phrase.id ? 'opacity-0 scale-95' : 'opacity-100'
                  }`}
                >
                  <TableCell className="font-medium">{phrase.canonical_label}</TableCell>
                  <TableCell>
                    <ModuleBadge module={phrase.module} />
                  </TableCell>
                  <TableCell className="text-gray-500 text-sm">
                    {trunc(phrase.synonyms, 40)}
                  </TableCell>
                  <TableCell className="text-gray-500 text-sm">
                    {trunc(phrase.disambiguation_hint, 50)}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => openEdit(phrase)}
                        title="Editar"
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => openDelete(phrase)}
                        title="Delete"
                        className="text-red-500 hover:text-red-700 hover:bg-red-50"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Dialogs */}
      <PhraseDialog
        open={dialogOpen}
        entry={editEntry}
        onClose={() => setDialogOpen(false)}
        onSaved={handleSaved}
      />

      <DeleteDialog
        open={deleteOpen}
        entry={deleteEntry}
        onClose={() => setDeleteOpen(false)}
        onDeleted={handleDeleted}
      />

      {/* Toasts */}
    </div>
  )
}
