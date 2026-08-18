/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import axios from 'axios'

export type Mode = 'flash' | 'precise' | 'smart'
export type Env = 'dev' | 'prod'

// ── Error extraction ──────────────────────────────────────────────────────────
// The orchestrator returns structured errors: FastAPI wraps our ErrorResponse in
// `{ detail: { error_code, message, trace_id } }` (e.g. WORKSPACE_HAS_NO_ENTITIES
// when a workspace has no Data Products published to the queried env). Plain
// HTTPExceptions send `{ detail: "text" }`, and pydantic validation sends
// `{ detail: [{ msg, loc }] }`. Surface the human message from any of these
// instead of axios's generic "Request failed with status code 400".
export function extractApiError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (Array.isArray(detail)) {
      const msgs = detail.map((d) => (d as { msg?: string })?.msg).filter(Boolean)
      if (msgs.length) return msgs.join('; ')
    }
    if (detail && typeof detail === 'object') {
      const m = (detail as { message?: string }).message
      if (typeof m === 'string' && m.trim()) return m
    }
    return err.message
  }
  return err instanceof Error ? err.message : 'Unknown error'
}

// ── /v1/query ────────────────────────────────────────────────────────────────

export interface QueryRequest {
  question: string
  workspace_id: string
  mode: Mode
  env: Env
  session_id?: string | null
  conversation_history?: ConversationTurn[] | null
}

export interface ConversationTurn {
  role: 'user' | 'assistant'
  content: string
}

// Per-request token accounting produced by the orchestrator's TokenTracker
// (`ask_llm_gateway.infrastructure.token_tracker`). Mirrors the Pydantic
// `TokensBreakdown` in `ask_orchestrator/models/responses.py` — every LLM call
// the request made, tagged by pipeline phase.
export interface TokenRecord {
  phase: string
  model: string
  input_tokens: number
  output_tokens: number
  total_tokens: number
  timestamp_utc: string
  query_id?: string | null
}

export interface TokensPhase {
  calls: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
}

export interface TokensBreakdown {
  total_calls: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  by_phase?: Record<string, TokensPhase>
  records?: TokenRecord[]
}

export interface QueryResponse {
  answer: string
  sql?: string | null
  rows?: Record<string, unknown>[] | null
  mode_used?: string
  macro_intent?: string
  citations?: unknown[]
  tokens_used?: number | null
  tokens_breakdown?: TokensBreakdown | null
  trace_id?: string
}

export async function postQuery(req: QueryRequest): Promise<QueryResponse> {
  const { data } = await axios.post<QueryResponse>('/api/orchestrator/query', req)
  return data
}

// ── /v1/artifact ─────────────────────────────────────────────────────────────

export interface ArtifactRequest {
  name: string
  artifact_type: string
  format: string
  purpose: string
  data_focus: string
  mode: Mode
  env: Env
  workspace_id: string
  sql_override?: string | null
}

export interface ArtifactDataset {
  name: string
  sql: string
  rows: Record<string, unknown>[]
  error?: string | null
}

export interface ArtifactResponse {
  name: string
  artifact_type: string
  format: string
  content: string
  sql?: string | null
  rows?: Record<string, unknown>[] | null
  datasets?: ArtifactDataset[] | null
  data_error?: string | null
  trace_id?: string
  tokens_used?: number | null
}

export async function postArtifact(req: ArtifactRequest): Promise<ArtifactResponse> {
  const { data } = await axios.post<ArtifactResponse>('/api/orchestrator/artifact', req)
  return data
}

// ── /v1/title ─────────────────────────────────────────────────────────────────

export interface TitleRequest {
  question: string
}

export interface TitleResponse {
  title: string
}

export async function generateChatTitle(req: TitleRequest): Promise<TitleResponse> {
  const { data } = await axios.post<TitleResponse>('/api/orchestrator/title', req)
  return data
}

// ── /v1/health ────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: string
}

export async function getHealth(): Promise<HealthResponse> {
  const { data } = await axios.get<HealthResponse>('/api/orchestrator/health')
  return data
}
