/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

export interface SapConnectionConfig {
  host: string
  odata_path: string
  username: string
  password?: string
}

export interface SapConnectionResponse {
  config: SapConnectionConfig
}

export interface SapConnectionSaveRequest {
  host: string
  odata_path: string
  username: string
  password?: string
}

export interface TestConnectionResult {
  success: boolean
  message: string
  status_code?: number
  details?: Record<string, unknown>
}

// ── App config (settings.json) ───────────────────────────────────────────────

export interface OpenSearchConfig {
  host?: string
  port?: number
  use_ssl?: boolean
  username?: string
  password?: string
}

export interface HanaConfig {
  host?: string
  port?: number
  schema?: string
  user?: string
  password?: string
}

export interface PostgresConfig {
  host?: string
  port?: number
  database?: string
  schema?: string
  user?: string
  password?: string
}

export interface IasConfig {
  url?: string
  client_id?: string
  client_secret?: string
}

export interface AppConfig {
  db_type?: 'hana' | 'postgresql'
  opensearch?: OpenSearchConfig
  hana?: HanaConfig
  postgresql?: PostgresConfig
  ias?: IasConfig
  deployments?: { llm?: string; embeddings?: string }
  sap_ai_core?: { config_path?: string }
  [key: string]: unknown
}

export interface ConfigGetResponse {
  config: AppConfig
}

export interface ConfigSaveResponse {
  success: boolean
  cleared: string[]
  message: string
}

// ── Setup effective (read-only snapshot: GET /v1/admin/setup/effective) ───────
// One generic section shape per provider. OpenSearch is env-sourced (bootstrap);
// `source` tells the UI where each value came from.

export type ConfigFieldSource = 'environment' | 'file' | 'default' | 'encrypted' | 'plain'

export interface SetupConfigField {
  name: string
  label?: string | null
  value: string // '***' when sensitive
  source: ConfigFieldSource
  sensitive: boolean
  help_text?: string | null
}

export interface SetupConfigSection {
  id: string
  title: string
  provider?: string | null
  provider_label?: string | null
  fields: SetupConfigField[]
  info?: string | null
  test_target?: string | null
}

export interface SetupEffectiveResponse {
  sections: SetupConfigSection[]
}

export interface OpenSearchTestResponse {
  success: boolean
  latency_ms: number
  cluster_name?: string
  status?: string
  detail?: string
  error?: string | null
}

// ── DB connections (multi-DB registry) ──────────────────────────────────────

export interface DbProviderFieldSpec {
  name: string
  sensitive: boolean
  kind: string // 'str' | 'int' | 'bool'
}

export interface DbProviderSpec {
  id: string
  label: string
  fields: DbProviderFieldSpec[]
}

export interface DbProvidersListResponse {
  providers: DbProviderSpec[]
}

export interface DbFieldView {
  name: string
  value: string // '' when sensitive
  sensitive: boolean
  source: 'plain' | 'encrypted' | 'environment' | 'default'
}

export interface DbConnectionView {
  id: string
  name: string
  db_type: string
  fields: DbFieldView[]
  configured: boolean
  updated_at: string
  updated_by: string
}

export interface DbActiveView {
  dev: string | null
  prod: string | null
}

export interface DbConnectionsListResponse {
  connections: DbConnectionView[]
  active: DbActiveView
}

export interface DbConnectionUpsertRequest {
  name: string
  db_type: string
  fields: Record<string, string>
}

export interface DbConnectionDeleteResponse {
  id: string
  deleted: boolean
}

export interface DbConnectionTestResponse {
  id: string
  success: boolean
  db_type: string
  latency_ms: number
  detail: string
  error?: string
}

// ── Provider metadata (shared: GET /v1/admin/secrets/providers) ───────────────

export interface ProviderFieldSpec {
  name: string
  sensitive: boolean
}

export interface ProviderSpec {
  id: string
  label: string
  fields: ProviderFieldSpec[]
}

export interface ProvidersListResponse {
  providers: ProviderSpec[]
}

