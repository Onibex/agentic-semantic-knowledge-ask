import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Mode, Env } from '@/api/orchestrator'
import type { ChatMessage } from '@/types'

export interface Chat {
  id: string
  title: string
  createdAt: number
  messages: ChatMessage[]
  sessionId: string
}

interface ChatStore {
  workspaceId: string
  env: Env
  mode: Mode
  workspaceChats: Record<string, Chat[]>
  activeChatIds: Record<string, string>
  setWorkspaceId: (id: string) => void
  setEnv: (env: Env) => void
  setMode: (mode: Mode) => void
  createChat: (workspaceId: string) => Chat
  deleteChat: (workspaceId: string, chatId: string) => void
  setActiveChat: (workspaceId: string, chatId: string) => void
  updateChatTitle: (workspaceId: string, chatId: string, title: string) => void
  setChatMessages: (workspaceId: string, chatId: string, messages: ChatMessage[]) => void
}

export const useChatStore = create<ChatStore>()(
  persist(
    (set) => ({
      workspaceId: '',
      env: 'dev',
      mode: 'precise',
      workspaceChats: {},
      activeChatIds: {},

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

      deleteChat: (workspaceId, chatId) =>
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
        }),

      setActiveChat: (workspaceId, chatId) =>
        set((state) => ({
          activeChatIds: { ...state.activeChatIds, [workspaceId]: chatId },
        })),

      updateChatTitle: (workspaceId, chatId, title) =>
        set((state) => ({
          workspaceChats: {
            ...state.workspaceChats,
            [workspaceId]: (state.workspaceChats[workspaceId] ?? []).map((c) =>
              c.id === chatId ? { ...c, title } : c,
            ),
          },
        })),

      setChatMessages: (workspaceId, chatId, messages) =>
        set((state) => ({
          workspaceChats: {
            ...state.workspaceChats,
            [workspaceId]: (state.workspaceChats[workspaceId] ?? []).map((c) =>
              c.id === chatId ? { ...c, messages } : c,
            ),
          },
        })),
    }),
    { name: 'onibex-chat-store' },
  ),
)
