import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import {
  Loader2, FileText, BarChart2, Table2, FileSearch,
  Plus, Search, ChevronDown, ArrowLeft, RefreshCw,
  Download, Copy, Check, Database, Pencil, X,
} from 'lucide-react'
import { postArtifact, extractApiError } from '@/api/orchestrator'
import type { ArtifactResponse, ArtifactRequest, ArtifactDataset } from '@/api/orchestrator'
import { useChatStore } from '@/store/chatStore'
import { toast } from 'sonner'
import { MarkdownContent } from '@/components/MarkdownContent'
import { SqlResultsBlock } from '@/components/SqlResultsBlock'
import { OnibexLogo } from '@/components/OnibexLogo'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/hooks/useTranslation'
import type { TranslationKey } from '@/i18n/translations'

// ── Types ─────────────────────────────────────────────────────────────────────

interface SavedArtifact extends ArtifactResponse {
  id: string
  createdAt: number
  _request: Omit<ArtifactRequest, 'sql_override'>
}

interface CreatorMessage {
  role: 'assistant' | 'user'
  content: string
  chips?: string[]
}

type CreatorStep = 'name' | 'type' | 'purpose' | 'data_focus' | 'format' | 'generating'

interface ArtifactDraft {
  name: string
  artifact_type: string
  purpose: string
  data_focus: string
  format: string
}

// ── Constants ─────────────────────────────────────────────────────────────────

const ARTIFACT_TYPE_VALUES = [
  'sales_report', 'inventory_report', 'executive_summary', 'financial_report', 'custom',
] as const

const FORMAT_OPTION_VALUES = [
  'executive_brief', 'detailed_report', 'data_tables', 'proposal_format', 'dashboard',
] as const

// Maps artifact type value → translation key
const TYPE_LABEL_KEYS: Record<string, TranslationKey> = {
  sales_report:     'artifact_type_sales',
  inventory_report: 'artifact_type_inventory',
  executive_summary:'artifact_type_executive',
  financial_report: 'artifact_type_financial',
  custom:           'artifact_type_custom',
}

// Maps format value → translation key
const FORMAT_LABEL_KEYS: Record<string, TranslationKey> = {
  executive_brief: 'artifact_format_brief',
  detailed_report: 'artifact_format_detailed',
  data_tables:     'artifact_format_tables',
  proposal_format: 'artifact_format_proposal',
  dashboard:       'artifact_format_dashboard',
}

// Chips store format values (not display labels) — translate at render time
const FORMAT_CHIPS = ['detailed_report', 'executive_brief', 'data_tables', 'proposal_format'] as const

const TYPE_ICONS: Record<string, React.ReactNode> = {
  sales_report: <BarChart2 className="h-8 w-8 text-gray-300" />,
  inventory_report: <Table2 className="h-8 w-8 text-gray-300" />,
  financial_report: <BarChart2 className="h-8 w-8 text-gray-300" />,
  executive_summary: <FileSearch className="h-8 w-8 text-gray-300" />,
  custom: <FileText className="h-8 w-8 text-gray-300" />,
}

function buildStepMeta(t: (k: TranslationKey) => string): Record<Exclude<CreatorStep, 'generating'>, { question: string; placeholder: string; chips?: string[] }> {
  return {
    name:       { question: t('artifact_step_name_q'),    placeholder: t('artifact_step_name_ph') },
    type:       { question: '',                            placeholder: '' },
    purpose:    { question: t('artifact_step_purpose_q'), placeholder: t('artifact_step_purpose_ph') },
    data_focus: { question: t('artifact_step_data_q'),    placeholder: t('artifact_step_data_ph') },
    format:     { question: t('artifact_step_format_q'),  placeholder: t('artifact_step_format_ph'), chips: [...FORMAT_CHIPS] },
  }
}

const STEP_ORDER: Array<Exclude<CreatorStep, 'generating'>> = [
  'name', 'purpose', 'data_focus', 'format',
]

const THINKING_COUNT = 12

function pickMsg(exclude: number): number {
  let next = exclude
  while (next === exclude) next = Math.floor(Math.random() * THINKING_COUNT)
  return next
}

// ── Excel export (SpreadsheetML — no library required) ────────────────────────

function escXml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function parseTableRow(line: string): string[] {
  return line.split('|').slice(1, -1).map((c) => c.trim())
}

