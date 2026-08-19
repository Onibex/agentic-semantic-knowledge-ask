/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { z } from 'zod'

/**
 * Zod schemas for the upcoming Workspace + Data Product + Organization features.
 *
 * Single source of truth for FE form validation. Pair with react-hook-form:
 *
 *   const form = useForm<WorkspaceFormValues>({
 *     resolver: zodResolver(workspaceSchema),
 *   })
 *
 * Once the backend Pydantic models for these entities land, regenerate this
 * file from ``model.model_json_schema()`` so FE + BE validation stay in sync.
 */

// ── Roles (informational only — Curator / Reviewer / Viewer) ─────────────

export const roleSchema = z.enum(['curator', 'reviewer', 'viewer'])

// ── Workspace ─────────────────────────────────────────────────────────────

export const workspaceSchema = z.object({
  name: z
    .string()
    .min(2, 'Workspace name must be at least 2 characters')
    .max(80, 'Workspace name must be at most 80 characters'),
  objective: z
    .string()
    .min(10, 'Objective must explain the purpose of this workspace (min 10 chars)')
    .max(500),
  description: z.string().max(2000).optional().default(''),
  data_product_ids: z.array(z.string().min(1)).default([]),
  roles: z
    .array(
      z.object({
        email: z.string().email(),
        role: roleSchema,
      }),
    )
    .default([]),
})

export type WorkspaceFormValues = z.infer<typeof workspaceSchema>

// ── Business Domain ─────────────────────────────────────────────────────────
// (Formerly "Data Product" — UX_CHANGES audit, Iter 1. Members are
//  data_product_ids, was entity_ids.)

export const businessDomainSchema = z.object({
  id: z
    .string()
    .min(2)
    .regex(/^[a-z0-9_]+$/, 'Use lowercase letters, digits and underscores only'),
  name: z.string().min(2).max(80),
  description: z.string().min(10).max(2000),
  data_product_ids: z.array(z.string().min(1)).default([]),
})

export type BusinessDomainFormValues = z.infer<typeof businessDomainSchema>

// ── Organization (Requirement #3) ────────────────────────────────────────

export const organizationSchema = z.object({
  company_name: z.string().min(2).max(120),
  sap_version: z.string().min(2).max(120),
  sap_core_bases: z.array(z.string().min(1)).default([]),
  url: z.string().url().or(z.literal('')).default(''),
})

export type OrganizationFormValues = z.infer<typeof organizationSchema>
