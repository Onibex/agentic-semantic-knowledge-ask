import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';
import type {
  YAMLLayer,
  YAMLNode,
  YAMLNodeSummary,
  YAMLUpdateRequest,
  MergeResult,
  ConflictBlock,
  ConflictDecision,
  HistoryResponse,
  HistoryBranch,
  DiffResult,
  StatsResponse,
  PhraseEntry,
  DictionaryListResponse,
  UpsertResponse,
  AppSettings,
  ConfigResponse,
  ConfigSaveResponse,
  LightweightEntity,
  CatalogResponse,
  DeletionResult,
  ImportYamlResult,
  IngestionResult,
  IndexWorkspaceResult,
  ResetIndicesResult,
  ConnectionTestResult,
  ContractsConfig,
  ContractsSaveResponse,
  DocIngestResult,
  AicoreConfigStatus,
  AicoreConfigUploadResponse,
  DeploymentInfo,
  DeploymentListResponse,
  EffectiveLLMConfig,
  ProviderConfigRequest,
  TestProviderRequest,
  TestProviderResponse,
  SetupEffectiveResponse,
  OpenSearchTestResponse,
  DatabaseTestRequest,
  DatabaseTestResult,
  Workspace,
  WorkspaceCreatePayload,
  WorkspaceUpdatePayload,
  BusinessDomain,
  BusinessDomainCreatePayload,
  BusinessDomainUpdatePayload,
  DataProductLifecycle,
  DataProductStatus,
  DdlImportResult,
  DomainPublishResult,
  DomainPublishStreamEvent,
  PublishEnvResult,
  UnpublishEnvResult,
  Organization,
  OrganizationUpdatePayload,
  SecretsTarget,
  SecretsGetResponse,
  SecretsPutRequest,
  SecretsTestRequest,
  SecretsTestResponse,
  ProvidersListResponse,
  PromptKey,
  SystemPromptResponse,
  SystemPromptUpdateRequest,
  EnrichEntityScopeDefaults,
  EnrichEntityRequest,
  EnrichEntityResponse,
  PromptPreviewRequest,
  PromptPreviewResponse,
  RelationshipSuggestRequest,
  RelationshipSuggestResponse,
  EnrichFieldRequest,
  EnrichFieldResponse,
  EnrichEntityDraftRequest,
  EnrichFieldDraftRequest,
  RelationshipSuggestDraftRequest,
  DeriveYamlResult,
  SourceProfile,
} from './types';
import { useAuthStore } from '../store/authStore';
import { authConfig } from '../auth/config';

const http = axios.create({ baseURL: '/api' });

http.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  if (token) {
    config.headers = config.headers ?? {};
    config.headers['Authorization'] = `Bearer ${token}`;
  }
  return config;
});

// ─── 401 / token-expiry handling ────────────────────────────────────────────
// When an access token expires mid-session the backend answers 401. Instead of
// surfacing a raw error, try a one-shot silent refresh and replay the request;
// if that fails the session is dead, so clear it and send the user to /login.
// A single in-flight refresh is shared across concurrent 401s so a burst of
// requests that all expire together triggers exactly one refresh round-trip.
let refreshInFlight: Promise<boolean> | null = null;

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as
      | (InternalAxiosRequestConfig & { _retry?: boolean })
      | undefined;

    if (
      error.response?.status === 401 &&
      original &&
      !original._retry &&
      authConfig.mode !== 'none'
    ) {
      original._retry = true;

      // Coalesce concurrent 401s into a single refresh round-trip; clear the
      // shared promise once it settles so a later expiry can refresh again.
      if (!refreshInFlight) {
        refreshInFlight = useAuthStore
          .getState()
          .refreshSession()
          .finally(() => {
            refreshInFlight = null;
          });
      }
      const refreshed = await refreshInFlight;

      if (refreshed) {
        const token = useAuthStore.getState().accessToken;
        if (token) {
          original.headers = original.headers ?? {};
          original.headers['Authorization'] = `Bearer ${token}`;
        }
        return http(original);
      }

      // Refresh impossible/failed → bounce to login rather than show a 401.
      useAuthStore.getState().clearSession();
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login';
      }
    }

    return Promise.reject(error);
  },
);

export interface ListYamlsOptions {
  layer?: YAMLLayer;
  /** Workspace UUID or slug — server scopes the listing to the workspace's DPs + 1-hop neighbors. */
  workspace?: string | null;
  /** Business Domain id — server scopes to that single domain's DPs + 1-hop (domain canvas, §03). Narrower than `workspace`. */
  businessDomain?: string | null;
}

