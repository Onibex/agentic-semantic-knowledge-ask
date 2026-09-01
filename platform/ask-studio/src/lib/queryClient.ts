/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { QueryClient } from '@tanstack/react-query'

/**
 * Shared TanStack Query client.
 *
 * Defaults chosen for an admin SPA over a slow-changing backend:
 *  - staleTime 30s   → don't refetch on every focus / mount within 30 seconds
 *  - gcTime 5min     → keep cached query data for 5 minutes after the last
 *                       consumer unmounts (was cacheTime in v4)
 *  - retry 1         → one retry on network blip; user can re-trigger manually
 *  - refetchOnWindowFocus false — admin work doesn't need aggressive refresh
 *
 * Per-query overrides are still possible: pass `staleTime: Infinity` for
 * data that never changes within a session (e.g. JSON Schema), or a shorter
 * staleTime for fast-moving views.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 0,
    },
  },
})