function isTableSep(line: string): boolean {
  return /^\|[\s|:\-]+\|$/.test(line.trim())
}

function inlineStrip(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/`(.+?)`/g, '$1')
    .replace(/\[(.+?)\]\(.+?\)/g, '$1')
}

// Converts markdown content to SpreadsheetML rows, properly handling tables
function buildReportSheet(artifactName: string, content: string): string {
  const lines = content.split('\n')
  const rows: string[] = []

  rows.push(`<Row><Cell ss:StyleID="title"><Data ss:Type="String">${escXml(artifactName)}</Data></Cell></Row>`)
  rows.push('<Row/>')

  let i = 0
  while (i < lines.length) {
    const raw = lines[i]
    const trimmed = raw.trim()

    // Empty / horizontal rule
    if (!trimmed || /^---+$/.test(trimmed) || /^\*\*\*+$/.test(trimmed)) {
      rows.push('<Row/>')
      i++
      continue
    }

    // Heading → bold cell with blue fill
    const hm = trimmed.match(/^(#{1,6})\s+(.+)/)
    if (hm) {
      rows.push(`<Row><Cell ss:StyleID="heading"><Data ss:Type="String">${escXml(inlineStrip(hm[2]))}</Data></Cell></Row>`)
      i++
      continue
    }

    // Markdown table — header row followed by separator
    if (trimmed.startsWith('|')) {
      const nextTrimmed = (lines[i + 1] ?? '').trim()
      if (isTableSep(nextTrimmed)) {
        // Table header
        const cells = parseTableRow(trimmed)
        const headerCells = cells
          .map((c) => `<Cell ss:StyleID="header"><Data ss:Type="String">${escXml(c)}</Data></Cell>`)
          .join('')
        rows.push(`<Row>${headerCells}</Row>`)
        i += 2 // skip separator
        continue
      }
      if (isTableSep(trimmed)) { i++; continue } // lone separator
      // Table data row
      const cells = parseTableRow(trimmed)
      const dataCells = cells.map((c) => {
        const n = Number(c.replace(/,/g, ''))
        const isNum = c.trim() !== '' && !isNaN(n) && isFinite(n)
        return `<Cell><Data ss:Type="${isNum ? 'Number' : 'String'}">${escXml(isNum ? n : c)}</Data></Cell>`
      }).join('')
      rows.push(`<Row>${dataCells}</Row>`)
      i++
      continue
    }

    // List item
    const li = trimmed.match(/^[-*+]\s+(.+)/)
    if (li) {
      rows.push(`<Row><Cell><Data ss:Type="String">${escXml('• ' + inlineStrip(li[1]))}</Data></Cell></Row>`)
      i++
      continue
    }

    // Normal paragraph
    rows.push(`<Row><Cell><Data ss:Type="String">${escXml(inlineStrip(trimmed))}</Data></Cell></Row>`)
    i++
  }

  return `<Worksheet ss:Name="Report"><Table ss:DefaultColumnWidth="180">${rows.join('')}</Table></Worksheet>`
}

function buildXmlSheet(sheetName: string, rows: Record<string, unknown>[]): string {
  if (rows.length === 0) return ''
  const headers = Object.keys(rows[0])
  const safe = escXml(sheetName.slice(0, 31))
  const headerCells = headers
    .map((h) => `<Cell ss:StyleID="header"><Data ss:Type="String">${escXml(h)}</Data></Cell>`)
    .join('')
  const dataRows = rows
    .map((row) => {
      const cells = headers.map((h) => {
        const v = row[h]
        const isNum = typeof v === 'number' && isFinite(v)
        return `<Cell><Data ss:Type="${isNum ? 'Number' : 'String'}">${escXml(v)}</Data></Cell>`
      })
      return `<Row>${cells.join('')}</Row>`
    })
    .join('')
  return `<Worksheet ss:Name="${safe}"><Table><Row>${headerCells}</Row>${dataRows}</Table></Worksheet>`
}

function buildSqlSheet(datasets: ArtifactDataset[]): string {
  const withSql = datasets.filter((ds) => ds.sql)
  if (withSql.length === 0) return ''
  const rows: string[] = [
    `<Row><Cell ss:StyleID="title"><Data ss:Type="String">SQL Queries</Data></Cell></Row>`,
    '<Row/>',
  ]
  withSql.forEach((ds, i) => {
    rows.push(
      `<Row><Cell ss:StyleID="heading"><Data ss:Type="String">${escXml(ds.name || `Dataset ${i + 1}`)}</Data></Cell></Row>`,
    )
    ;(ds.sql ?? '').split('\n').forEach((line) => {
      rows.push(`<Row><Cell><Data ss:Type="String">${escXml(line)}</Data></Cell></Row>`)
    })
    rows.push('<Row/>')
  })
  return `<Worksheet ss:Name="SQL"><Table ss:DefaultColumnWidth="600">${rows.join('')}</Table></Worksheet>`
}

function downloadAsExcel(name: string, content: string, datasets: ArtifactDataset[]): void {
  const reportSheet = buildReportSheet(name, content)
  const dataSheets = datasets
    .filter((ds) => ds.rows && ds.rows.length > 0)
    .map((ds, i) => buildXmlSheet(ds.name || `Dataset ${i + 1}`, ds.rows!))
    .join('\n')
  const sqlSheet = buildSqlSheet(datasets)

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
  xmlns:o="urn:schemas-microsoft-com:office:office"
  xmlns:x="urn:schemas-microsoft-com:office:excel"
  xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
  <Styles>
    <Style ss:ID="title"><Font ss:Bold="1" ss:Size="14"/></Style>
    <Style ss:ID="heading"><Font ss:Bold="1"/><Interior ss:Color="#DBEAFE" ss:Pattern="Solid"/></Style>
    <Style ss:ID="header"><Font ss:Bold="1"/><Interior ss:Color="#EFF6FF" ss:Pattern="Solid"/></Style>
  </Styles>
  ${reportSheet}
  ${dataSheets}
  ${sqlSheet}
</Workbook>`

  const blob = new Blob([xml], { type: 'application/vnd.ms-excel;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${name}.xls`
  a.click()
  URL.revokeObjectURL(url)
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function timeAgo(ts: number): string {
  const diff = Date.now() - ts
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 7) return `${days}d ago`
  return `${Math.floor(days / 7)}w ago`
}

function typeLabel(value: string, t: (k: TranslationKey) => string): string {
  const key = TYPE_LABEL_KEYS[value]
  return key ? t(key) : value
}

function formatLabel(value: string, t: (k: TranslationKey) => string): string {
  const key = FORMAT_LABEL_KEYS[value]
  return key ? t(key) : value
}

// ── Copy button ────────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 2000)
        })
      }}
      className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-gray-500 hover:text-gray-800 hover:bg-gray-100 transition-colors"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? t('artifact_copied') : t('artifact_copy')}
    </button>
  )
}

