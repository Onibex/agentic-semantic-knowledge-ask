/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { Trash2, Plus, MessageSquare } from 'lucide-react'
import { useChatStore } from '@/store/chatStore'
import type { Chat } from '@/store/chatStore'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/hooks/useTranslation'

// ── Single chat item ───────────────────────────────────────────────────────────

function ChatItem({
  chat,
  isActive,
  onClick,
  onDelete,
}: {
  chat: Chat
  isActive: boolean
  onClick: () => void
  onDelete: (e: React.MouseEvent) => void
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
      className={cn(
        'group flex items-center gap-2 px-3 py-2 rounded-md cursor-pointer transition-colors select-none',
        isActive
          ? 'bg-sidebar-active text-sidebar-active-foreground'
          : 'text-sidebar-foreground hover:bg-muted hover:text-foreground',
      )}
    >
      <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-50" />
      <span className="flex-1 text-xs font-medium truncate">{chat.title}</span>
      <button
        onClick={onDelete}
        className={cn(
          'shrink-0 rounded p-0.5 opacity-0 transition-opacity',
          'group-hover:opacity-50 hover:!opacity-100',
          isActive ? 'text-sidebar-active-foreground' : 'text-muted-foreground hover:text-error',
        )}
        title="Delete chat"
      >
        <Trash2 className="h-3 w-3" />
      </button>
    </div>
  )
}

// ── Sidebar ────────────────────────────────────────────────────────────────────

export function ChatSidebar() {
  const { t } = useTranslation()
  const { workspaceId, workspaceChats, activeChatIds, createChat, deleteChat, setActiveChat } =
    useChatStore()

  const chats = workspaceChats[workspaceId] ?? []
  const activeChatId = activeChatIds[workspaceId] ?? ''

  const handleNew = () => {
    if (workspaceId) createChat(workspaceId)
  }

  const handleDelete = (e: React.MouseEvent, chatId: string) => {
    e.stopPropagation()
    if (!workspaceId) return
    deleteChat(workspaceId, chatId)
    // If no chats remain after deletion, auto-create one
    const remaining = (useChatStore.getState().workspaceChats[workspaceId] ?? [])
    if (remaining.length === 0) createChat(workspaceId)
  }

  return (
    <aside className="w-52 shrink-0 flex flex-col border-r border-sidebar-border bg-sidebar overflow-hidden">
      {/* New chat */}
      <div className="shrink-0 p-3 border-b border-sidebar-border">
        <button
          onClick={handleNew}
          disabled={!workspaceId}
          className={cn(
            'flex w-full items-center gap-2 rounded-md border px-3 py-2',
            'text-xs font-medium transition-colors',
            workspaceId
              ? 'border-border text-sidebar-foreground hover:border-brand/40 hover:bg-sidebar-active hover:text-sidebar-active-foreground'
              : 'border-border/60 text-muted-foreground/50 cursor-not-allowed',
          )}
        >
          <Plus className="h-3.5 w-3.5" />
          {t('sidebar_new_chat')}
        </button>
      </div>

      {/* Chat list */}
      <div className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5">
        {!workspaceId ? (
          <p className="py-4 text-center text-[11px] text-muted-foreground">
            {t('sidebar_select_workspace')}
          </p>
        ) : chats.length === 0 ? (
          <p className="py-4 text-center text-[11px] text-muted-foreground">{t('sidebar_no_chats')}</p>
        ) : (
          chats.map((chat) => (
            <ChatItem
              key={chat.id}
              chat={chat}
              isActive={chat.id === activeChatId}
              onClick={() => setActiveChat(workspaceId, chat.id)}
              onDelete={(e) => handleDelete(e, chat.id)}
            />
          ))
        )}
      </div>
    </aside>
  )
}
