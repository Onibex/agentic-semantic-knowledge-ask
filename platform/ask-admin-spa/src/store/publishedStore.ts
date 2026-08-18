/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * Tiny store of entity ids currently DEPLOYED to the dev runtime registry
 * (``ask-entity-registry-v1-dev`` via the admin-api's /published-ids?env=dev).
 *
 * Used by the Graph page to render per-node "● Published" / "○ Unpublished"
 * chips and to gate the Unpublish action. Refreshed after every Publish /
 * Unpublish so the chip flips instantly without a full catalogue reload.
 *
 * Not derived from `graphStore` because it is global / runtime state — the
 * graph store models the workspace folder (what we COULD publish), this one
 * models what is ACTUALLY deployed. dev is the coarse "is it live" signal:
 * prod requires a dev publish first, so dev-membership implies "live somewhere".
 */
import { create } from 'zustand'

import { getPublishedIds } from '../api/client'

interface PublishedState {
  ids: Set<string>
  loading: boolean
  error: string | null

  /** True if the given entity id is currently in the runtime index. */
  isPublished: (id: string) => boolean
  /** Refresh from the backend. Safe to call repeatedly — coalesces concurrent fetches. */
  refresh: () => Promise<void>
}

let inflight: Promise<void> | null = null

export const usePublishedStore = create<PublishedState>((set, get) => ({
  ids: new Set<string>(),
  loading: false,
  error: null,

  isPublished(id: string) {
    return get().ids.has(id)
  },

  async refresh() {
    if (inflight) return inflight
    set({ loading: true, error: null })
    inflight = (async () => {
      try {
        const list = await getPublishedIds()
        set({ ids: new Set(list), loading: false })
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Failed to load published ids'
        set({ loading: false, error: msg })
      } finally {
        inflight = null
      }
    })()
    return inflight
  },
}))