export async function listYamls(
  optsOrLayer?: ListYamlsOptions | YAMLLayer,
): Promise<YAMLNodeSummary[]> {
  // Back-compat: callers used to pass a layer string directly.
  const opts: ListYamlsOptions = typeof optsOrLayer === 'string'
    ? { layer: optsOrLayer }
    : optsOrLayer ?? {};
  const params: Record<string, string> = {};
  if (opts.layer) params.layer = opts.layer;
  if (opts.workspace) params.workspace = opts.workspace;
  if (opts.businessDomain) params.business_domain = opts.businessDomain;
  const { data } = await http.get<YAMLNodeSummary[]>('/yamls', { params });
  return data;
}

export async function getYaml(id: string): Promise<YAMLNode> {
  const { data } = await http.get<YAMLNode>(`/yamls/${encodeURIComponent(id)}`);
  return data;
}

/**
 * Full nodes for a workspace OR business-domain scope in ONE request — the graph
 * needs each node's composed_of + relationships for the edges. Replaces the old
 * listYamls + N x getYaml pattern (each getYaml rglobbed the whole workspace =
 * O(N x files)); the backend resolves the scope and returns all nodes in a
 * single pass. `businessDomain` wins when both are set (narrower).
 */
export async function listScopedYamls(opts: {
  workspace?: string | null;
  businessDomain?: string | null;
}): Promise<YAMLNode[]> {
  const params: Record<string, string> = {};
  if (opts.businessDomain) params.business_domain = opts.businessDomain;
  else if (opts.workspace) params.workspace = opts.workspace;
  const { data } = await http.get<YAMLNode[]>('/yamls/scoped', { params });
  return data;
}

export async function updateYaml(id: string, req: YAMLUpdateRequest): Promise<YAMLNode> {
  const { data } = await http.put<YAMLNode>(`/yamls/${encodeURIComponent(id)}`, req);
  return data;
}

export async function getYamlHistory(
  id: string,
  page = 1,
  pageSize = 20,
  branch: HistoryBranch = 'working',
): Promise<HistoryResponse> {
  const { data } = await http.get<HistoryResponse>(`/yamls/${encodeURIComponent(id)}/history`, {
    params: { page, per_page: pageSize, branch },
  });
  return data;
}

// Iter 5 — Merge API
export async function ingestSapJson(
  payload: Record<string, unknown>,
  authorEmail: string,
): Promise<MergeResult> {
  const { data } = await http.post<MergeResult>('/ingest/sap-json', {
    payload,
    author_email: authorEmail,
  });
  return data;
}

export async function getConflicts(
  id: string,
  includeResolved = false,
): Promise<ConflictBlock[]> {
  const { data } = await http.get<ConflictBlock[]>(
    `/yamls/${encodeURIComponent(id)}/conflicts`,
    { params: { include_resolved: includeResolved } },
  );
  return data;
}

export async function getPendingConflictsWorkspace(): Promise<ConflictBlock[]> {
  const { data } = await http.get<ConflictBlock[]>('/conflicts/pending');
  return data;
}

export async function resolveConflict(
  yamlId: string,
  conflictId: string,
  decision: ConflictDecision,
  authorEmail: string,
): Promise<YAMLNode> {
  const { data } = await http.post<YAMLNode>(
    `/yamls/${encodeURIComponent(yamlId)}/conflicts/${encodeURIComponent(conflictId)}/resolve`,
    { decision, author_email: authorEmail },
  );
  return data;
}

// Bulk resolution — one request, one YAML write, one commit. The fast path
// for upload-first ingests where a whole export's differences land at once.
export async function resolveConflictsBulk(
  yamlId: string,
  resolutions: { conflict_id: string; decision: ConflictDecision }[],
  authorEmail: string,
): Promise<YAMLNode> {
  const { data } = await http.post<YAMLNode>(
    `/yamls/${encodeURIComponent(yamlId)}/conflicts/resolve-bulk`,
    { resolutions, author_email: authorEmail },
  );
  return data;
}

// Iter 6 — Additional history API
export async function getYamlAtCommit(id: string, sha: string): Promise<YAMLNode> {
  const { data } = await http.get<YAMLNode>(
    `/yamls/${encodeURIComponent(id)}/history/${encodeURIComponent(sha)}`,
  );
  return data;
}

