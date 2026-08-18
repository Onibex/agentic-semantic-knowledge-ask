/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { create } from 'zustand';
import {
  ingestSapJson,
  getConflicts,
  getPendingConflictsWorkspace,
  resolveConflict,
  resolveConflictsBulk,
} from '../api/client';
import { invalidateLifecycle } from '../hooks/queries/catalogQueries';
import { useGraphStore } from './graphStore';
import { useAuthStore } from './authStore';
import type { MergeResult, ConflictBlock, ConflictDecision } from '../api/types';

interface MergeStore {
  ingestJson: string;
  ingestResult: MergeResult | null;
  ingestLoading: boolean;
  ingestError: string | null;

  conflicts: ConflictBlock[];
  conflictsLoading: boolean;
  selectedConflictId: string | null;
  resolving: boolean;
  resolveError: string | null;

  setIngestJson(json: string): void;
  ingest(): Promise<void>;
  fetchAllConflicts(yamlIds: string[]): Promise<void>;
  loadPendingConflicts(): Promise<void>;
  selectConflict(id: string | null): void;
  resolve(yamlId: string, conflictId: string, decision: ConflictDecision): Promise<void>;
  resolveBulk(
    yamlId: string,
    resolutions: { conflict_id: string; decision: ConflictDecision }[],
  ): Promise<void>;
}

export const useMergeStore = create<MergeStore>((set, get) => ({
  ingestJson: '',
  ingestResult: null,
  ingestLoading: false,
  ingestError: null,

  conflicts: [],
  conflictsLoading: false,
  selectedConflictId: null,
  resolving: false,
  resolveError: null,

  setIngestJson(json: string) {
    set({ ingestJson: json });
  },

  async ingest() {
    const { ingestJson } = get();
    const authorEmail = useAuthStore.getState().user?.email ?? '';
    set({ ingestLoading: true, ingestError: null, ingestResult: null });
    try {
      const payload = JSON.parse(ingestJson) as Record<string, unknown>;
      const result = await ingestSapJson(payload, authorEmail);
      set({ ingestResult: result, ingestLoading: false });

      // Collect yaml_ids involved: from conflicts + from rawNodes that already have conflicts
      const involvedFromResult = result.conflicts.map((c) => c.yaml_id);
      const rawNodes = useGraphStore.getState().rawNodes;
      const involvedFromNodes = rawNodes
        .filter((n) => Array.isArray(n.meta.conflicts) && n.meta.conflicts.length > 0)
        .map((n) => n.id);
      const allIds = [...new Set([...involvedFromResult, ...involvedFromNodes])];
      await get().fetchAllConflicts(allIds);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      set({ ingestLoading: false, ingestError: msg });
    }
  },

  async fetchAllConflicts(yamlIds: string[]) {
    if (yamlIds.length === 0) return;
    set({ conflictsLoading: true });
    try {
      const results = await Promise.all(yamlIds.map((id) => getConflicts(id)));
      const flat = results.flat();
      set({ conflicts: flat, conflictsLoading: false });
    } catch {
      set({ conflictsLoading: false });
    }
  },

  async loadPendingConflicts() {
    // Workspace-wide pending inbox — called on /merge mount so the list
    // shows on F5 / cold load, not just after a fresh ingest.
    set({ conflictsLoading: true });
    try {
      const all = await getPendingConflictsWorkspace();
      set({ conflicts: all, conflictsLoading: false });
    } catch {
      set({ conflictsLoading: false });
    }
  },

  selectConflict(id: string | null) {
    set({ selectedConflictId: id, resolveError: null });
  },

  async resolve(yamlId: string, conflictId: string, decision: ConflictDecision) {
    const authorEmail = useAuthStore.getState().user?.email ?? '';
    set({ resolving: true, resolveError: null });
    try {
      const updated = await resolveConflict(yamlId, conflictId, decision, authorEmail);
      // Refresh conflicts for this yaml
      const freshConflicts = await getConflicts(yamlId);
      const { conflicts } = get();
      const merged = conflicts.filter((c) => c.yaml_id !== yamlId).concat(freshConflicts);
      set({ conflicts: merged, resolving: false });
      // Swap the updated node into the graph (no full refetch).
      useGraphStore.getState().replaceNode(updated);
      // Resolving changes pending_conflicts (and maybe status) → refresh the
      // catalog badge/filter + every lifecycle view, even on partial resolution.
      invalidateLifecycle();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      set({ resolving: false, resolveError: msg });
    }
  },

  async resolveBulk(
    yamlId: string,
    resolutions: { conflict_id: string; decision: ConflictDecision }[],
  ) {
    if (resolutions.length === 0) return;
    const authorEmail = useAuthStore.getState().user?.email ?? '';
    set({ resolving: true, resolveError: null });
    try {
      const updated = await resolveConflictsBulk(yamlId, resolutions, authorEmail);
      const freshConflicts = await getConflicts(yamlId);
      const { conflicts } = get();
      const merged = conflicts.filter((c) => c.yaml_id !== yamlId).concat(freshConflicts);
      set({ conflicts: merged, resolving: false });
      useGraphStore.getState().replaceNode(updated);
      invalidateLifecycle();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      set({ resolving: false, resolveError: msg });
    }
  },
}));
