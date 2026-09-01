/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

// Global axios auth wiring for the chat SPA. The api modules (orchestrator.ts,
// admin.ts) call the DEFAULT axios instance directly, so registering the
// interceptors here (imported once from main.tsx) attaches the Keycloak bearer
// to every request and transparently refreshes on a 401 — mirrors ask-studio.
import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '../store/authStore'
import { authConfig } from '../auth/config'

axios.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers = config.headers ?? {}
    config.headers['Authorization'] = `Bearer ${token}`
  }
  return config
})

// One shared in-flight refresh coalesces a burst of concurrent 401s.
let refreshInFlight: Promise<boolean> | null = null

axios.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as
      | (InternalAxiosRequestConfig & { _retry?: boolean })
      | undefined

    if (
      error.response?.status === 401 &&
      original &&
      !original._retry &&
      authConfig.mode !== 'none'
    ) {
      original._retry = true
      if (!refreshInFlight) {
        refreshInFlight = useAuthStore
          .getState()
          .refreshSession()
          .finally(() => {
            refreshInFlight = null
          })
      }
      const refreshed = await refreshInFlight
      if (refreshed) {
        const token = useAuthStore.getState().accessToken
        if (token) {
          original.headers = original.headers ?? {}
          original.headers['Authorization'] = `Bearer ${token}`
        }
        return axios(original)
      }
      useAuthStore.getState().clearSession()
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)
