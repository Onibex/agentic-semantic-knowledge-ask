/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import axios, { type AxiosError } from 'axios'
import type {
  SapConnectionResponse,
  SapConnectionSaveRequest,
  TestConnectionResult,
  ConfigGetResponse,
  ConfigSaveResponse,
  SetupEffectiveResponse,
  OpenSearchTestResponse,
  AicoreConfigStatus,
  AicoreUploadResponse,
  DictionaryEntry,
  DictionaryListResponse,
  DictionaryUpsertResponse,
  ContractsConfig,
  DbProvidersListResponse,
  DbConnectionsListResponse,
  DbConnectionView,
  DbConnectionUpsertRequest,
  DbConnectionDeleteResponse,
  DbActiveView,
  DbConnectionTestResponse,
  ProvidersListResponse,
  LlmConnectionsListResponse,
  LlmConnectionView,
  LlmConnectionUpsertRequest,
  LlmConnectionDeleteResponse,
  LlmActiveView,
  LlmConnectionTestResponse,
  SecretsGetResponse,
  SecretsPutRequest,
  SecretsTestResponse,
} from './types'
import { useAuthStore } from '@/store/authStore'
import { authConfig } from '@/auth/config'

const http = axios.create({ baseURL: '/api/admin' })

http.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 401 -> one silent refresh + replay, else bounce to /login (mirrors admin-spa).
let refreshInFlight: Promise<boolean> | null = null
http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as (typeof error.config & { _retry?: boolean }) | undefined
    if (error.response?.status === 401 && original && !original._retry && authConfig.mode !== 'none') {
      original._retry = true
      if (!refreshInFlight) {
        refreshInFlight = useAuthStore
          .getState()
          .refreshSession()
          .finally(() => {
            refreshInFlight = null
          })
      }
      if (await refreshInFlight) {
        const token = useAuthStore.getState().accessToken
        if (token && original.headers) original.headers.Authorization = `Bearer ${token}`
        return http(original)
      }
      useAuthStore.getState().clearSession()
      if (!window.location.pathname.startsWith('/login')) window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)

function extractError(err: unknown): string {
  const e = err as AxiosError<{ detail?: string }>
  return e.response?.data?.detail ?? e.message ?? 'Unknown error'
}

