/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { create } from 'zustand';
import { getYamlHistory, getYamlDiff, restoreYaml } from '../api/client';
import { invalidateLifecycle } from '../hooks/queries/catalogQueries';
import { useGraphStore } from './graphStore';
import { useAuthStore } from './authStore';
import type { CommitEntry, DiffResult, HistoryBranch } from '../api/types';

const PER_PAGE = 20;

interface HistoryStore {
  selectedYamlId: string | null;
  historyBranch: HistoryBranch;
  commits: CommitEntry[];
  totalCount: number;
  currentPage: number;
  loading: boolean;
  fromSha: string | null;
  toSha: string | null;
  diffResult: DiffResult | null;
  diffLoading: boolean;
  restoreTarget: string | null;
  restoreDialogOpen: boolean;
  restoring: boolean;
  restoreError: string | null;

  selectYaml(id: string): Promise<void>;
  setHistoryBranch(branch: HistoryBranch): Promise<void>;
  loadMore(): Promise<void>;
  setFromSha(sha: string | null): void;
  setToSha(sha: string | null): void;
  loadDiff(): Promise<void>;
  openRestoreDialog(sha: string): void;
  closeRestoreDialog(): void;
  confirmRestore(reason?: string): Promise<void>;
}

export const useHistoryStore = create<HistoryStore>((set, get) => ({
  selectedYamlId: null,
  historyBranch: 'working',
  commits: [],
  totalCount: 0,
  currentPage: 1,
  loading: false,
  fromSha: null,
  toSha: null,
  diffResult: null,
  diffLoading: false,
  restoreTarget: null,
  restoreDialogOpen: false,
  restoring: false,
  restoreError: null,

  async selectYaml(id: string) {
    // Selecting a new file resets to the Working tab (UX_CHANGES §4.4 default).
    const branch: HistoryBranch = 'working';
    set({
      selectedYamlId: id,
      historyBranch: branch,
      commits: [],
      totalCount: 0,
      currentPage: 1,
      fromSha: null,
      toSha: null,
      diffResult: null,
      loading: true,
    });
    try {
      const resp = await getYamlHistory(id, 1, PER_PAGE, branch);
      set({
        commits: resp.commits,
        totalCount: resp.total_count,
        currentPage: 1,
        loading: false,
      });
    } catch {
      set({ loading: false });
    }
  },

  async setHistoryBranch(branch: HistoryBranch) {
    const { selectedYamlId, historyBranch } = get();
    if (branch === historyBranch) return;
    set({
      historyBranch: branch,
      commits: [],
      totalCount: 0,
      currentPage: 1,
      fromSha: null,
      toSha: null,
      diffResult: null,
      loading: selectedYamlId !== null,
    });
    if (!selectedYamlId) return;
    try {
      const resp = await getYamlHistory(selectedYamlId, 1, PER_PAGE, branch);
      set({ commits: resp.commits, totalCount: resp.total_count, currentPage: 1, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  async loadMore() {
    const { selectedYamlId, currentPage, commits, loading, historyBranch } = get();
    if (!selectedYamlId || loading) return;
    const nextPage = currentPage + 1;
    set({ loading: true });
    try {
      const resp = await getYamlHistory(selectedYamlId, nextPage, PER_PAGE, historyBranch);
      set({
        commits: [...commits, ...resp.commits],
        totalCount: resp.total_count,
        currentPage: nextPage,
        loading: false,
      });
    } catch {
      set({ loading: false });
    }
  },

  setFromSha(sha: string | null) {
    set({ fromSha: sha, diffResult: null });
  },

  setToSha(sha: string | null) {
    set({ toSha: sha, diffResult: null });
  },

  async loadDiff() {
    const { selectedYamlId, fromSha, toSha } = get();
    if (!selectedYamlId || !fromSha || !toSha) return;
    set({ diffLoading: true, diffResult: null });
    try {
      const result = await getYamlDiff(selectedYamlId, fromSha, toSha);
      set({ diffResult: result, diffLoading: false });
    } catch {
      set({ diffLoading: false });
    }
  },

  openRestoreDialog(sha: string) {
    set({ restoreTarget: sha, restoreDialogOpen: true, restoreError: null });
  },

  closeRestoreDialog() {
    set({ restoreDialogOpen: false, restoreTarget: null, restoreError: null });
  },

  async confirmRestore(reason?: string) {
    const { selectedYamlId, restoreTarget } = get();
    if (!selectedYamlId || !restoreTarget) return;
    const authorEmail = useAuthStore.getState().user?.email ?? '';
    set({ restoring: true, restoreError: null });
    try {
      const updated = await restoreYaml(selectedYamlId, restoreTarget, authorEmail, reason);
      set({ restoring: false, restoreDialogOpen: false, restoreTarget: null });
      // Refresh this file's history + swap the node in the graph (no full refetch).
      await get().selectYaml(selectedYamlId);
      useGraphStore.getState().replaceNode(updated);
      invalidateLifecycle();  // restore bumps the working version; refresh chips

    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      set({ restoring: false, restoreError: msg });
    }
  },
}));
