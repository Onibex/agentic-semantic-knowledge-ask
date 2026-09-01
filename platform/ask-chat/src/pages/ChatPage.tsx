/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useState, useCallback, useRef, useEffect } from 'react'
import { postQuery, generateChatTitle, extractApiError } from '@/api/orchestrator'
import type { ConversationTurn } from '@/api/orchestrator'
import type { ChatMessage, MessageMeta } from '@/types'
import { useChatStore } from '@/store/chatStore'
import { Thread } from '@/components/Thread'
import { ChatSidebar } from '@/components/ChatSidebar'
import { toast } from 'sonner'
import { useTranslation } from '@/hooks/useTranslation'

// Re-export for any consumers still importing from here
export type { ChatMessage }

// ── Chat hook ─────────────────────────────────────────────────────────────────

function useChat() {
  const {
    workspaceId,
    env,
    mode,
    workspaceChats,
    activeChatIds,
    setChatMessages,
    updateChatTitle,
    createChat,
  } = useChatStore()

  const chats = workspaceChats[workspaceId] ?? []
  const activeChatId = activeChatIds[workspaceId] ?? ''
  const activeChat = chats.find((c) => c.id === activeChatId)
  const messages = activeChat?.messages ?? []

  // Auto-create a chat when the workspace is set but has no valid active chat
  useEffect(() => {
    if (!workspaceId) return
    if (chats.length === 0 || !activeChatId || !chats.find((c) => c.id === activeChatId)) {
      createChat(workspaceId)
    }
  }, [workspaceId, chats.length, activeChatId, createChat])

  const [isRunning, setIsRunning] = useState(false)
  const abortRef = useRef(false)

  const send = useCallback(
    async (userText: string) => {
      if (!userText.trim()) return
      if (!workspaceId) {
        toast.warning('Select a workspace in the sidebar before asking a question.')
        return
      }

      // Snapshot store at call time — avoids stale-closure bugs during async streaming
      const state = useChatStore.getState()
      const chatId = state.activeChatIds[workspaceId]
      if (!chatId) return

      const wsChats = state.workspaceChats[workspaceId] ?? []
      const chat = wsChats.find((c) => c.id === chatId)
      if (!chat) return

      const isFirstMessage = chat.messages.length === 0
      const history: ConversationTurn[] = chat.messages.map((m) => ({
        role: m.role,
        content: m.text,
      }))

      const userId = crypto.randomUUID()
      const assistantId = crypto.randomUUID()

      // Add user message immediately; track via local variable during streaming
      // to avoid stale-ref races when the store re-renders.
      let currentMsgs: ChatMessage[] = [
        ...chat.messages,
        { id: userId, role: 'user', text: userText },
      ]
      setChatMessages(workspaceId, chatId, currentMsgs)

      setIsRunning(true)
      abortRef.current = false

      try {
        const result = await postQuery({
          question: userText,
          workspace_id: workspaceId,
          mode,
          env,
          session_id: chat.sessionId,
          conversation_history: history.length ? history : null,
        })

        const fullText = result.answer ?? ''
        const meta: MessageMeta = {
          sql: result.sql,
          rows: result.rows,
          mode_used: result.mode_used,
          macro_intent: result.macro_intent,
          trace_id: result.trace_id,
          tokens_used: result.tokens_used,
          tokens_breakdown: result.tokens_breakdown,
        }

        // Insert empty assistant placeholder before streaming begins
        currentMsgs = [...currentMsgs, { id: assistantId, role: 'assistant', text: '', meta }]
        setChatMessages(workspaceId, chatId, currentMsgs)

        // Batch streaming: 6 words / 30 ms → ~10× fewer renders than per-word
        const words = fullText.split(' ')
        const BATCH = 6
        const TICK = 30
        let revealed = ''
        for (let i = 0; i < words.length; i += BATCH) {
          if (abortRef.current) break
          await new Promise<void>((r) => setTimeout(r, TICK))
          const chunk = words.slice(i, i + BATCH).join(' ')
          revealed += (i === 0 ? '' : ' ') + chunk
          const snap = revealed
          currentMsgs = currentMsgs.map((m) =>
            m.id === assistantId ? { ...m, text: snap } : m,
          )
          setChatMessages(workspaceId, chatId, currentMsgs)
        }

        // Finalize with full text + meta
        currentMsgs = currentMsgs.map((m) =>
          m.id === assistantId ? { ...m, text: fullText, meta } : m,
        )
        setChatMessages(workspaceId, chatId, currentMsgs)

        // Generate an LLM title on the first exchange (fire-and-forget)
        if (isFirstMessage) {
          generateChatTitle({ question: userText })
            .then(({ title }) => updateChatTitle(workspaceId, chatId, title))
            .catch(() => {/* keep 'New Chat' on failure */})
        }
      } catch (err) {
        const msg = extractApiError(err)
        toast.error(msg)
        currentMsgs = [
          ...currentMsgs,
          { id: assistantId, role: 'assistant', text: `⚠ ${msg}` },
        ]
        setChatMessages(workspaceId, chatId, currentMsgs)
      } finally {
        setIsRunning(false)
      }
    },
    [workspaceId, env, mode, setChatMessages, updateChatTitle],
  )

  return { messages, isRunning, send }
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const { workspaceId } = useChatStore()
  const { messages, isRunning, send } = useChat()
  const { t } = useTranslation()

  return (
    <div className="flex h-full overflow-hidden">
      {/* Per-workspace chat history sidebar */}
      <ChatSidebar />

      {/* Main chat area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {!workspaceId && (
          <div className="shrink-0 border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-700">
            {t('chat_select_workspace')}
          </div>
        )}
        <Thread messages={messages} isRunning={isRunning} onSend={send} />
      </div>
    </div>
  )
}