export const sapApi = {
  get: async (): Promise<SapConnectionResponse> => {
    try {
      const res = await http.get<SapConnectionResponse>('/sap-connection')
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  save: async (body: SapConnectionSaveRequest): Promise<SapConnectionResponse> => {
    try {
      const res = await http.put<SapConnectionResponse>('/sap-connection', body)
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  test: async (): Promise<TestConnectionResult> => {
    try {
      const res = await http.post<{ ok: boolean; status_code?: number; message: string }>('/sap-connection/test')
      return {
        success: res.data.ok,
        status_code: res.data.status_code,
        message: res.data.message,
      }
    } catch (err) {
      const e = err as AxiosError<{ detail?: string; message?: string }>
      return {
        success: false,
        message: e.response?.data?.detail ?? e.response?.data?.message ?? e.message ?? 'Connection failed',
      }
    }
  },
}

export const dictionaryApi = {
  list: async (module?: string, typeFilter = 'phrase'): Promise<DictionaryListResponse> => {
    try {
      const params: Record<string, string> = { type_filter: typeFilter }
      if (module) params.module = module
      const res = await http.get<DictionaryListResponse>('/dictionary', { params })
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  upsert: async (entry: DictionaryEntry): Promise<DictionaryUpsertResponse> => {
    try {
      const res = await http.post<DictionaryUpsertResponse>('/dictionary', entry)
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  delete: async (id: string): Promise<{ success: boolean; message: string }> => {
    try {
      const res = await http.delete<{ success: boolean; message: string }>(`/dictionary/${id}`)
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },
}

export const contractsApi = {
  get: async (): Promise<ContractsConfig> => {
    try {
      const res = await http.get<{ config: ContractsConfig }>('/contracts')
      return res.data.config
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  save: async (config: ContractsConfig): Promise<{ success: boolean; message: string }> => {
    try {
      const res = await http.post<{ success: boolean; message: string }>('/contracts', { config })
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },
}

export const mcpApi = {
  test: async (): Promise<{ ok: boolean; status_code?: number; message: string }> => {
    try {
      const res = await http.post<{ ok: boolean; status_code?: number; message: string }>('/mcp/test')
      return res.data
    } catch (err) {
      const e = err as AxiosError<{ detail?: string }>
      return { ok: false, message: e.response?.data?.detail ?? e.message ?? 'Test failed' }
    }
  },

  restart: async (): Promise<{ ok: boolean; message: string }> => {
    try {
      const res = await http.post<{ ok: boolean; message: string }>('/mcp/restart')
      return res.data
    } catch (err) {
      const e = err as AxiosError<{ detail?: string }>
      return { ok: false, message: e.response?.data?.detail ?? e.message ?? 'Restart failed' }
    }
  },
}

export const configApi = {
  get: async (): Promise<ConfigGetResponse> => {
    try {
      const res = await http.get<ConfigGetResponse>('/config')
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  save: async (partial: Record<string, unknown>): Promise<ConfigSaveResponse> => {
    try {
      const res = await http.post<ConfigSaveResponse>('/config', { config: partial })
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },
}

// Read-only effective config snapshot + OpenSearch health probe.
// OpenSearch connection is env-sourced (bootstrap store) — this SPA displays it,
// it does not edit it. Config lives in .env / K8s Secret.
export const setupApi = {
  effective: async (): Promise<SetupEffectiveResponse> => {
    try {
      const res = await http.get<SetupEffectiveResponse>('/setup/effective')
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  testOpensearch: async (): Promise<OpenSearchTestResponse> => {
    try {
      const res = await http.post<OpenSearchTestResponse>('/setup/test/opensearch')
      return res.data
    } catch (err) {
      const e = err as AxiosError<{ detail?: string }>
      return {
        success: false,
        latency_ms: 0,
        detail: 'Could not reach OpenSearch',
        error: e.response?.data?.detail ?? e.message ?? 'Test failed',
      }
    }
  },
}

export const dbApi = {
  providers: async (): Promise<DbProvidersListResponse> => {
    try {
      const res = await http.get<DbProvidersListResponse>('/secrets/db/providers')
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  list: async (): Promise<DbConnectionsListResponse> => {
    try {
      const res = await http.get<DbConnectionsListResponse>('/secrets/db/connections')
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  create: async (body: DbConnectionUpsertRequest): Promise<DbConnectionView> => {
    try {
      const res = await http.post<DbConnectionView>('/secrets/db/connections', body)
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  update: async (id: string, body: DbConnectionUpsertRequest): Promise<DbConnectionView> => {
    try {
      const res = await http.put<DbConnectionView>(`/secrets/db/connections/${id}`, body)
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  remove: async (id: string): Promise<DbConnectionDeleteResponse> => {
    try {
      const res = await http.delete<DbConnectionDeleteResponse>(`/secrets/db/connections/${id}`)
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  setActive: async (body: { dev: string | null; prod: string | null }): Promise<DbActiveView> => {
    try {
      const res = await http.put<DbActiveView>('/secrets/db/connections/active', body)
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  test: async (id: string): Promise<DbConnectionTestResponse> => {
    try {
      const res = await http.post<DbConnectionTestResponse>(`/secrets/db/connections/${id}/test`)
      return res.data
    } catch (err) {
      const e = err as AxiosError<{ detail?: string }>
      return {
        id,
        success: false,
        db_type: '',
        latency_ms: 0,
        detail: 'Test failed',
        error: e.response?.data?.detail ?? e.message ?? 'Test failed',
      }
    }
  },
}

// Shared provider registry (drives both the LLM-connection form + embedder form).
export const providersApi = {
  list: async (): Promise<ProvidersListResponse> => {
    try {
      const res = await http.get<ProvidersListResponse>('/secrets/providers')
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },
}

// LLM connection registry — N connections, one active (global, no dev/prod).
export const llmConnApi = {
  providers: providersApi.list,

  list: async (): Promise<LlmConnectionsListResponse> => {
    try {
      const res = await http.get<LlmConnectionsListResponse>('/secrets/llm/connections')
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  create: async (body: LlmConnectionUpsertRequest): Promise<LlmConnectionView> => {
    try {
      const res = await http.post<LlmConnectionView>('/secrets/llm/connections', body)
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  update: async (id: string, body: LlmConnectionUpsertRequest): Promise<LlmConnectionView> => {
    try {
      const res = await http.put<LlmConnectionView>(`/secrets/llm/connections/${id}`, body)
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  remove: async (id: string): Promise<LlmConnectionDeleteResponse> => {
    try {
      const res = await http.delete<LlmConnectionDeleteResponse>(`/secrets/llm/connections/${id}`)
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  setActive: async (active: string | null): Promise<LlmActiveView> => {
    try {
      const res = await http.put<LlmActiveView>('/secrets/llm/connections/active', { active })
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  test: async (id: string): Promise<LlmConnectionTestResponse> => {
    try {
      const res = await http.post<LlmConnectionTestResponse>(`/secrets/llm/connections/${id}/test`)
      return res.data
    } catch (err) {
      const e = err as AxiosError<{ detail?: string }>
      return {
        id,
        success: false,
        provider: '',
        model: '',
        latency_ms: 0,
        detail: 'Test failed',
        error: e.response?.data?.detail ?? e.message ?? 'Test failed',
      }
    }
  },
}

// Embedder — single canonical config, shared with ASK Studio (/secrets/embedder).
export const embedderApi = {
  providers: providersApi.list,

  get: async (): Promise<SecretsGetResponse> => {
    try {
      const res = await http.get<SecretsGetResponse>('/secrets/embedder')
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  save: async (body: SecretsPutRequest): Promise<SecretsGetResponse> => {
    try {
      const res = await http.put<SecretsGetResponse>('/secrets/embedder', body)
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  test: async (): Promise<SecretsTestResponse> => {
    try {
      const res = await http.post<SecretsTestResponse>('/secrets/test', { target: 'embedder' })
      return res.data
    } catch (err) {
      const e = err as AxiosError<{ detail?: string }>
      return {
        success: false,
        target: 'embedder',
        provider: '',
        model: '',
        latency_ms: 0,
        detail: 'Test failed',
        error: e.response?.data?.detail ?? e.message ?? 'Test failed',
      }
    }
  },
}

// SAP AI Core service-key upload (legacy plane, kept for the managed provider).
export const llmApi = {
  getAicoreStatus: async (): Promise<AicoreConfigStatus> => {
    try {
      const res = await http.get<AicoreConfigStatus>('/llm/aicore/config')
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  getAicoreDeployments: async (): Promise<{ deployments: { deployment_id: string; model_name: string }[] }> => {
    try {
      const res = await http.get('/llm/aicore/deployments')
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },

  uploadAicore: async (file: File): Promise<AicoreUploadResponse> => {
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await http.post<AicoreUploadResponse>('/llm/aicore/config', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return res.data
    } catch (err) {
      throw new Error(extractError(err))
    }
  },
}
