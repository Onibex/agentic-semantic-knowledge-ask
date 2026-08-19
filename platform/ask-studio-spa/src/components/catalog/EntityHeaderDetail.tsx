/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * The expanded state of a Semantic Knowledge catalog row: the whole §3.1 entity
 * header, laid out horizontally under the row.
 *
 * Why here and not as columns: `business_process` is the one header key worth a
 * permanent column (owner call) — the rest is reference data you consult on one
 * entity at a time, and a column each would win every width fight in the table.
 * This block is rendered from the catalog row itself (`YAMLNodeSummary` already
 * carries the projection), so expanding costs no request and no spinner.
 *
 * Rows with no value are omitted rather than shown empty. That is not cosmetic:
 * a Bronze declares only description / source_system of this set, so an "always
 * render every label" panel would state a dozen absences that the layer's
 * contract never asked for.
 */

import type { YAMLNodeSummary } from '@/api/types'

const CLASSIFICATION_LABEL: Record<string, string> = {
  M: 'master',
  T: 'transactional',
  C: 'configuration',
}

function KV({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex gap-2 py-0.5 text-[11px] leading-snug">
      <span className="w-24 shrink-0 text-gray-400">{label}</span>
      <span className={`min-w-0 break-words text-gray-700 ${mono ? 'font-mono' : ''}`}>
        {value}
      </span>
    </div>
  )
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <h4 className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-gray-400">
        {title}
      </h4>
      {children}
    </div>
  )
}

export function EntityHeaderDetail({ row }: { row: YAMLNodeSummary }) {
  // Defensive reads: admin-api and studio-spa are separate images, so a rollout
  // can serve this component against an API that predates the projection. The
  // types say these are always present; a stale payload would say otherwise and
  // `undefined.length` would take the whole page down for a cosmetic panel.
  const fieldCount = row.field_count ?? 0
  const measureCount = row.measure_count ?? 0
  const relationshipCount = row.relationship_count ?? 0
  const instance =
    row.source_system && row.source_system_no != null
      ? `${row.source_system} · no ${row.source_system_no}`
      : row.source_system
  const classification = row.classification
    ? `${row.classification}${CLASSIFICATION_LABEL[row.classification] ? ` · ${CLASSIFICATION_LABEL[row.classification]}` : ''}`
    : null
  // Bronze has no grain block; its declared key is the equivalent structural fact.
  const keyLabel = row.layer === 'bronze' ? 'primary_key' : 'entity_grain'
  const keyMembers = (row.layer === 'bronze' ? row.primary_key : row.entity_grain) ?? []
  const shape = [
    `${fieldCount} field${fieldCount === 1 ? '' : 's'}`,
    measureCount > 0 ? `${measureCount} measures` : null,
    relationshipCount > 0 ? `${relationshipCount} relationships` : null,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className="rounded-md border border-gray-200 bg-gray-50/70 p-3">
      {row.description && (
        <p className="mb-3 max-w-4xl text-xs leading-relaxed text-gray-600">{row.description}</p>
      )}

      <div className="grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2 xl:grid-cols-3">
        <Group title="Physical">
          {row.db_table_name && <KV label="db_table" value={row.db_table_name} mono />}
          {instance && <KV label="source" value={instance} />}
        </Group>

        <Group title="Structure">
          {keyMembers.length > 0 && <KV label={keyLabel} value={keyMembers.join(', ')} mono />}
          {row.business_grain && <KV label="business grain" value={row.business_grain} />}
          <KV label="shape" value={shape} />
          {row.has_normalization && <KV label="normalization" value="currency / UoM declared" />}
        </Group>

        <Group title="Catalog">
          {classification && <KV label="class" value={classification} />}
          {row.entity_role && <KV label="role" value={row.entity_role} />}
          {row.alias && row.alias !== row.name && <KV label="alias" value={row.alias} />}
          {(row.tag1 || row.tag2) && (
            <KV label="tags" value={[row.tag1, row.tag2].filter(Boolean).join(' · ')} />
          )}
          {row.internal_id && <KV label="internal_id" value={row.internal_id} mono />}
        </Group>
      </div>
    </div>
  )
}