export async function getYamlDiff(
  id: string,
  fromSha: string,
  toSha: string,
): Promise<DiffResult> {
  const { data } = await http.get<DiffResult>(`/yamls/${encodeURIComponent(id)}/diff`, {
    params: { from_sha: fromSha, to_sha: toSha },
  });
  return data;
}

export interface DiffWithLastPublishResult {
  yaml_id: string;
  env: 'dev' | 'prod' | null;
  last_publish_sha: string | null;
  unified_diff: string;
}

/**
 * Diff the workspace HEAD against what is published to `env` (dev/prod). The
 * baseline is the last `publish-<env>(<id>)` commit on that env's branch — so
 * the comparison is environment-explicit. Omitting `env` falls back to the
 * legacy runtime-index publish.
 */
export async function getDiffWithLastPublish(
  id: string,
  env?: 'dev' | 'prod',
): Promise<DiffWithLastPublishResult> {
  const { data } = await http.get<DiffWithLastPublishResult>(
    `/yamls/${encodeURIComponent(id)}/diff-with-last-publish`,
    { params: env ? { env } : undefined },
  );
  return data;
}

export async function restoreYaml(
  id: string,
  sha: string,
  authorEmail: string,
  reason?: string,
): Promise<YAMLNode> {
  const { data } = await http.post<YAMLNode>(
    `/yamls/${encodeURIComponent(id)}/restore/${encodeURIComponent(sha)}`,
    { author_email: authorEmail, reason },
  );
  return data;
}

// Iter 7 — Search, bulk state, stats, export
export async function searchYamls(q: string): Promise<YAMLNodeSummary[]> {
  const { data } = await http.get<YAMLNodeSummary[]>('/yamls/search', { params: { q } });
  return data;
}

export async function getStats(): Promise<StatsResponse> {
  const { data } = await http.get<StatsResponse>('/stats');
  return data;
}

/**
 * Download the full YAML workspace as a ZIP through the authenticated axios
 * client, so the Bearer token is attached. A plain `<a href>` navigation is
 * NOT authenticated (the token lives in sessionStorage, not a cookie) and the
 * guarded `/v1/viz/export` endpoint answers 401.
 */
export async function exportYamls(): Promise<Blob> {
  const { data } = await http.get<Blob>('/export', { responseType: 'blob' });
  return data;
}

// Dictionary API
export async function listPhrases(): Promise<PhraseEntry[]> {
  const { data } = await http.get<DictionaryListResponse>('/admin/dictionary', {
    params: { type_filter: 'phrase' },
  });
  return data.entries;
}

export async function upsertPhrase(entry: PhraseEntry): Promise<UpsertResponse> {
  const { data } = await http.post<UpsertResponse>('/admin/dictionary', entry);
  return data;
}

export async function deletePhrase(id: string): Promise<void> {
  await http.delete(`/admin/dictionary/${encodeURIComponent(id)}`);
}

// Config API
export async function getConfig(): Promise<AppSettings> {
  const { data } = await http.get<ConfigResponse>('/admin/config');
  return data.config;
}

export async function saveConfig(config: AppSettings): Promise<ConfigSaveResponse> {
  const { data } = await http.post<ConfigSaveResponse>('/admin/config', { config });
  return data;
}

// Knowledge Graph API
export async function getCatalog(): Promise<LightweightEntity[]> {
  const { data } = await http.get<CatalogResponse>('/admin/yaml/catalog');
  return data.entities;
}

export async function deleteKgEntity(id: string): Promise<DeletionResult> {
  const { data } = await http.delete<DeletionResult>(`/admin/yaml/${encodeURIComponent(id)}`);
  return data;
}

// Phase C2 — code-defined source-system profiles for the DDL form selector.
export async function getSourceProfiles(): Promise<SourceProfile[]> {
  const { data } = await http.get<SourceProfile[]>('/admin/source-profiles');
  return data;
}

// Effective (env-resolved) deployment ingestion config. `column_naming`
// decides how the Manual-entity form derives Silver/Gold field names from a
// composed Bronze: 'technical' -> <fldname>_<tabname>, 'alias' -> <alias>_<tabname>.
export interface IngestConfig {
  column_naming: 'technical' | 'alias';
}

export async function getIngestConfig(): Promise<IngestConfig> {
  const { data } = await http.get<IngestConfig>('/admin/ingest-config');
  return data;
}

