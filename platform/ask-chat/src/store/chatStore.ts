/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import axios from 'axios'
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { listChats, getStoredChat, putChat, deleteStoredChat } from '@/api/orchestrator'
import type { Mode, Env, ChatSummary } from '@/api/orchestrator'
import type { ChatMessage } from '@/types'

// Chats are saved per user on the server (/v1/chats), so the same user sees
// them from any browser and nobody else sees them in this one. This store
// holds them in memory; only the browser preferences persist locally.

export interface Chat {
  id: string
  title: string
  createdAt: number
  messages: ChatMessage[]
  sessionId: string
  /** 'summary': listed from the server, messages not fetched yet. */
  sync: 'summary' | 'loaded'
}

export type ListState = 'idle' | 'loading' | 'ready' | 'error'

interface ChatStore {
  workspaceId: string
  env: Env
  mode: Mode
  workspaceChats: Record<string, Chat[]>
  activeChatIds: Record<string, string>
  listState: ListState
  setWorkspaceId: (id: string) => void
  setEnv: (env: Env) => void
  setMode: (mode: Mode) => void
  createChat: (workspaceId: string) => Chat
  setActiveChat: (workspaceId: string, chatId: string) => void
  updateChatTitle: (workspaceId: string, chatId: string, title: string) => void
  setChatMessages: (workspaceId: string, chatId: string, messages: ChatMessage[]) => void
  /** Fetch the user's chats, titles only. */
  loadChats: () => Promise<void>
  /** Fetch the messages of a chat listed from the server. */
  openChat: (workspaceId: string, chatId: string) => Promise<void>
  /** Save the chat as it stands when the save runs. */
  saveChat: (workspaceId: string, chatId: string) => Promise<void>
  /** Remove the chat here at once, then on the server. */
  deleteChat: (workspaceId: string, chatId: string) => Promise<void>
}

// Ids the server holds: listed, or saved from this tab. A chat that never got
// a message is never sent, so deleting it needs no request.
const onServer = new Set<string>()

// Saves and the delete of one chat run one after another, each reading the
// chat when it starts. Without the queue the title save and the messages save
// race, and whichever lands last overwrites the other.
const queues = new Map<string, Promise<void>>()

function enqueue(chatId: string, task: () => Promise<void>): Promise<void> {
  const run = (queues.get(chatId) ?? Promise.resolve()).catch(() => undefined).then(task)
  queues.set(chatId, run)
  const cleanup = () => {
    if (queues.get(chatId) === run) queues.delete(chatId)
  }
  run.then(cleanup, cleanup)
  return run
}

const opening = new Set<string>()

function fromSummary(item: ChatSummary): Chat {
  return {
    id: item.id,
    title: item.title,
    createdAt: Date.parse(item.created_at),
    messages: [],
    sessionId: '',
    sync: 'summary',
  }
}

function findChat(state: ChatStore, workspaceId: string, chatId: string): Chat | undefined {
  return (state.workspaceChats[workspaceId] ?? []).find((c) => c.id === chatId)
}

function updateChat(
  state: ChatStore,
  workspaceId: string,
  chatId: string,
  change: (chat: Chat) => Chat,
): Pick<ChatStore, 'workspaceChats'> {
  return {
    workspaceChats: {
      ...state.workspaceChats,
      [workspaceId]: (state.workspaceChats[workspaceId] ?? []).map((c) =>
        c.id === chatId ? change(c) : c,
      ),
    },
  }
}

