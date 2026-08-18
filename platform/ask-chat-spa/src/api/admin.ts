/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import axios from 'axios'

export interface Workspace {
  id: string
  slug: string
  name: string
  description?: string
}

export async function listWorkspaces(): Promise<Workspace[]> {
  const { data } = await axios.get<Workspace[]>('/api/admin/workspaces')
  return data
}
