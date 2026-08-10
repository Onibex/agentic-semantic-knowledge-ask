/**
 * Session-wide active-workspace store.
 *
 * Picked once via the AppLayout top-bar selector, persisted to localStorage so
 * a browser refresh restores the same scope. Consumed by the views that load
 * YAMLs (GraphPage, SemanticKnowledgePage, MergePage, HistoryPage) — each calls
 * `listYamls({ workspace: activeWorkspaceId })` so the SPA never shows YAMLs
 * outside the admin's chosen workspace.
 *
 * The chat backend already enforces `workspace_id` on `/v1/query`; this store
 * gives the admin UI the same scoping model.
 */
import { create } from 'zustand'

import { listWorkspaces } from '../api/client'
import type { Workspace } from '../api/types'

const STORAGE_KEY = 'ask-admin-spa:activeWorkspaceId'

function readPersisted(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY) || null
  } catch {
    return null
  }
}

function writePersisted(id: string | null): void {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id)
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* private mode — silent */
  }
}

interface WorkspaceState {
  available: Workspace[]
  activeWorkspaceId: string | null
  loading: boolean
  error: string | null

  /** Resolved Workspace object for `activeWorkspaceId`, or null. */
  active: () => Workspace | null
  loadWorkspaces: () => Promise<void>
  setActive: (workspaceId: string | null) => void
}

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  available: [],
  activeWorkspaceId: readPersisted(),
  loading: false,
  error: null,

  active() {
    const id = get().activeWorkspaceId
    if (!id) return null
    return get().available.find((w) => w.id === id || w.slug === id) ?? null
  },

  async loadWorkspaces() {
    if (get().loading) return
    set({ loading: true, error: null })
    try {
      const list = await listWorkspaces()
      set({ available: list, loading: false })

      // Heal stale selection: if the persisted id no longer exists, drop it.
      const current = get().activeWorkspaceId
      if (current && !list.some((w) => w.id === current || w.slug === current)) {
        writePersisted(null)
        set({ activeWorkspaceId: null })
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load workspaces'
      set({ loading: false, error: msg })
    }
  },

  setActive(workspaceId) {
    writePersisted(workspaceId)
    set({ activeWorkspaceId: workspaceId })
  },
}))
