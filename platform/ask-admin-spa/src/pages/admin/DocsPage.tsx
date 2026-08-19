/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * Docs page — single-purpose: ingest documentation files into the RAG index.
 *
 * History: this page used to be the Knowledge hub and carried four tabs
 * (Browse Catalog, Import YAML, Ingest Docs, Maintenance). The catalog +
 * YAML lifecycle moved to the Graph page so there is ONE home for entity
 * lifecycle (workspace file + runtime publish). Maintenance / Reset Indices
 * is a destructive admin op that belongs on the Setup page once we add a
 * Danger Zone section there.
 *
 * What stayed: documentation ingestion (PDFs, markdown, etc.) is a separate
 * domain (RAG over docs, not the semantic YAML layer) so it keeps its own
 * page. UX_CHANGES audit (Iter 1) completed the rename: file → DocsPage.tsx,
 * route → `/admin/docs`. The new "Semantic Knowledge" catalog (DataProducts)
 * is a distinct page — see SemanticKnowledgePage.tsx.
 */
import { useState } from 'react'
import { Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toast } from 'sonner'

import { ingestDoc } from '@/api/client'
import type { DocIngestResult } from '@/api/types'
import { useTranslation } from '@/hooks/useTranslation'

export default function DocsPage() {
  const { t } = useTranslation()
  const [file, setFile] = useState<File | null>(null)
  const [collection, setCollection] = useState('rag_docs')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<DocIngestResult | null>(null)

  async function handleIngest() {
    if (!file) return
    setLoading(true)
    setResult(null)
    try {
      const res = await ingestDoc(file, collection)
      setResult(res)
      if (res.error) {
        toast.error(`Ingest failed: ${res.error}`)
      } else {
        toast.success(`Indexed ${res.chunks_indexed} chunks from ${file.name}`)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Ingest failed'
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-8 max-w-3xl">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">{t('docs_title')}</h1>
        <p className="text-sm text-gray-500 mt-1">
          {t('docs_subtitle')}
        </p>
      </header>

      <div className="space-y-5 rounded-md border p-4 bg-white">
        <div className="space-y-1.5">
          <Label htmlFor="doc-file">{t('docs_file_label')}</Label>
          <Input
            id="doc-file"
            type="file"
            accept=".pdf,.docx,.txt,.md,.rst"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null)
              setResult(null)
            }}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="doc-collection">{t('docs_collection_label')}</Label>
          <Input
            id="doc-collection"
            value={collection}
            onChange={(e) => setCollection(e.target.value)}
            placeholder="rag_docs"
          />
        </div>
        <Button
          onClick={() => void handleIngest()}
          disabled={!file || loading}
          className="min-w-36"
        >
          {loading ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              {t('docs_indexing')}
            </>
          ) : (
            t('docs_ingest_btn')
          )}
        </Button>
        {result && !result.error && (
          <div className="rounded-md bg-green-50 border border-green-200 px-4 py-3 text-sm text-green-800 space-y-0.5">
            <p className="font-semibold">{t('docs_indexed_title')}</p>
            <p>
              {t('docs_indexed_chunks')}{' '}
              <span className="font-mono font-bold">{result.chunks_indexed}</span>
            </p>
            <p>
              {t('docs_indexed_batches')} <span className="font-mono">{result.batches_sent}</span>
            </p>
            <p>
              {t('docs_indexed_collection')} <span className="font-mono">{result.collection}</span>
            </p>
          </div>
        )}
        {result?.error && (
          <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
            {result.error}
          </div>
        )}
      </div>
    </div>
  )
}
