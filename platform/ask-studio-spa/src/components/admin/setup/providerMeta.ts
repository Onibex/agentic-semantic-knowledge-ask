/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * Provider brand colours — the single source shared by the Setup cards and the
 * embedder drawer so both read as the same visual family as ASK Setup. Glyphs
 * live in ``ProviderLogo``; this map only carries the tile accent colour.
 */
export const PROVIDER_COLOR: Record<string, string> = {
  openai: '#10a37f',
  anthropic: '#d97757',
  bedrock: '#f0972a',
  gemini: '#4285f4',
  vertex_ai: '#34a853',
  azure: '#0078d4',
  databricks: '#ee4b2e',
  huggingface: '#e6a817',
  sap_aicore: '#0aa8e0',
  opensearch: '#0ea5e9',
}

export function providerColor(id: string): string {
  return PROVIDER_COLOR[id] ?? '#64748b'
}
