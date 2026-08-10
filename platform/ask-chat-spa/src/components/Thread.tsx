import { useRef, useEffect, useState, useCallback } from 'react'
import { SendHorizonal, ArrowDown } from 'lucide-react'
import { OnibexLogo } from './OnibexLogo'
import { cn } from '@/lib/utils'
import { SqlResultsBlock } from './SqlResultsBlock'
import { MarkdownContent } from './MarkdownContent'
import { TokenUsageBlock } from './TokenUsageBlock'
import type { ChatMessage } from '@/types'
import { useTranslation } from '@/hooks/useTranslation'

// ── User message ──────────────────────────────────────────────────────────────

function UserMessage({ msg }: { msg: ChatMessage }) {
  return (
    <div className="flex justify-end px-4 py-1.5">
      <div className="max-w-[70%]">
        <div className="rounded-2xl rounded-br-md bg-gray-100 px-4 py-2.5 text-sm text-gray-800 leading-relaxed">
          <span className="whitespace-pre-wrap">{msg.text}</span>
        </div>
      </div>
    </div>
  )
}

// ── Assistant message ─────────────────────────────────────────────────────────

function AssistantMessage({ msg, isStreaming }: { msg: ChatMessage; isStreaming: boolean }) {
  const rows = (msg.meta?.rows ?? []) as Record<string, unknown>[]
  const hasSqlData = rows.length > 0 || !!msg.meta?.sql
  const tokens = msg.meta?.tokens_breakdown

  return (
    <div className="flex gap-3 px-4 py-1.5">
      {/* Avatar */}
      <div className="shrink-0 mt-0.5">
        <OnibexLogo className="w-7 h-7" />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 space-y-2">
        {/* Text — plain during streaming to avoid parsing overhead */}
        {isStreaming ? (
          <div className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">
            {msg.text}
          </div>
        ) : (
          <MarkdownContent content={msg.text} />
        )}

        {/* Mode badge + token chip + data block only after streaming completes */}
        {!isStreaming && (
          <>
            {(msg.meta?.mode_used || tokens) && (
              // flex-wrap so TokenUsageBlock's expanded panel (basis-full) drops
              // onto its own full-width line below the chips.
              <div className="flex flex-wrap items-center gap-1.5">
                {msg.meta?.mode_used && (
                  <span className="inline-block text-[10px] font-medium text-gray-400 bg-gray-100 rounded px-1.5 py-0.5">
                    {msg.meta.mode_used}
                  </span>
                )}
                {tokens && <TokenUsageBlock breakdown={tokens} />}
              </div>
            )}
            {hasSqlData && (
              <SqlResultsBlock rows={rows} sql={msg.meta?.sql} answerText={msg.text} />
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── Thinking bubble ───────────────────────────────────────────────────────────

const THINKING_MSGS = [
  "Asking your data for guidance...",
  "Consulting the SAP oracle...",
  "Waking up your data products...",
  "Interrogating the tables with respect...",
  "Summoning insights from the knowledge graph...",
  "Teaching SQL to dream...",
  "Whispering to OpenSearch...",
  "Demanding answers from the data void...",
  "Translating your question into database truth...",
  "Following the semantic path to your answer...",
  "Resolving entities in the knowledge plane...",
  "Communing with the silver layer...",
  "Asking the bronze tables very nicely...",
  "Performing the sacred rites of JOIN...",
  "Channeling your CFO's unspoken questions...",
  "Running the numbers through the semantic filter...",
  "Persuading the database to share its secrets...",
  "Searching for truth in aggregate functions...",
  "Bridging human language and SQL...",
  "Cross-referencing with the cosmic schema...",
  "Decoding your business intent...",
  "Making the data work overtime...",
  "Aligning the JOIN stars...",
  "Reasoning across your semantic layer...",
  "Extracting signal from the data noise...",
  "Navigating Dijkstra's path to enlightenment...",
  "Meditating on your warehouse schema...",
  "Politely interviewing each table in order...",
  "Asking the vector index for its deepest thoughts...",
  "Convincing the LLM to stay on topic...",
]

function pickMsg(exclude: number) {
  let next = exclude
  while (next === exclude) next = Math.floor(Math.random() * THINKING_MSGS.length)
  return next
}

function ThinkingBubble() {
  const [idx, setIdx] = useState(() => Math.floor(Math.random() * THINKING_MSGS.length))
  const [visible, setVisible] = useState(true)

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
    <div className="flex gap-3 px-4 py-1.5">
      <div className="shrink-0 mt-0.5">
        <OnibexLogo className="w-7 h-7" />
      </div>
      <div className="flex items-center h-7 min-w-0">
        <span
          className="text-sm text-gray-400 italic truncate transition-opacity duration-300"
          style={{ opacity: visible ? 1 : 0 }}
        >
          {THINKING_MSGS[idx]}
        </span>
      </div>
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ onSend }: { onSend: (text: string) => void }) {
  const { t } = useTranslation()
  const chips = [t('thread_chip1'), t('thread_chip2'), t('thread_chip3')]
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center px-6">
      <OnibexLogo className="h-20 w-20" />
      <div>
        <p className="text-base font-semibold text-gray-800">{t('thread_empty_title')}</p>
        <p className="mt-1 text-sm text-gray-400 max-w-xs">
          {t('thread_empty_subtitle')}
        </p>
      </div>
      <div className="flex flex-wrap gap-2 justify-center mt-2">
        {chips.map((s) => (
          <button
            key={s}
            onClick={() => onSend(s)}
            className="rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-600 hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 transition-colors cursor-pointer"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Composer ──────────────────────────────────────────────────────────────────

function Composer({
  onSend,
  disabled,
}: {
  onSend: (text: string) => void
  disabled: boolean
}) {
  const { t } = useTranslation()
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const submit = useCallback(() => {
    const text = value.trim()
    if (!text || disabled) return
    setValue('')
    // Reset textarea height
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    onSend(text)
  }, [value, disabled, onSend])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value)
    // Auto-resize
    const ta = e.target
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`
  }

  return (
    <div className="shrink-0 px-4 pb-4 pt-2">
      <div className="flex items-end gap-2 rounded-2xl border border-gray-200 bg-white px-4 py-3 shadow-sm focus-within:border-blue-400 focus-within:shadow-md transition-all">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={t('thread_composer_ph')}
          rows={1}
          disabled={disabled}
          className="flex-1 resize-none bg-transparent text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none overflow-y-hidden leading-relaxed disabled:opacity-60"
          style={{ maxHeight: 160 }}
        />
        <button
          onClick={submit}
          disabled={disabled || !value.trim()}
          className={cn(
            'flex h-8 w-8 shrink-0 items-center justify-center rounded-xl transition-all',
            'bg-blue-600 text-white hover:bg-blue-700',
            'disabled:bg-gray-100 disabled:text-gray-300 disabled:cursor-not-allowed',
          )}
        >
          <SendHorizonal className="h-4 w-4" />
        </button>
      </div>
      <p className="mt-1.5 text-center text-[10px] text-gray-300">
        {t('thread_composer_footer')}
      </p>
    </div>
  )
}

// ── Thread ────────────────────────────────────────────────────────────────────

interface ThreadProps {
  messages: ChatMessage[]
  isRunning: boolean
  onSend: (text: string) => void
}

export function Thread({ messages, isRunning, onSend }: ThreadProps) {
  const { t } = useTranslation()
  const viewportRef = useRef<HTMLDivElement>(null)
  const [showScrollBtn, setShowScrollBtn] = useState(false)

  const scrollToBottom = useCallback(() => {
    const el = viewportRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [])

  // Auto-scroll when new messages arrive or text streams in
  useEffect(() => {
    const el = viewportRef.current
    if (!el) return
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    // Only auto-scroll if already near the bottom (within 200px)
    if (distFromBottom < 200) scrollToBottom()
  }, [messages, isRunning, scrollToBottom])

  // Show/hide scroll button based on scroll position
  const handleScroll = () => {
    const el = viewportRef.current
    if (!el) return
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    setShowScrollBtn(distFromBottom > 100)
  }

  const isEmpty = messages.length === 0 && !isRunning

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-white">
      {/* Message list */}
      <div
        ref={viewportRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto"
      >
        {isEmpty ? (
          <div className="h-full">
            <EmptyState onSend={onSend} />
          </div>
        ) : (
          <div className="mx-auto max-w-3xl py-6 space-y-1">
            {messages.map((msg, idx) => {
              const isStreaming =
                isRunning && idx === messages.length - 1 && msg.role === 'assistant'
              return msg.role === 'user' ? (
                <UserMessage key={msg.id} msg={msg} />
              ) : (
                <AssistantMessage key={msg.id} msg={msg} isStreaming={isStreaming} />
              )
            })}
            {/* Show thinking dots while waiting for response (no assistant msg yet) */}
            {isRunning && messages[messages.length - 1]?.role === 'user' && (
              <ThinkingBubble />
            )}
          </div>
        )}
      </div>

      {/* Scroll to bottom button */}
      {showScrollBtn && (
        <div className="relative shrink-0">
          <button
            onClick={scrollToBottom}
            className="absolute bottom-2 left-1/2 -translate-x-1/2 flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-500 shadow-sm hover:text-gray-800 hover:shadow-md transition-all"
          >
            <ArrowDown className="h-3.5 w-3.5" />
            {t('thread_scroll_bottom')}
          </button>
        </div>
      )}

      {/* Composer */}
      <Composer onSend={onSend} disabled={isRunning} />
    </div>
  )
}