// Masked field row shared by the LLM-connection + embedder views.
export interface SecretsFieldView {
  name: string
  value: string // '' when sensitive-stored
  sensitive: boolean
  source: 'plain' | 'encrypted' | 'environment' | 'default'
}

// ── LLM connections (multi-LLM registry, ONE active — global, no dev/prod) ────

export interface LlmConnectionView {
  id: string
  name: string
  provider: string
  model: string
  fields: SecretsFieldView[]
  configured: boolean
  updated_at: string
  updated_by: string
}

export interface LlmActiveView {
  active: string | null
}

export interface LlmConnectionsListResponse {
  connections: LlmConnectionView[]
  active: LlmActiveView
}

export interface LlmConnectionUpsertRequest {
  name: string
  provider: string
  model: string
  fields: Record<string, string>
}

export interface LlmConnectionDeleteResponse {
  id: string
  deleted: boolean
}

export interface LlmActivePutRequest {
  active: string | null
}

export interface LlmConnectionTestResponse {
  id: string
  success: boolean
  provider: string
  model: string
  latency_ms: number
  detail: string
  error?: string
}

// ── Embedder (single canonical config — shared with ASK Studio) ────────────────
// GET/PUT /v1/admin/secrets/embedder + POST /v1/admin/secrets/test.

export interface SecretsGetResponse {
  target: 'llm' | 'embedder'
  provider: string
  model: string
  fields: SecretsFieldView[]
  updated_at: string
  updated_by: string
}

export interface SecretsPutRequest {
  provider: string
  model: string
  fields: Record<string, string>
}

export interface SecretsTestRequest {
  target: 'llm' | 'embedder'
}

export interface SecretsTestResponse {
  success: boolean
  target: string
  provider: string
  model: string
  latency_ms: number
  detail: string
  error?: string
}

// ── SAP AI Core service-key upload (legacy plane, kept for D2) ─────────────────

export interface AicoreConfigStatus {
  exists: boolean
  valid?: boolean
  auth_url?: string
  ai_api_url?: string
  client_id_preview?: string
}

export interface AicoreUploadResponse {
  success: boolean
  message: string
  status: AicoreConfigStatus
}

// ── Semantic Dictionary ───────────────────────────────────────────────────────

export interface DictionaryEntry {
  type: string
  canonical_label: string
  technical_name: string
  table?: string
  synonyms?: string
  context_clues?: string
  disambiguation_hint?: string
  module: string
  source_system?: string
  entity_id?: string
  description?: string
  examples?: string
  value_synonyms?: string
  is_preferred_id?: boolean
}

export interface DictionaryListEntry extends DictionaryEntry {
  id?: string
  updated_at?: string
}

export interface DictionaryListResponse {
  entries: DictionaryListEntry[]
}

export interface DictionaryUpsertResponse {
  success: boolean
  message: string
}

export interface DictionaryDeleteResponse {
  success: boolean
  message: string
}

// ── Contracts (api-config.json) ──────────────────────────────────────────────

export interface ContractKey {
  name: string
  type: string
}

export interface ContractField {
  name: string
  type: string
  description: string
  nullable?: boolean
  maxLength?: number
  behavior?: string
}

export interface ContractEntitySet {
  entitySet: string
  urlPath: string
  description: string
  category?: string
  keys: ContractKey[]
  operations: {
    list?: boolean
    get?: boolean
    create?: boolean
    update?: boolean
    delete?: boolean
  }
  fields: ContractField[]
}

export interface ContractApi {
  name: string
  destination?: string
  pathPrefix?: string
  csrfProtected?: boolean
  entitySets: ContractEntitySet[]
  _meta?: {
    title?: string
    version?: string
    filename?: string
  }
}

export interface ContractsConfig {
  server?: Record<string, unknown>
  apis: ContractApi[]
}

export interface ContractsGetResponse {
  config: ContractsConfig
}

export interface ContractsSaveResponse {
  success: boolean
  message: string
}
