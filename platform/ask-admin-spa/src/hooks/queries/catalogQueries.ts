/**
 * TanStack Query hooks for the DataProduct lifecycle / catalog.
 *
 * Lifecycle state (status / version / dev|prod publish records / pending
 * conflicts / business-domain membership) used to be fetched into FIVE
 * independent `useState` copies (DetailPanel, DomainCanvasPage,
 * SemanticKnowledgePage, HistoryPage, WorkspaceHome). A mutation in one view
 * refreshed at most its own copy, leaving every other view stale until a route
 * change or manual refresh.
 *
 * These hooks make it ONE shared cache that every view subscribes to. Any
 * mutation that changes lifecycle (publish dev/prod, edit save, AI enrich,
 * conflict resolve, add/remove from domain, create, restore) calls
 * {@link invalidateLifecycle}, and all subscribers re-render automatically.
 *
 * `invalidateLifecycle` uses the singleton queryClient so it also works inside
 * the zustand stores (editorStore / mergeStore / historyStore), which run
 * outside React and can't call `useQueryClient`.
 */

import { useQuery, type UseQueryOptions } from '@tanstack/react-query';

import { getDataProductCatalog, getDataProductLifecycle } from '../../api/client';
import type { DataProductLifecycle, DataProductStatus } from '../../api/types';
import { queryClient } from '../../lib/queryClient';

type CatalogOpts = { workspaceId?: string | null; status?: DataProductStatus | null };

// ── Query key registry (single source of truth for invalidation) ──────────

export const catalogKeys = {
  all: ['catalog'] as const,
  list: (opts?: CatalogOpts) => [...catalogKeys.all, 'list', opts ?? {}] as const,
  lifecycle: (id: string) => [...catalogKeys.all, 'lifecycle', id] as const,
};

// ── Queries ────────────────────────────────────────────────────────────────

export function useDataProductCatalog(
  opts?: CatalogOpts,
  options?: Omit<UseQueryOptions<DataProductLifecycle[]>, 'queryKey' | 'queryFn'>,
) {
  return useQuery({
    queryKey: catalogKeys.list(opts),
    queryFn: () => getDataProductCatalog(opts),
    ...options,
  });
}

export function useDataProductLifecycle(
  id: string | null | undefined,
  options?: Omit<
    UseQueryOptions<DataProductLifecycle | null>,
    'queryKey' | 'queryFn' | 'enabled'
  >,
) {
  return useQuery({
    queryKey: catalogKeys.lifecycle(id ?? ''),
    queryFn: () => getDataProductLifecycle(id as string),
    enabled: Boolean(id),
    ...options,
  });
}

// ── Invalidation ─────────────────────────────────────────────────────────

/**
 * Invalidate every catalog + per-entity lifecycle query. Call from any mutation
 * that changes status / version / publish state / conflicts / domain membership.
 * Safe to call from React components and from zustand stores (singleton client).
 */
export function invalidateLifecycle(): void {
  void queryClient.invalidateQueries({ queryKey: catalogKeys.all });
}

/**
 * Coalesce a burst of lifecycle invalidations into a single refetch. Use on
 * high-frequency interactions (rapid add/remove-from-domain "+" clicks) where
 * the full `/admin/catalog` refetch would otherwise fire once per click and
 * thrash the network. The membership chip derives from the BD object the
 * mutation already returns, so the catalog refetch only needs to land once the
 * burst settles. Other (one-shot) mutations keep calling `invalidateLifecycle`.
 */
let _debounceTimer: ReturnType<typeof setTimeout> | null = null;
export function invalidateLifecycleDebounced(delayMs = 800): void {
  if (_debounceTimer) clearTimeout(_debounceTimer);
  _debounceTimer = setTimeout(() => {
    _debounceTimer = null;
    invalidateLifecycle();
  }, delayMs);
}
