/**
 * Domain-publish gate — mirror of the backend `_needs_publish`
 * (ask-admin-api/routers/business_domains.py) so the SPA checklist defaults
 * match exactly what the server will publish. The server re-checks
 * authoritatively, so any drift here only changes the *default selection*, never
 * correctness (a selected-but-up-to-date DP is reported `skipped`).
 */
import type { DataProductLifecycle } from '../api/types'

export interface PublishGate {
  /** True when the DP has changes pending for `env` (will actually publish). */
  eligible: boolean
  /** Human reason it would be skipped, when not eligible. */
  skipReason: string | null
}

export function publishGate(
  lc: DataProductLifecycle | undefined,
  env: 'dev' | 'prod',
): PublishGate {
  if (env === 'dev') {
    if (!lc || !lc.dev_published || lc.dev_published.sha !== lc.main_sha) {
      return { eligible: true, skipReason: null }
    }
    return { eligible: false, skipReason: 'already up to date with working' }
  }
  // prod — needs a dev publish first, and prod must be behind that dev version.
  if (!lc || !lc.dev_published) return { eligible: false, skipReason: 'needs a dev publish first' }
  if (lc.prod_published && lc.prod_published.sha === lc.dev_published.sha) {
    return { eligible: false, skipReason: 'already up to date with dev' }
  }
  return { eligible: true, skipReason: null }
}

export interface PublishCandidate extends PublishGate {
  entityId: string
  /** Display name (falls back to entityId at the call site if unknown). */
  name: string
}

/**
 * Build the ordered candidate list for a domain publish: every member with its
 * gate verdict + display name, preserving membership order. The dialog renders
 * the eligible ones as a checklist and summarises the rest as "will be skipped".
 */
export function buildPublishCandidates(
  memberIds: string[],
  lifecycleById: Map<string, DataProductLifecycle>,
  env: 'dev' | 'prod',
  nameById?: Map<string, string>,
): PublishCandidate[] {
  return memberIds.map((entityId) => ({
    entityId,
    name: nameById?.get(entityId) ?? entityId,
    ...publishGate(lifecycleById.get(entityId), env),
  }))
}
