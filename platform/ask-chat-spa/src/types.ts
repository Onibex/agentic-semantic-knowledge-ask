/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import type { TokensBreakdown } from '@/api/orchestrator'

export interface MessageMeta {
  sql?: string | null
  rows?: Record<string, unknown>[] | null
  mode_used?: string
  macro_intent?: string
  trace_id?: string
  // Per-request token accounting. Carried from QueryResponse so the thread can
  // render a per-phase expander next to the mode badge.
  tokens_used?: number | null
  tokens_breakdown?: TokensBreakdown | null
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  meta?: MessageMeta
}
