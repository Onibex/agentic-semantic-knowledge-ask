/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * Organization profile — singleton page.
 *
 * Captures the customer's identity (company name, SAP version, active
 * modules, portal URL) and persists it via PUT /v1/admin/organization.
 *
 * The orchestrator pulls this on every query and prepends it to the agent's
 * system prompt — letting the LLM frame answers in the customer's context
 * ("for ACME Corp running SAP S/4HANA with modules SD, MM, PP …").
 */

import { Building2, Loader2, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { getOrganization, upsertOrganization } from '@/api/client'
import type { Organization } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useTranslation } from '@/hooks/useTranslation'

export default function OrganizationPage() {
  const { t } = useTranslation()
  const [companyName, setCompanyName] = useState('')
  const [sourceSystem, setSourceSystem] = useState('')
  // ``core_bases`` is hidden from the UI for now (the chip editor was removed
  // until we redesign how SAP module scope is captured). We still hydrate the
  // value from the server and ship it back verbatim on save, so existing
  // entries on legacy deployments don't get clobbered.
  const [coreBases, setCoreBases] = useState<string[]>([])
  const [url, setUrl] = useState('')
  const [original, setOriginal] = useState<Organization | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  function hydrate(org: Organization) {
    setCompanyName(org.company_name)
    // Prefer the generic field; fall back to legacy sap_version for unmigrated orgs.
    setSourceSystem(org.source_system || org.sap_version || '')
    setCoreBases(org.core_bases)
    setUrl(org.url)
    setOriginal(org)
  }

  async function load() {
    setLoading(true)
    try {
      hydrate(await getOrganization())
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load organization'
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function handleSave() {
    setSaving(true)
    try {
      const org = await upsertOrganization({
        company_name: companyName.trim(),
        source_system: sourceSystem.trim(),
        core_bases: coreBases,
        url: url.trim(),
      })
      hydrate(org)
      toast.success('Organization profile saved')
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Could not save'
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  const dirty =
    original === null ||
    companyName !== original.company_name ||
    sourceSystem !== (original.source_system || original.sap_version || '') ||
    url !== original.url

  return (
    <div className="max-w-2xl mx-auto p-6">
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-start gap-3">
          <div className="h-10 w-10 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
            <Building2 size={20} className="text-blue-600" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">{t('org_title')}</h1>
            <p className="text-sm text-gray-500 mt-1">{t('org_subtitle')}</p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          <span className="ml-1.5">{t('org_reload')}</span>
        </Button>
      </div>

      <div className="space-y-5 mt-8">
        <div className="space-y-1">
          <Label>{t('org_company_label')}</Label>
          <Input
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            placeholder={t('org_company_ph')}
            disabled={loading}
          />
        </div>

        <div className="space-y-1">
          <Label>{t('org_source_label')}</Label>
          <Input
            value={sourceSystem}
            onChange={(e) => setSourceSystem(e.target.value)}
            placeholder={t('org_source_ph')}
            disabled={loading}
          />
          <p className="text-xs text-gray-500">{t('org_source_hint')}</p>
        </div>

        <div className="space-y-1">
          <Label>{t('org_portal_label')}</Label>
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={t('org_portal_ph')}
            disabled={loading}
          />
        </div>

        <div className="flex justify-end pt-4 border-t border-gray-200">
          <Button onClick={() => void handleSave()} disabled={!dirty || saving || loading}>
            {saving ? (
              <>
                <Loader2 size={12} className="animate-spin mr-1.5" />
                {t('org_saving')}
              </>
            ) : (
              t('org_save')
            )}
          </Button>
        </div>

        {original && original.updated_at && (
          <p className="text-xs text-gray-400">
            Last updated by <code className="font-mono">{original.updated_by || 'unknown'}</code>{' '}
            at <code className="font-mono">{original.updated_at}</code>
          </p>
        )}
      </div>
    </div>
  )
}
