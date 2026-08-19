/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import type { DataProductLifecycle } from '@/api/types'

/**
 * Pure derivation for the Deployment & Versions panel (UX_CHANGES audit §6.3).
 * Kept in its own module (no React) so the gating logic is unit-testable and
 * the component file only exports a component (react-refresh rule).
 */

export type DevState = 'never' | 'current' | 'behind-working'
export type ProdState = 'waiting-on-dev' | 'never' | 'up-to-date' | 'behind'

export interface DeploymentState {
  workingVersion: number
  workingIsDraft: boolean
  dev: { state: DevState; canPublish: boolean; version: number | null }
  prod: { state: ProdState; canPublish: boolean; version: number | null }
}

export function computeDeploymentState(lc: DataProductLifecycle): DeploymentState {
  const dev = lc.dev_published
  const prod = lc.prod_published

  let devState: DevState
  if (dev === null) devState = 'never'
  else if (dev.sha === lc.main_sha) devState = 'current'
  else devState = 'behind-working'

  let prodState: ProdState
  if (dev === null) prodState = 'waiting-on-dev'
  else if (prod === null) prodState = 'never'
  else if (prod.sha === dev.sha) prodState = 'up-to-date'
  else prodState = 'behind'

  return {
    workingVersion: lc.version,
    workingIsDraft: lc.status === 'In Review',
    dev: { state: devState, canPublish: devState !== 'current', version: dev?.version ?? null },
    prod: {
      state: prodState,
      canPublish: prodState === 'never' || prodState === 'behind',
      version: prod?.version ?? null,
    },
  }
}
