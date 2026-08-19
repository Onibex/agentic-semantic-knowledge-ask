/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * Hand-authored inline brand marks for the LLM/embedder providers we support.
 *
 * No external assets (CSP-safe, no network) and no icon dependency. Each mark is
 * monochrome and uses ``currentColor`` so the parent tile sets the brand colour.
 * These are recognizable simplified glyphs, not pixel-perfect brand logos — easy
 * to swap for official SVGs later if we get vetted assets.
 */
export function ProviderLogo({ id, size = 18 }: { id: string; size?: number }) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    'aria-hidden': true as const,
  }
  switch (id) {
    case 'openai':
      return (
        <svg {...common} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
          <line x1="12" y1="3" x2="12" y2="21" />
          <line x1="4.2" y1="7.5" x2="19.8" y2="16.5" />
          <line x1="4.2" y1="16.5" x2="19.8" y2="7.5" />
        </svg>
      )
    case 'anthropic':
      return (
        <svg {...common} fill="currentColor">
          <path d="M12 3 5 21h2.7l1.3-3.5h6l1.3 3.5H19L12 3Zm-2.1 12L12 9l2.1 6H9.9Z" />
        </svg>
      )
    case 'bedrock':
      return (
        <svg {...common} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 14.5c4.5 3 11.5 3 16 0" />
          <path d="M16.5 12.8 20 14.2l-1.2 3.4" />
        </svg>
      )
    case 'gemini':
      return (
        <svg {...common} fill="currentColor">
          <path d="M12 2c.45 5.1 2.9 7.55 8 8-5.1.45-7.55 2.9-8 8-.45-5.1-2.9-7.55-8-8 5.1-.45 7.55-2.9 8-8Z" />
        </svg>
      )
    case 'vertex_ai':
      return (
        <svg {...common} fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round">
          <path d="M20 12a8 8 0 1 1-2.3-5.6" />
          <path d="M20.5 12H12" />
        </svg>
      )
    case 'azure':
      return (
        <svg {...common} fill="currentColor">
          <path d="M12 4 4 20h16L12 4Zm0 5 4.2 8.4H7.8L12 9Z" />
        </svg>
      )
    case 'databricks':
      return (
        <svg {...common} fill="currentColor">
          <path d="M4 8 12 4l8 4-8 4Z" opacity=".5" />
          <path d="M4 12 12 8l8 4-8 4Z" opacity=".78" />
          <path d="M4 16 12 12l8 4-8 4Z" />
        </svg>
      )
    case 'huggingface':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" fill="currentColor" opacity=".18" />
          <circle cx="9" cy="10.5" r="1.3" fill="currentColor" />
          <circle cx="15" cy="10.5" r="1.3" fill="currentColor" />
          <path d="M8 14c1.5 1.8 6.5 1.8 8 0" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" />
        </svg>
      )
    case 'sap_aicore':
      return (
        <svg {...common}>
          <text
            x="12"
            y="15.5"
            textAnchor="middle"
            fontFamily="Arial, sans-serif"
            fontSize="8.5"
            fontWeight={800}
            letterSpacing="0.3"
            fill="currentColor"
          >
            SAP
          </text>
        </svg>
      )
    case 'opensearch':
      return (
        <svg {...common} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
          <circle cx="10.5" cy="10.5" r="6" />
          <path d="M20 20l-4.5-4.5" />
        </svg>
      )
    default:
      return (
        <svg {...common}>
          <text x="12" y="15.5" textAnchor="middle" fontSize="9" fontWeight={700} fill="currentColor">
            {(id || '?').slice(0, 2).toUpperCase()}
          </text>
        </svg>
      )
  }
}