// Iter 6 (CH-6) — DDL → YAML: deterministic skeleton for typed tables, AI for
// semantics/views. Lands each entity in the workspace (In Review). `module`
// drives the silver/gold workspace path — a user-chosen value the backend
// backstops deterministically, so imports never fail on a missing module.
export async function importDdl(
  ddl: string,
  layer: 'bronze' | 'silver' | 'gold',
  sourceSystem = 's4h',
  force = false,
  context = '',
  module = 'gen',
): Promise<DdlImportResult> {
  const { data } = await http.post<DdlImportResult>(
    '/admin/yaml/import/ddl',
    { ddl, layer, source_system: sourceSystem, force, context, module },
    { timeout: 300_000 },
  );
  return data;
}

// Pass I — workspace-only YAML import. Lands the YAML in ./workspace/ and
// commits to git. To publish to the runtime catalog, the admin separately
// clicks Publish in Graph (or POST /admin/yaml/index/{id}).
export async function importYamlToWorkspace(
  yamlContent: string,
  force = false,
): Promise<ImportYamlResult> {
  const { data } = await http.post<ImportYamlResult>(
    '/admin/yaml/import',
    { yaml_content: yamlContent, force },
    { timeout: 60_000 },
  );
  return data;
}

// Publish workspace YAMLs → runtime index. SAP JSON no longer ingests directly
// to OpenSearch here — it enters via the visualizer's SAP Updates (merge) flow,
// then the curated/production YAMLs are published with these:
export async function indexEntity(id: string): Promise<IngestionResult> {
  const { data } = await http.post<IngestionResult>(
    `/admin/yaml/index/${encodeURIComponent(id)}`,
    {},
    { timeout: 300_000 },
  );
  return data;
}

export async function indexWorkspace(layers?: string[]): Promise<IndexWorkspaceResult> {
  const { data } = await http.post<IndexWorkspaceResult>(
    '/admin/yaml/index-workspace',
    { layers },
    { timeout: 600_000 },
  );
  return data;
}

/**
 * Lightweight published-ids list — the ids currently deployed to an env's
 * runtime registry (`ask-entity-registry-v1-{env}`). Used by Graph / Domain
 * Canvas to paint per-node "Published / Unpublished" chips. Defaults to `dev`:
 * dev is the first deployment target (prod requires a dev publish first), so
 * "present in dev" is the coarse "is this live anywhere" signal the chip wants.
 * This is a DEPLOYMENT query — distinct from the catalog browse, which reads
 * the working YAMLs.
 */
export async function getPublishedIds(env: 'dev' | 'prod' = 'dev'): Promise<string[]> {
  const { data } = await http.get<{ ids: string[] }>('/admin/yaml/published-ids', {
    params: { env },
  });
  return data.ids ?? [];
}

/**
 * Per-file outcome for the multi-upload flow.
 *
 * The backend's POST /admin/yaml/import is single-file; this helper runs
 * one request per file so we can render per-file status (success / conflict /
 * validation error) without needing a new bulk endpoint.
 */
export interface UploadYamlOutcome {
  filename: string;
  status: 'created' | 'overwritten' | 'conflict' | 'invalid' | 'error';
  entity_id?: string;
  layer?: string;
  message?: string;
}

export async function uploadYamlFile(
  file: File,
  force: boolean,
): Promise<UploadYamlOutcome> {
  const content = await file.text();
  try {
    const result = await importYamlToWorkspace(content, force);
    return {
      filename: file.name,
      status: result.overwritten ? 'overwritten' : 'created',
      entity_id: result.entity_id,
      layer: result.layer,
    };
  } catch (err: unknown) {
    // Axios errors carry status + detail in response.data.detail per FastAPI convention.
    const ax = err as { response?: { status?: number; data?: { detail?: string } }; message?: string };
    const status = ax.response?.status;
    const detail = ax.response?.data?.detail ?? ax.message ?? 'Upload failed';
    if (status === 409) return { filename: file.name, status: 'conflict', message: detail };
    if (status === 422) return { filename: file.name, status: 'invalid', message: detail };
    return { filename: file.name, status: 'error', message: detail };
  }
}

export async function resetKgIndices(): Promise<ResetIndicesResult> {
  const { data } = await http.post<ResetIndicesResult>('/admin/yaml/reset-indices', {});
  return data;
}