// ── Thinking bubble (inside chat creator) ─────────────────────────────────────

function ThinkingBubble() {
  const { t } = useTranslation()
  const [idx, setIdx] = useState(() => Math.floor(Math.random() * THINKING_COUNT))
  const [visible, setVisible] = useState(true)

  const thinkingMsgs = [
    t('artifact_thinking_0'), t('artifact_thinking_1'), t('artifact_thinking_2'),
    t('artifact_thinking_3'), t('artifact_thinking_4'), t('artifact_thinking_5'),
    t('artifact_thinking_6'), t('artifact_thinking_7'), t('artifact_thinking_8'),
    t('artifact_thinking_9'), t('artifact_thinking_10'), t('artifact_thinking_11'),
  ]

  useEffect(() => {
    const id = setInterval(() => {
      setVisible(false)
      setTimeout(() => {
        setIdx((prev) => pickMsg(prev))
        setVisible(true)
      }, 280)
    }, 2800)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="flex gap-3 px-4 py-2">
      <div className="shrink-0 mt-0.5">
        <OnibexLogo className="w-7 h-7" />
      </div>
      <div className="flex items-center h-7">
        <span
          className="text-sm text-gray-400 italic transition-opacity duration-300"
          style={{ opacity: visible ? 1 : 0 }}
        >
          {thinkingMsgs[idx]}
        </span>
      </div>
    </div>
  )
}

// ── Artifact chat creator ─────────────────────────────────────────────────────

function ArtifactChatCreator({
  onCreated,
  onCancel,
}: {
  onCreated: (a: SavedArtifact) => void
  onCancel: () => void
}) {
  const { workspaceId, env, mode } = useChatStore()
  const { t } = useTranslation()
  const STEP_META = buildStepMeta(t)
  const [messages, setMessages] = useState<CreatorMessage[]>(() => [
    { role: 'assistant', content: buildStepMeta(t)['name'].question },
  ])
  const [step, setStep] = useState<CreatorStep>('name')
  const [draft, setDraft] = useState<Partial<ArtifactDraft>>({})
  const [input, setInput] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isTyping])

  const processAnswer = useCallback(
    (currentStep: Exclude<CreatorStep, 'generating'>, answer: string): Partial<ArtifactDraft> => {
      switch (currentStep) {
        case 'name': return { name: answer }
        case 'purpose': return { purpose: answer }
        case 'data_focus': return { data_focus: answer }
        case 'format': {
          // Chips pass format values directly; user-typed text falls back to detailed_report
          const knownFormats = [...FORMAT_OPTION_VALUES] as string[]
          return { format: knownFormats.includes(answer) ? answer : 'detailed_report' }
        }
        default: return {}
      }
    },
    [],
  )

  const advanceStep = useCallback(
    async (answer: string) => {
      if (step === 'generating') return

      const currentStep = step as Exclude<CreatorStep, 'generating'>
      const newDraft = { ...draft, ...processAnswer(currentStep, answer) }
      setDraft(newDraft)

      // Add user message
      setMessages((prev) => [...prev, { role: 'user', content: answer }])
      setInput('')
      if (textareaRef.current) textareaRef.current.style.height = 'auto'

      const currentIdx = STEP_ORDER.indexOf(currentStep)
      const nextStep = STEP_ORDER[currentIdx + 1]

      if (!nextStep) {
        // All questions answered — generate
        setIsTyping(true)
        await new Promise((r) => setTimeout(r, 500))
        setIsTyping(false)
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: t('artifact_generating_msg').replace('{name}', newDraft.name ?? '') },
        ])
        setStep('generating')

        if (!workspaceId) {
          toast.warning('Select a workspace first.')
          return
        }

        try {
          const req: ArtifactRequest = {
            name: newDraft.name ?? 'Untitled',
            artifact_type: 'custom',
            format: newDraft.format ?? 'detailed_report',
            purpose: newDraft.purpose ?? '',
            data_focus: newDraft.data_focus ?? '',
            mode,
            env,
            workspace_id: workspaceId,
          }
          const res = await postArtifact(req)
          onCreated({ ...res, id: crypto.randomUUID(), createdAt: Date.now(), _request: req })
        } catch (err) {
          toast.error(`Generation failed: ${extractApiError(err)}`)
          // Let user go back
          setStep('format')
          setMessages((prev) => [
            ...prev,
            { role: 'assistant', content: t('artifact_error_recovery') },
          ])
        }
        return
      }

      // Show next question after a brief typing indicator
      setIsTyping(true)
      await new Promise((r) => setTimeout(r, 500))
      setIsTyping(false)
      setStep(nextStep)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: STEP_META[nextStep].question,
          chips: STEP_META[nextStep].chips,
        },
      ])
    },
    [step, draft, workspaceId, mode, env, onCreated, processAnswer],
  )

  const handleSend = useCallback(() => {
    const text = input.trim()
    if (!text || step === 'generating') return
    advanceStep(text)
  }, [input, step, advanceStep])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleTextareaInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value)
    const ta = e.target
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`
  }

  const isGenerating = step === 'generating'
  const currentPlaceholder = isGenerating ? '' : STEP_META[step as Exclude<CreatorStep, 'generating'>]?.placeholder ?? ''

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-5 py-3 border-b border-gray-200 shrink-0">
        <button
          onClick={onCancel}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          {t('artifact_back_gallery')}
        </button>
        <div className="w-px h-4 bg-gray-200" />
        <span className="text-sm font-medium text-gray-700">{t('artifact_new_artifact_header')}</span>
      </div>

      {/* Message thread */}
      <div className="flex-1 overflow-y-auto py-6">
        <div className="mx-auto max-w-2xl space-y-1 px-4">
          {messages.map((msg, i) => {
            const isLastMsg = i === messages.length - 1
            if (msg.role === 'user') {
              return (
                <div key={i} className="flex justify-end py-1.5">
                  <div className="max-w-[70%] rounded-2xl rounded-br-md bg-gray-100 px-4 py-2.5 text-sm text-gray-800 leading-relaxed">
                    {msg.content}
                  </div>
                </div>
              )
            }
            return (
              <div key={i} className="flex gap-3 py-1.5">
                <div className="shrink-0 mt-0.5">
                  <OnibexLogo className="w-7 h-7" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-800 leading-relaxed">{msg.content}</p>
                  {/* Chips — only on the last assistant message */}
                  {msg.chips && isLastMsg && !isTyping && !isGenerating && (
                    <div className="flex flex-wrap gap-2 mt-3">
                      {msg.chips.map((chip) => (
                        <button
                          key={chip}
                          onClick={() => advanceStep(chip)}
                          className="rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-600 hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 transition-colors"
                        >
                          {formatLabel(chip, t)}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )
          })}

          {/* Typing indicator OR generating spinner */}
          {isTyping && <ThinkingBubble />}
          {isGenerating && !isTyping && <ThinkingBubble />}

          <div ref={bottomRef} />
        </div>
      </div>

      {/* Composer — hidden while generating */}
      {!isGenerating && (
        <div className="shrink-0 px-4 pb-4 pt-2">
          <div className="mx-auto max-w-2xl">
            <div className="flex items-end gap-2 rounded-2xl border border-gray-200 bg-white px-4 py-3 shadow-sm focus-within:border-blue-400 focus-within:shadow-md transition-all">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={handleTextareaInput}
                onKeyDown={handleKeyDown}
                placeholder={currentPlaceholder}
                rows={1}
                disabled={isTyping}
                className="flex-1 resize-none bg-transparent text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none overflow-y-hidden leading-relaxed disabled:opacity-50"
                style={{ maxHeight: 160 }}
              />
              <button
                onClick={handleSend}
                disabled={isTyping || !input.trim()}
                className={cn(
                  'flex h-8 w-8 shrink-0 items-center justify-center rounded-xl transition-all',
                  'bg-blue-600 text-white hover:bg-blue-700',
                  'disabled:bg-gray-100 disabled:text-gray-300 disabled:cursor-not-allowed',
                )}
              >
                {isTyping
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 2L11 13" /><path d="M22 2L15 22 11 13 2 9l20-7z" /></svg>
                }
              </button>
            </div>
            <p className="mt-1.5 text-center text-[10px] text-gray-300">
              {t('artifact_composer_hint')}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Dataset panel ──────────────────────────────────────────────────────────────

function DatasetPanel({ datasets }: { datasets: ArtifactDataset[] }) {
  const { t } = useTranslation()
  const [activeIdx, setActiveIdx] = useState(0)

  if (datasets.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 text-center">
        <Database className="h-8 w-8 text-gray-300" />
        <p className="text-sm text-gray-400">{t('artifact_no_datasets')}</p>
      </div>
    )
  }

  const ds = datasets[activeIdx]

  return (
    <div className="flex flex-col h-full">
      {datasets.length > 1 && (
        <div className="flex gap-1 px-6 py-2 border-b border-gray-100 shrink-0 flex-wrap">
          {datasets.map((d, i) => (
            <button
              key={i}
              onClick={() => setActiveIdx(i)}
              className={cn(
                'rounded-md px-3 py-1 text-xs font-medium transition-colors',
                activeIdx === i
                  ? 'bg-blue-50 text-blue-700 border border-blue-200'
                  : 'text-gray-500 hover:bg-gray-100 border border-transparent',
              )}
            >
              {d.name || `Dataset ${i + 1}`}
            </button>
          ))}
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-6">
        {ds.error && (
          <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            {ds.error}
          </div>
        )}
        <SqlResultsBlock rows={ds.rows ?? []} sql={ds.sql} />
      </div>
    </div>
  )
}

// ── Artifact viewer ────────────────────────────────────────────────────────────

function ArtifactViewer({
  artifact,
  onBack,
  onUpdated,
}: {
  artifact: SavedArtifact
  onBack: () => void
  onUpdated: (a: SavedArtifact) => void
}) {
  const { workspaceId, env, mode } = useChatStore()
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState<'document' | 'data'>('document')
  const [regenerating, setRegenerate] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editValues, setEditValues] = useState({
    name: artifact._request.name,
    purpose: artifact._request.purpose,
    data_focus: artifact._request.data_focus,
    format: artifact._request.format,
  })
  const [sqlOverride, setSqlOverride] = useState((artifact.datasets ?? [])[0]?.sql ?? artifact.sql ?? '')

  const datasets = artifact.datasets ?? []
  const hasData = datasets.length > 0

  const handleRegenerate = async () => {
    if (!workspaceId) { toast.warning('Select a workspace first.'); return }
    setRegenerate(true)
    try {
      const primarySql = datasets[0]?.sql ?? artifact.sql ?? undefined
      const req: ArtifactRequest = {
        ...artifact._request,
        workspace_id: workspaceId,
        env,
        mode,
        sql_override: primarySql ?? null,
      }
      const res = await postArtifact(req)
      onUpdated({ ...res, id: artifact.id, createdAt: Date.now(), _request: artifact._request })
      toast.success('Artifact regenerated')
    } catch (err) {
      toast.error(`Regeneration failed: ${extractApiError(err)}`)
    } finally {
      setRegenerate(false)
    }
  }

  const handleEditRegenerate = async () => {
    if (!workspaceId) { toast.warning('Select a workspace first.'); return }
    setRegenerate(true)
    try {
      const newRequest: Omit<ArtifactRequest, 'sql_override'> = {
        ...artifact._request,
        ...editValues,
        workspace_id: workspaceId,
        env,
        mode,
      }
      const originalSql = (artifact.datasets ?? [])[0]?.sql ?? artifact.sql ?? ''
      const sqlChanged = sqlOverride.trim() !== originalSql.trim()
      const res = await postArtifact({
        ...newRequest,
        ...(sqlChanged && sqlOverride.trim() ? { sql_override: sqlOverride.trim() } : {}),
      })
      onUpdated({ ...res, id: artifact.id, createdAt: Date.now(), _request: newRequest })
      setEditing(false)
      toast.success('Artifact updated')
    } catch (err) {
      toast.error(`Update failed: ${extractApiError(err)}`)
    } finally {
      setRegenerate(false)
    }
  }

  const dataDatasets = (artifact.datasets ?? []).filter((ds) => ds.rows && ds.rows.length > 0)

  const handleDownload = () => {
    downloadAsExcel(artifact.name, artifact.content, dataDatasets)
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-3 border-b border-gray-200 bg-white shrink-0 flex-wrap gap-y-2">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          {t('artifact_back')}
        </button>
        <div className="w-px h-4 bg-gray-200" />
        <h1 className="text-sm font-semibold text-gray-900 truncate max-w-xs">{artifact.name}</h1>
        <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-600">
          {formatLabel(artifact.format ?? '', t)}
        </span>
        {artifact.tokens_used && (
          <span className="text-[10px] text-gray-400">{artifact.tokens_used.toLocaleString()} tokens</span>
        )}
        <div className="ml-auto flex items-center gap-1">
          <CopyButton text={artifact.content} />
          <button
            onClick={handleDownload}
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-gray-500 hover:text-gray-800 hover:bg-gray-100 transition-colors"
          >
            <Download className="h-3.5 w-3.5" />
            {t('artifact_download_excel')}
          </button>
          <button
            onClick={() => setEditing((v) => !v)}
            className={cn(
              'flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors',
              editing
                ? 'bg-gray-100 text-gray-800'
                : 'text-gray-500 hover:text-gray-800 hover:bg-gray-100',
            )}
          >
            {editing ? <X className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
            {editing ? t('artifact_cancel') : t('artifact_edit')}
          </button>
          <button
            onClick={handleRegenerate}
            disabled={regenerating || editing}
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-blue-600 hover:text-blue-800 hover:bg-blue-50 transition-colors disabled:opacity-40"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', regenerating && 'animate-spin')} />
            {regenerating ? t('artifact_regenerating') : t('artifact_regenerate')}
          </button>
        </div>
      </div>

      {/* Edit panel */}
      {editing && (
        <div className="shrink-0 border-b border-gray-200 bg-gray-50 px-6 py-4">
          <div className="grid grid-cols-2 gap-3 mb-3">
            <div>
              <label className="block text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1">{t('artifact_label_name')}</label>
              <input
                value={editValues.name}
                onChange={(e) => setEditValues((v) => ({ ...v, name: e.target.value }))}
                className="w-full rounded-md border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-800 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1">{t('artifact_label_format')}</label>
              <select
                value={editValues.format}
                onChange={(e) => setEditValues((v) => ({ ...v, format: e.target.value }))}
                className="w-full rounded-md border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                {FORMAT_OPTION_VALUES.map((v) => (
                  <option key={v} value={v}>{formatLabel(v, t)}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="mb-3">
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1">{t('artifact_label_purpose')}</label>
            <textarea
              value={editValues.purpose}
              onChange={(e) => setEditValues((v) => ({ ...v, purpose: e.target.value }))}
              rows={2}
              className="w-full rounded-md border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-800 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
            />
          </div>
          <div className="mb-3">
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1">{t('artifact_label_data_focus')}</label>
            <textarea
              value={editValues.data_focus}
              onChange={(e) => setEditValues((v) => ({ ...v, data_focus: e.target.value }))}
              rows={3}
              className="w-full rounded-md border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-800 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
            />
          </div>
          <div className="mb-3">
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1">
              {t('artifact_label_sql_override')}
              <span className="ml-2 normal-case font-normal text-gray-400">
                {t('artifact_label_sql_hint')}
              </span>
            </label>
            <textarea
              value={sqlOverride}
              onChange={(e) => setSqlOverride(e.target.value)}
              rows={5}
              spellCheck={false}
              placeholder={t('artifact_label_sql_ph')}
              className="w-full rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-xs text-green-300 font-mono focus:outline-none focus:ring-1 focus:ring-blue-500 resize-y placeholder:text-gray-600"
            />
          </div>
          <button
            onClick={handleEditRegenerate}
            disabled={regenerating}
            className="flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {regenerating
              ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> {t('artifact_applying')}</>
              : <><RefreshCw className="h-3.5 w-3.5" /> {t('artifact_apply_regenerate')}</>
            }
          </button>
        </div>
      )}

      {/* Tab bar */}
      <div className="flex gap-0 border-b border-gray-200 bg-white shrink-0 px-6">
        <button
          onClick={() => setActiveTab('document')}
          className={cn(
            'px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
            activeTab === 'document'
              ? 'border-blue-600 text-blue-700'
              : 'border-transparent text-gray-500 hover:text-gray-700',
          )}
        >
          {t('artifact_tab_document')}
        </button>
        {hasData && (
          <button
            onClick={() => setActiveTab('data')}
            className={cn(
              'flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
              activeTab === 'data'
                ? 'border-blue-600 text-blue-700'
                : 'border-transparent text-gray-500 hover:text-gray-700',
            )}
          >
            <Database className="h-3.5 w-3.5" />
            {t('artifact_tab_data')}
            <span className="rounded-full bg-gray-100 px-1.5 text-[10px] font-semibold text-gray-500">
              {datasets.length}
            </span>
          </button>
        )}
      </div>

      {/* Tab content */}
      {activeTab === 'document' && (
        <div className="flex-1 overflow-y-auto p-6 bg-gray-50">
          {artifact.data_error && (
            <div className="mb-4 max-w-3xl mx-auto rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              {artifact.data_error}
            </div>
          )}
          <div className="max-w-3xl mx-auto rounded-xl border border-gray-200 bg-white px-8 py-8 shadow-sm">
            <MarkdownContent content={artifact.content} />
          </div>
        </div>
      )}

      {activeTab === 'data' && hasData && (
        <div className="flex-1 overflow-hidden">
          <DatasetPanel datasets={datasets} />
        </div>
      )}
    </div>
  )
}

// ── Artifact card (gallery) ────────────────────────────────────────────────────

function ArtifactCard({ artifact, onClick }: { artifact: SavedArtifact; onClick: () => void }) {
  const { t } = useTranslation()
  return (
    <button
      onClick={onClick}
      className="group text-left rounded-xl border border-gray-200 bg-white hover:border-gray-300 hover:shadow-sm transition-all overflow-hidden"
    >
      <div className="flex items-center justify-center h-36 bg-gray-50 border-b border-gray-100 relative">
        <div className="absolute top-2 right-2 opacity-30">
          <FileText className="h-4 w-4 text-gray-400" />
        </div>
        {TYPE_ICONS[artifact.artifact_type] ?? <FileText className="h-8 w-8 text-gray-300" />}
      </div>
      <div className="px-4 py-3">
        <p className="text-sm font-medium text-gray-900 truncate">{artifact.name}</p>
        <p className="mt-0.5 text-xs text-gray-400">{t('artifact_edited_prefix')} {timeAgo(artifact.createdAt)}</p>
        <span className="mt-2 inline-block rounded-md bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-600">
          {typeLabel(artifact.artifact_type, t)}
        </span>
      </div>
    </button>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

type PageMode = 'gallery' | 'creating'

const ARTIFACTS_KEY = 'onibex_artifacts_v1'

function loadArtifacts(): SavedArtifact[] {
  try {
    const raw = localStorage.getItem(ARTIFACTS_KEY)
    return raw ? (JSON.parse(raw) as SavedArtifact[]) : []
  } catch {
    return []
  }
}

export default function ArtifactsPage() {
  const { t } = useTranslation()
  const [artifacts, setArtifacts] = useState<SavedArtifact[]>(loadArtifacts)

  useEffect(() => {
    localStorage.setItem(ARTIFACTS_KEY, JSON.stringify(artifacts))
  }, [artifacts])
  const [selected, setSelected] = useState<SavedArtifact | null>(null)
  const [pageMode, setPageMode] = useState<PageMode>('gallery')
  const [search, setSearch] = useState('')
  const [filterType, setFilterType] = useState('all')

  const filtered = useMemo(
    () =>
      artifacts.filter(
        (a) =>
          a.name.toLowerCase().includes(search.toLowerCase()) &&
          (filterType === 'all' || a.artifact_type === filterType),
      ),
    [artifacts, search, filterType],
  )

  const handleCreated = (a: SavedArtifact) => {
    setArtifacts((prev) => [a, ...prev])
    setPageMode('gallery')
    setSelected(a)
  }

  const handleUpdated = (a: SavedArtifact) => {
    setArtifacts((prev) => prev.map((x) => (x.id === a.id ? a : x)))
    setSelected(a)
  }

  // ── Viewer ──
  if (selected) {
    return (
      <ArtifactViewer
        artifact={selected}
        onBack={() => setSelected(null)}
        onUpdated={handleUpdated}
      />
    )
  }

  // ── Chat creator ──
  if (pageMode === 'creating') {
    return (
      <ArtifactChatCreator
        onCreated={handleCreated}
        onCancel={() => setPageMode('gallery')}
      />
    )
  }

  // ── Gallery ──
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-8 pt-8 pb-4 shrink-0">
        <div className="flex items-center justify-between mb-5">
          <h1 className="text-2xl font-semibold text-gray-900">{t('artifact_gallery_title')}</h1>
          <div className="flex items-center gap-2">
            <div className="relative">
              <select
                value={filterType}
                onChange={(e) => setFilterType(e.target.value)}
                className="appearance-none rounded-md border border-gray-200 bg-white pl-3 pr-8 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="all">{t('artifact_all_types')}</option>
                {ARTIFACT_TYPE_VALUES.map((v) => (
                  <option key={v} value={v}>{typeLabel(v, t)}</option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2 top-2 h-4 w-4 text-gray-400" />
            </div>
            <button
              onClick={() => setPageMode('creating')}
              className="flex items-center gap-1.5 rounded-md bg-gray-900 px-3.5 py-2 text-sm font-medium text-white hover:bg-gray-800 transition-colors"
            >
              <Plus className="h-4 w-4" />
              {t('artifact_new_btn')}
            </button>
          </div>
        </div>
        <div className="relative">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('artifact_search_ph')}
            className="w-full rounded-lg border border-gray-200 bg-white pl-9 pr-4 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      {/* Gallery grid */}
      <div className="flex-1 overflow-y-auto px-8 pb-8">
        {artifacts.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
            <div className="rounded-full bg-gray-100 p-4">
              <FileText className="h-7 w-7 text-gray-400" />
            </div>
            <p className="text-sm font-medium text-gray-600">{t('artifact_empty_title')}</p>
            <p className="text-xs text-gray-400">{t('artifact_empty_desc')}</p>
          </div>
        ) : filtered.length === 0 ? (
          <p className="mt-8 text-center text-sm text-gray-400">{t('artifact_no_match')}</p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
            {filtered.map((a) => (
              <ArtifactCard key={a.id} artifact={a} onClick={() => setSelected(a)} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
