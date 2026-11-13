/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import type { Clarification, Env, TokensBreakdown } from '@/api/orchestrator'

export interface MessageMeta {
  sql?: string | null
  // Where the SQL ran. The environment picker is global, so one chat can hold
  // answers from dev and from prod, and a follow-up reuses only the SQL of its own.
  env?: Env
  rows?: Record<string, unknown>[] | null
  mode_used?: string
  macro_intent?: string
  trace_id?: string
  // Per-request token accounting. Carried from QueryResponse so the thread can
  // render a per-phase expander next to the mode badge.
  tokens_used?: number | null
  tokens_breakdown?: TokensBreakdown | null
  // Set when the agent asked before answering. Sent back with this message in
  // the history, so the next message is read as the reply.
  clarification?: Clarification | null
  // Facts the orchestrator computed from every row of the result. Never shown:
  // sent back with this message in the history, so a follow-up is checked
  // against the whole result and not only against the answer's text.
  result_facts?: string | null
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  meta?: MessageMeta
}