export async function testSapConnection(): Promise<ConnectionTestResult> {
  const { data } = await http.post<ConnectionTestResult>('/admin/sap-connection/test', {});
  return data;
}

export async function testMcpConnection(): Promise<ConnectionTestResult> {
  const { data } = await http.post<ConnectionTestResult>('/admin/mcp/test', {});
  return data;
}

// Contracts
export async function getContracts(): Promise<ContractsConfig> {
  const { data } = await http.get<{ config: ContractsConfig }>('/admin/contracts');
  return data.config;
}

export async function saveContracts(config: ContractsConfig): Promise<ContractsSaveResponse> {
  const { data } = await http.post<ContractsSaveResponse>('/admin/contracts', { config });
  return data;
}

// AI Core (now under /admin/llm/aicore/*)
export async function getAicoreStatus(): Promise<AicoreConfigStatus> {
  const { data } = await http.get<AicoreConfigStatus>('/admin/llm/aicore/config');
  return data;
}

export async function uploadAicoreConfig(file: File): Promise<AicoreConfigUploadResponse> {
  const form = new FormData();
  form.append('file', file);
  const { data } = await http.post<AicoreConfigUploadResponse>('/admin/llm/aicore/config', form);
  return data;
}

export async function listAicoreDeployments(): Promise<DeploymentInfo[]> {
  const { data } = await http.get<DeploymentListResponse>('/admin/llm/aicore/deployments');
  return data.deployments;
}

// ── Multi-provider LLM + Embedder config ────────────────────────────────────
// New generic endpoints (Tier 2): one shape for SAP AI Core (managed) and for
// LiteLLM (direct — OpenAI, Anthropic, Azure, Databricks, Bedrock, …).
export async function getEffectiveLLMConfig(): Promise<EffectiveLLMConfig> {
  const { data } = await http.get<EffectiveLLMConfig>('/admin/llm/config');
  return data;
}

export async function saveProviderConfig(body: ProviderConfigRequest): Promise<{ status: string; message: string }> {
  const { data } = await http.post<{ status: string; message: string }>('/admin/llm/config', body);
  return data;
}

export async function testProviderConnection(body: TestProviderRequest): Promise<TestProviderResponse> {
  const { data } = await http.post<TestProviderResponse>('/admin/llm/test', body);
  return data;
}

// ── Setup Effective (read-only snapshot for the SPA's Setup page) ──────────

export async function getSetupEffective(): Promise<SetupEffectiveResponse> {
  const { data } = await http.get<SetupEffectiveResponse>('/admin/setup/effective');
  return data;
}

export async function testOpenSearchConnection(): Promise<OpenSearchTestResponse> {
  const { data } = await http.post<OpenSearchTestResponse>('/admin/setup/test/opensearch', {});
  return data;
}

// ── Encrypted secrets (LLM + Embedder write path) ──────────────────────────

export async function listSecretsProviders(): Promise<ProvidersListResponse> {
  const { data } = await http.get<ProvidersListResponse>('/admin/secrets/providers');
  return data;
}

export async function getSecrets(target: SecretsTarget): Promise<SecretsGetResponse> {
  const { data } = await http.get<SecretsGetResponse>(`/admin/secrets/${target}`);
  return data;
}

export async function putSecrets(
  target: SecretsTarget,
  body: SecretsPutRequest,
): Promise<SecretsGetResponse> {
  const { data } = await http.put<SecretsGetResponse>(`/admin/secrets/${target}`, body);
  return data;
}

export async function testSecrets(body: SecretsTestRequest): Promise<SecretsTestResponse> {
  const { data } = await http.post<SecretsTestResponse>('/admin/secrets/test', body);
  return data;
}

// ── Editable system prompts ────────────────────────────────────────────────

export async function getSystemPrompt(key: PromptKey): Promise<SystemPromptResponse> {
  const { data } = await http.get<SystemPromptResponse>(
    `/admin/prompts/${encodeURIComponent(key)}`,
  );
  return data;
}

export async function putSystemPrompt(
  key: PromptKey,
  body: SystemPromptUpdateRequest,
): Promise<SystemPromptResponse> {
  const { data } = await http.put<SystemPromptResponse>(
    `/admin/prompts/${encodeURIComponent(key)}`,
    body,
  );
  return data;
}

// ── AI Enrichment ──────────────────────────────────────────────────────────