export const useChatStore = create<ChatStore>()(
  persist(
    (set, get) => ({
      workspaceId: '',
      env: 'dev',
      mode: 'precise',
      workspaceChats: {},
      activeChatIds: {},
      listState: 'idle',

      setWorkspaceId: (workspaceId) => set({ workspaceId }),
      setEnv: (env) => set({ env }),
      setMode: (mode) => set({ mode }),

      createChat: (workspaceId) => {
        const newChat: Chat = {
          id: crypto.randomUUID(),
          title: 'New Chat',
          createdAt: Date.now(),
          messages: [],
          sessionId: crypto.randomUUID(),
          sync: 'loaded',
        }
        set((state) => ({
          workspaceChats: {
            ...state.workspaceChats,
            [workspaceId]: [newChat, ...(state.workspaceChats[workspaceId] ?? [])],
          },
          activeChatIds: { ...state.activeChatIds, [workspaceId]: newChat.id },
        }))
        return newChat
      },

      setActiveChat: (workspaceId, chatId) =>
        set((state) => ({
          activeChatIds: { ...state.activeChatIds, [workspaceId]: chatId },
        })),

      updateChatTitle: (workspaceId, chatId, title) =>
        set((state) => updateChat(state, workspaceId, chatId, (c) => ({ ...c, title }))),

      setChatMessages: (workspaceId, chatId, messages) =>
        set((state) => updateChat(state, workspaceId, chatId, (c) => ({ ...c, messages }))),

      loadChats: async () => {
        set({ listState: 'loading' })
        try {
          const items = await listChats()
          set((state) => {
            // Chats started in this tab before the list arrived stay, first.
            const next: Record<string, Chat[]> = {}
            for (const [ws, chats] of Object.entries(state.workspaceChats)) {
              const unsent = chats.filter((c) => !onServer.has(c.id))
              if (unsent.length) next[ws] = unsent
            }
            for (const item of items) {
              onServer.add(item.id)
              ;(next[item.workspace_id] ??= []).push(fromSummary(item))
            }
            return { workspaceChats: next, listState: 'ready' }
          })
        } catch {
          set({ listState: 'error' })
        }
      },

      openChat: async (workspaceId, chatId) => {
        const chat = findChat(get(), workspaceId, chatId)
        if (!chat || chat.sync !== 'summary' || opening.has(chatId)) return
        opening.add(chatId)
        try {
          const stored = await getStoredChat(chatId)
          const data = stored.data as { sessionId?: string; messages?: ChatMessage[] }
          set((state) =>
            updateChat(state, workspaceId, chatId, (c) => ({
              ...c,
              title: stored.title,
              messages: data.messages ?? [],
              sessionId: data.sessionId || crypto.randomUUID(),
              sync: 'loaded',
            })),
          )
        } finally {
          opening.delete(chatId)
        }
      },

      saveChat: (workspaceId, chatId) =>
        enqueue(chatId, async () => {
          const chat = findChat(get(), workspaceId, chatId)
          // Deleted meanwhile, messages not fetched, or nothing said yet.
          if (!chat || chat.sync !== 'loaded' || chat.messages.length === 0) return
          await putChat(chatId, {
            workspace_id: workspaceId,
            title: chat.title,
            data: { sessionId: chat.sessionId, messages: chat.messages },
          })
          onServer.add(chatId)
        }),

      deleteChat: (workspaceId, chatId) => {
        set((state) => {
          const existing = state.workspaceChats[workspaceId] ?? []
          const updated = existing.filter((c) => c.id !== chatId)
          const activeId = state.activeChatIds[workspaceId]
          let newActiveId = activeId
          if (activeId === chatId) {
            const idx = existing.findIndex((c) => c.id === chatId)
            // Prefer the item that fills the same slot after removal, then the one before
            newActiveId = (updated[idx] ?? updated[idx - 1])?.id ?? ''
          }
          return {
            workspaceChats: { ...state.workspaceChats, [workspaceId]: updated },
            activeChatIds: { ...state.activeChatIds, [workspaceId]: newActiveId },
          }
        })
        return enqueue(chatId, async () => {
          if (!onServer.has(chatId)) return
          try {
            await deleteStoredChat(chatId)
          } catch (err) {
            // Already gone is what we wanted.
            if (!(axios.isAxiosError(err) && err.response?.status === 404)) throw err
          }
          onServer.delete(chatId)
        })
      },
    }),
    {
      name: 'onibex-chat-store',
      // Version 1 moved the chats to the server. Only these preferences stay
      // in the browser, and migrating from 0 drops the chats the old version
      // stored here, so they do not linger for the next user of this browser.
      version: 1,
      partialize: (state) => ({
        workspaceId: state.workspaceId,
        env: state.env,
        mode: state.mode,
        activeChatIds: state.activeChatIds,
      }),
      migrate: (persisted) => {
        const old = (persisted ?? {}) as Partial<ChatStore>
        return {
          workspaceId: old.workspaceId ?? '',
          env: old.env ?? 'dev',
          mode: old.mode ?? 'precise',
          activeChatIds: {},
        }
      },
    },
  ),
)
