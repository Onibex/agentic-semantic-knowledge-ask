/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * TanStack Query hooks for YAML workspace operations.
 *
 * These wrap the existing axios-based API client and provide:
 *  - Automatic cache, retry, dedupe
 *  - Optimistic updates / cache invalidation on mutations
 *  - Loading + error states per consumer (no manual zustand fetch flags)
 *
 * Pattern for new features: prefer these hooks over manual fetch+setState.
 * Existing zustand stores (graphStore, historyStore, mergeStore) continue
 * to work — migrate them incrementally as touched.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from '@tanstack/react-query'

import {
  getYaml,
  getYamlHistory,
  listYamls,
  restoreYaml,
  updateYaml,
} from '../../api/client'
import type {
  HistoryResponse,
  YAMLLayer,
  YAMLNode,
  YAMLNodeSummary,
  YAMLUpdateRequest,
} from '../../api/types'

// ── Query key registry (single source of truth for invalidation) ──────────

export const yamlKeys = {
  all: ['yamls'] as const,
  lists: () => [...yamlKeys.all, 'list'] as const,
  list: (layer?: YAMLLayer) => [...yamlKeys.lists(), { layer }] as const,
  details: () => [...yamlKeys.all, 'detail'] as const,
  detail: (id: string) => [...yamlKeys.details(), id] as const,
  history: (id: string) => [...yamlKeys.detail(id), 'history'] as const,
  historyPage: (id: string, page: number, pageSize: number) =>
    [...yamlKeys.history(id), { page, pageSize }] as const,
}

// ── Queries ──────────────────────────────────────────────────────────────

export function useYamlList(
  layer?: YAMLLayer,
  options?: Omit<UseQueryOptions<YAMLNodeSummary[]>, 'queryKey' | 'queryFn'>,
) {
  return useQuery({
    queryKey: yamlKeys.list(layer),
    queryFn: () => listYamls(layer),
    ...options,
  })
}

export function useYamlNode(
  id: string | null | undefined,
  options?: Omit<UseQueryOptions<YAMLNode>, 'queryKey' | 'queryFn' | 'enabled'>,
) {
  return useQuery({
    queryKey: yamlKeys.detail(id ?? ''),
    queryFn: () => getYaml(id as string),
    enabled: Boolean(id),
    ...options,
  })
}

export function useYamlHistory(
  id: string | null | undefined,
  page = 1,
  pageSize = 20,
  options?: Omit<UseQueryOptions<HistoryResponse>, 'queryKey' | 'queryFn' | 'enabled'>,
) {
  return useQuery({
    queryKey: yamlKeys.historyPage(id ?? '', page, pageSize),
    queryFn: () => getYamlHistory(id as string, page, pageSize),
    enabled: Boolean(id),
    ...options,
  })
}

// ── Mutations ────────────────────────────────────────────────────────────

export function useUpdateYamlMutation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, req }: { id: string; req: YAMLUpdateRequest }) =>
      updateYaml(id, req),
    onSuccess: (node) => {
      // Refresh the detail cache + invalidate the list (alias / name may have changed).
      qc.setQueryData(yamlKeys.detail(node.id), node)
      void qc.invalidateQueries({ queryKey: yamlKeys.lists() })
      void qc.invalidateQueries({ queryKey: yamlKeys.history(node.id) })
    },
  })
}

export function useRestoreYamlMutation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      sha,
      authorEmail,
      reason,
    }: {
      id: string
      sha: string
      authorEmail: string
      reason?: string
    }) => restoreYaml(id, sha, authorEmail, reason),
    onSuccess: (node) => {
      qc.setQueryData(yamlKeys.detail(node.id), node)
      void qc.invalidateQueries({ queryKey: yamlKeys.lists() })
      void qc.invalidateQueries({ queryKey: yamlKeys.history(node.id) })
    },
  })
}