export async function getEnrichmentScopeDefaults(
  entityId: string,
  workspaceId?: string | null,
): Promise<EnrichEntityScopeDefaults> {
  const params: Record<string, string> = {};
  if (workspaceId) params.workspace_id = workspaceId;
  const { data } = await http.get<EnrichEntityScopeDefaults>(
    `/admin/enrich/entity/${encodeURIComponent(entityId)}/scope-defaults`,
    { params },
  );
  return data;
}

export async function previewEntityEnrichment(
  body: EnrichEntityRequest,
): Promise<EnrichEntityResponse> {
  const { data } = await http.post<EnrichEntityResponse>(
    '/admin/enrich/entity/preview',
    body,
  );
  return data;
}

export async function previewFieldEnrichment(
  body: EnrichFieldRequest,
): Promise<EnrichFieldResponse> {
  const { data } = await http.post<EnrichFieldResponse>('/admin/enrich/field', body);
  return data;
}

/**
 * Return the EXACT (system, user) messages the AI Assist endpoint would
 * send to the LLM for the supplied scope — no LLM call, no tokens spent.
 * Used by the Show-full-prompt dialog to give admins full transparency.
 */
export async function previewEnrichmentPrompt(
  entityId: string,
  body: PromptPreviewRequest,
): Promise<PromptPreviewResponse> {
  const { data } = await http.post<PromptPreviewResponse>(
    `/admin/enrich/entity/${encodeURIComponent(entityId)}/prompt-preview`,
    body,
  );
  return data;
}

/**
 * Modo 2 (Complete) — ask the LLM to fill in the join + cardinality + cost
 * for a SOURCE→TARGET pair the admin already picked. Never persists; the
 * SPA inspects the three-state outcome (clean / caveats / no-match) and
 * only commits if the admin clicks Apply.
 */
export async function suggestRelationshipComplete(
  body: RelationshipSuggestRequest,
): Promise<RelationshipSuggestResponse> {
  const { data } = await http.post<RelationshipSuggestResponse>(
    '/admin/enrich/relationships-suggest',
    body,
  );
  return data;
}

// ── Body-aware (draft) variants — AI on the not-yet-saved create form (§3.4) ──

/** Preview the EntityDeriver normalization on a draft YAML (no write). */
export async function deriveEntity(yamlContent: string): Promise<DeriveYamlResult> {
  const { data } = await http.post<DeriveYamlResult>('/admin/yaml/derive', {
    yaml_content: yamlContent,
  });
  return data;
}

/** Entity-level (and bulk-field) AI description draft over an unsaved node. */
export async function previewEntityEnrichmentDraft(
  body: EnrichEntityDraftRequest,
): Promise<EnrichEntityResponse> {
  const { data } = await http.post<EnrichEntityResponse>(
    '/admin/enrich/entity/preview/draft',
    body,
  );
  return data;
}

/** Single-field AI description draft over an unsaved node. */
export async function previewFieldEnrichmentDraft(
  body: EnrichFieldDraftRequest,
): Promise<EnrichFieldResponse> {
  const { data } = await http.post<EnrichFieldResponse>('/admin/enrich/field/draft', body);
  return data;
}

/** Mode-2 relationship suggest where the source is the in-progress draft. */
export async function suggestRelationshipCompleteDraft(
  body: RelationshipSuggestDraftRequest,
): Promise<RelationshipSuggestResponse> {
  const { data } = await http.post<RelationshipSuggestResponse>(
    '/admin/enrich/relationships-suggest/draft',
    body,
  );
  return data;
}

// ── Workspaces (Iter 1) ───────────────────────────────────────────────────

export async function listWorkspaces(): Promise<Workspace[]> {
  const { data } = await http.get<Workspace[]>('/admin/workspaces');
  return data;
}

export async function getWorkspace(idOrSlug: string): Promise<Workspace> {
  const { data } = await http.get<Workspace>(`/admin/workspaces/${encodeURIComponent(idOrSlug)}`);
  return data;
}

export async function createWorkspace(payload: WorkspaceCreatePayload): Promise<Workspace> {
  const { data } = await http.post<Workspace>('/admin/workspaces', payload);
  return data;
}

export async function updateWorkspace(
  idOrSlug: string,
  payload: WorkspaceUpdatePayload,
): Promise<Workspace> {
  const { data } = await http.patch<Workspace>(
    `/admin/workspaces/${encodeURIComponent(idOrSlug)}`,
    payload,
  );
  return data;
}

export async function deleteWorkspace(idOrSlug: string): Promise<{ workspaces_deleted: number; business_domains_deleted: number }> {
  const { data } = await http.delete<{ workspaces_deleted: number; business_domains_deleted: number }>(
    `/admin/workspaces/${encodeURIComponent(idOrSlug)}`,
  );
  return data;
}

// ── Business Domains ──────────────────────────────────────────────────────
// (Formerly "Data Products" — UX_CHANGES audit, Iter 1. Routes hard-swapped
//  from /admin/data-products to /admin/business-domains.)

export async function listWorkspaceBusinessDomains(idOrSlug: string): Promise<BusinessDomain[]> {
  const { data } = await http.get<BusinessDomain[]>(
    `/admin/workspaces/${encodeURIComponent(idOrSlug)}/business-domains`,
  );
  return data;
}

export async function createBusinessDomain(
  workspaceIdOrSlug: string,
  payload: BusinessDomainCreatePayload,
): Promise<BusinessDomain> {
  const { data } = await http.post<BusinessDomain>(
    `/admin/workspaces/${encodeURIComponent(workspaceIdOrSlug)}/business-domains`,
    payload,
  );
  return data;
}

export async function getBusinessDomain(bdId: string): Promise<BusinessDomain> {
  const { data } = await http.get<BusinessDomain>(
    `/admin/business-domains/${encodeURIComponent(bdId)}`,
  );
  return data;
}

export async function updateBusinessDomain(
  bdId: string,
  payload: BusinessDomainUpdatePayload,
): Promise<BusinessDomain> {
  const { data } = await http.patch<BusinessDomain>(
    `/admin/business-domains/${encodeURIComponent(bdId)}`,
    payload,
  );
  return data;
}

export async function deleteBusinessDomain(bdId: string): Promise<{ deleted: boolean }> {
  const { data } = await http.delete<{ deleted: boolean }>(
    `/admin/business-domains/${encodeURIComponent(bdId)}`,
  );
  return data;
}

// Incremental membership — add/remove ONE entity atomically. The server applies
// a scripted (atomic) update, so a burst of rapid "+" clicks on the canvas can't
// lose updates the way the full-array PATCH did (concurrent read-modify-write of
// data_product_ids let the last writer win). Both return the fresh BD doc.
export async function addDataProductToDomain(
  bdId: string,
  entityId: string,
): Promise<BusinessDomain> {
  const { data } = await http.post<BusinessDomain>(
    `/admin/business-domains/${encodeURIComponent(bdId)}/data-products`,
    { entity_id: entityId },
  );
  return data;
}

export async function removeDataProductFromDomain(
  bdId: string,
  entityId: string,
): Promise<BusinessDomain> {
  const { data } = await http.delete<BusinessDomain>(
    `/admin/business-domains/${encodeURIComponent(bdId)}/data-products/${encodeURIComponent(entityId)}`,
  );
  return data;
}

// ── DataProduct lifecycle + catalog (UX_CHANGES audit §5) ──────────────────

/** Semantic Knowledge catalog — every DP's lifecycle state. */
export async function getDataProductCatalog(opts?: {
  workspaceId?: string | null;
  status?: DataProductStatus | null;
}): Promise<DataProductLifecycle[]> {
  const params: Record<string, string> = {};
  if (opts?.workspaceId) params.workspace_id = opts.workspaceId;
  if (opts?.status) params.status = opts.status;
  const { data } = await http.get<DataProductLifecycle[]>('/admin/catalog', { params });
  return data;
}

/** Lifecycle doc for a single DataProduct (entity DetailPanel). */
export async function getDataProductLifecycle(
  entityId: string,
): Promise<DataProductLifecycle | null> {
  const { data } = await http.get<DataProductLifecycle | null>(
    `/admin/lifecycle/${encodeURIComponent(entityId)}`,
  );
  return data;
}

/**
 * Publish ONE entity to a specific environment (UX_CHANGES Iter 2/4).
 * Atomic: indexes into ask-*-{env} (OpenSearch first), file-by-file git checkout
 * onto the env branch (dev←main, prod←dev), then records dev/prod_published.
 * Prod requires a prior dev publish (409 otherwise).
 */
export async function publishEntityToEnv(
  entityId: string,
  env: 'dev' | 'prod',
): Promise<PublishEnvResult> {
  const { data } = await http.post<PublishEnvResult>(
    `/admin/yaml/index/${encodeURIComponent(entityId)}/${env}`,
    {},
    { timeout: 300_000 },
  );
  return data;
}

/**
 * Unpublish ONE Data Product from an environment — inverse of publishEntityToEnv.
 * Physically removes it from ``ask-*-{env}`` + the env branch so it stops being
 * answerable when the chat targets that env; it stays in dev/working and can be
 * re-published. 409 if not published to that env, or if unpublishing dev while
 * prod is still published (prod-before-dev gate).
 */
export async function unpublishEntityFromEnv(
  entityId: string,
  env: 'dev' | 'prod',
): Promise<UnpublishEnvResult> {
  const { data } = await http.delete<UnpublishEnvResult>(
    `/admin/yaml/index/${encodeURIComponent(entityId)}/${env}`,
    { timeout: 300_000 },
  );
  return data;
}

/**
 * Domain-level bulk publish (UX_CHANGES §6.5 / CH-5). Publishes every Data
 * Product in the Business Domain to ``env`` (skips up-to-date / not-ready DPs).
 */
export async function publishDomainToEnv(
  bdId: string,
  env: 'dev' | 'prod',
): Promise<DomainPublishResult> {
  const { data } = await http.post<DomainPublishResult>(
    `/admin/business-domains/${encodeURIComponent(bdId)}/publish/${env}`,
    {},
    { timeout: 600_000 },
  );
  return data;
}

/**
 * Streaming domain-level bulk publish — yields one event per Data Product as it
 * is processed (start → processing → item… → done) so the UI can show live
 * per-DP progress instead of a single blocking call. ``entityIds`` restricts the
 * batch to a checklist subset (null = every member).
 *
 * Uses ``fetch`` (axios can't expose a streaming body), so it replicates the two
 * axios behaviours we rely on: it attaches the bearer token, and on a 401 it
 * does one silent refresh + replay before giving up.
 */
export async function* publishDomainToEnvStream(
  bdId: string,
  env: 'dev' | 'prod',
  entityIds: string[] | null,
  signal?: AbortSignal,
): AsyncGenerator<DomainPublishStreamEvent, void, unknown> {
  const url = `/api/admin/business-domains/${encodeURIComponent(bdId)}/publish/${env}/stream`;
  const send = () => {
    const token = useAuthStore.getState().accessToken;
    return fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ entity_ids: entityIds }),
      signal,
    });
  };

  let res = await send();
  if (res.status === 401 && authConfig.mode !== 'none') {
    if (await useAuthStore.getState().refreshSession()) res = await send();
  }
  if (!res.ok || !res.body) {
    let detail = `Publish → ${env} failed (HTTP ${res.status})`;
    try {
      const j = (await res.json()) as { detail?: string };
      if (j.detail) detail = j.detail;
    } catch {
      /* non-JSON error body — keep the generic message */
    }
    throw new Error(detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    // Drain every complete NDJSON line; keep the trailing partial in the buffer.
    let nl: number;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) yield JSON.parse(line) as DomainPublishStreamEvent;
    }
  }
  const tail = buf.trim();
  if (tail) yield JSON.parse(tail) as DomainPublishStreamEvent;
}

/** Reconciliation safety net — reseed lifecycle membership from current BDs. */
export async function rebuildLifecycle(): Promise<{ data_products_touched: number }> {
  const { data } = await http.post<{ data_products_touched: number }>(
    '/admin/lifecycle/rebuild',
    {},
  );
  return data;
}

// ── Organization ──────────────────────────────────────────────────────────

export async function getOrganization(): Promise<Organization> {
  const { data } = await http.get<Organization>('/admin/organization');
  return data;
}

export async function upsertOrganization(payload: OrganizationUpdatePayload): Promise<Organization> {
  const { data } = await http.put<Organization>('/admin/organization', payload);
  return data;
}

// Docs ingest (multipart)
export async function ingestDoc(
  file: File,
  collectionName = 'rag_docs',
): Promise<DocIngestResult> {
  const form = new FormData();
  form.append('file', file);
  form.append('collection_name', collectionName);
  form.append('source_name', file.name);
  const { data } = await http.post<DocIngestResult>('/admin/docs/ingest', form, { timeout: 300_000 });
  return data;
}

// Database connection test
export async function testDatabaseConnection(body: DatabaseTestRequest): Promise<DatabaseTestResult> {
  const { data } = await http.post<DatabaseTestResult>('/admin/database/test', body);
  return data;
}
