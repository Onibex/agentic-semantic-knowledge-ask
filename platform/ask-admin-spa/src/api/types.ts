export type YAMLLayer = 'bronze' | 'silver' | 'gold';

export interface VizField {
  name: string;
  type: string | null;
  alias: string | null;
  key_field: boolean;
  description: string | null;
  source: string | null;
  field_role: string | null;
  /** Axis 1 of the aggregation contract: WHICH SQL function. No semantics. */
  aggregation_behavior: string | null;
  /** Axis 2: over WHICH grain dimensions applying it is valid. Measures only;
   *  null means additive. See REQ_ADDITIVITY_CONTRACT.md. */
  additivity: string | null;  // additive | semi_additive | non_additive
  /** Grain dimensions to collapse before aggregating. Set iff semi_additive. */
  non_additive_over: string[];
  synonyms: string[];
  normalization_flag: string | null;  // currency | uom | none
}

export interface VizJoinCondition {
  left_table: string;
  right_table: string;
  join_type: string;
  condition: string;
  sequence: number;
}

export interface VizMeta {
  field_enrichments: Record<string, string[]>;
  conflicts: unknown[];
}

export interface YAMLIdentity {
  id: string;
  layer: YAMLLayer;
  module: string | null;
  name: string;
  alias: string | null;
  file_path: string;
}

/** The entity's §3.1 top-level header — read-only everywhere in the SPA.
 *  Mirrors `VizHeader`, shared by the catalog row and the opened entity so the
 *  two can never show a different header for the same thing. All nullable: a
 *  Bronze declares only description / source_system / version of this set. */
export interface YAMLHeader {
  description: string | null;
  /** `ORDER TO CASH`, `PROCURE TO PAY`, … — the business axis, never a module code. */
  business_process: string | null;
  entity_role: EntityRole | string | null;
  classification: string | null; // M master | T transactional | C configuration
  db_table_name: string | null; // physical table the SQL targets
  source_system: string | null; // s4h | ecc | generic | …
  /** Source instance number (Bronze `source_system_id` / Silver+Gold `source_system_no`). */
  source_system_no: number | null;
  /** The YAML's spec version — NOT the lifecycle version shown next to the status. */
  version: string | null;
  internal_id: string | null;
  tag1: string | null;
  tag2: string | null;
}

/** One catalog row: identity + header + the structure counts the expandable
 *  detail renders. Everything here is projected from the already-parsed YAML, so
 *  expanding a row costs no second request. */
export interface YAMLNodeSummary extends YAMLIdentity, YAMLHeader {
  entity_grain: string[];
  business_grain: string | null;
  primary_key: string[]; // Bronze's declared key
  field_count: number;
  measure_count: number;
  relationship_count: number;
  has_normalization: boolean;
}

export interface VizRelationship {
  target_entity: string;
  relationship_type: string | null;
  join_condition: string | null;
  semantic_label: string | null;
  traversal_cost: number | null;
  aggregation_safety: string | null;
  cross_module: boolean | null;
  description: string | null;
}

export type EntityRole = 'fact' | 'dimension' | 'reference';

export interface VizGrain {
  entity_grain: string[];
  business_grain: string | null;
}

export interface YAMLNode extends YAMLIdentity, YAMLHeader {
  primary_key: string[]; // Bronze's declared key
  grain: VizGrain | null;
  fields: VizField[];
  join_graph: VizJoinCondition[];
  composed_of: string[];
  relationships: VizRelationship[];
  normalization: VizNormalization | null;
  meta: VizMeta;
}

export interface VizFieldUpdate {
  name: string;
  alias?: string | null;
  description?: string | null;
  field_role?: string | null;
  aggregation_behavior?: string | null;
  additivity?: string | null;
  /** [] clears it — required when moving a field off semi_additive. */
  non_additive_over?: string[] | null;
  synonyms?: string[] | null;
  normalization_flag?: string | null;
}

/** Complete field spec for a FULL structural replace (add/remove/rename/retype/
 *  key/source). Sent in YAMLUpdateRequest.fields_full; the backend normalizes. */
export interface VizFieldFull {
  name: string;
  type?: string | null;
  description?: string | null;
  alias?: string | null; // bronze
  key_field?: boolean | null; // bronze
  source?: string | null; // silver/gold
  field_role?: string | null; // silver/gold
  aggregation_behavior?: string | null; // silver/gold
  additivity?: string | null; // silver/gold — measures only
  non_additive_over?: string[] | null; // silver/gold — iff semi_additive
  synonyms?: string[] | null; // silver/gold
}

export interface VizNormCurrency {
  currency_field?: string;
  amount_fields?: string[];
  target_currency?: string;
  exchange_rate_entity?: string;
  rate_type?: string;
}

export interface VizNormUom {
  source_uom_field?: string;
  quantity_fields?: string[];
  base_uom_entity?: string;
  conversion_numerator?: string;
  conversion_denominator?: string;
  conversion_formula?: string;
}

export interface VizNormalization {
  currency?: VizNormCurrency | null;
  uom?: VizNormUom | null;
}

export interface YAMLUpdateRequest {
  author_name?: string;
  author_email?: string;
  description?: string | null;
  alias?: string | null;
  // Core structural fields (standards §4.1/§4.2). entity_role is Silver/Gold
  // only; db_table_name + classification apply to any layer. Sent only when
  // changed (see editorStore.save).
  db_table_name?: string | null;
  entity_role?: string | null;
  classification?: string | null;
  fields?: VizFieldUpdate[];
  join_graph?: VizJoinCondition[] | null;
  relationships?: VizRelationship[] | null;
  normalization?: VizNormalization | null;
  // Full structural replace (edit-in-full). When present these replace the
  // section wholesale; the backend re-normalizes + re-validates. `fields_full`
  // is mutually exclusive with the per-field `fields` enrichment patch.
  fields_full?: VizFieldFull[] | null;
  composed_of?: string[] | null;
  grain?: { entity_grain?: string[] | null; business_grain?: string | null } | null;
  module?: string | null;
  /**
   * Drives the git commit message prefix.
   *   manual                   → "viz: update <id>"  (default; preserves legacy wording)
   *   ai_assist                → "ai-enrich(<id>): ..."
   *   ai_suggest_relationship  → "ai-suggest-rel(<id>): ..."  + caveats in commit body
   *   import                   → "viz-import(<id>): ..."
   *   merge                    → "viz-merge(<id>): ..."
   *   history_restore          → "viz-restore(<id>): ..."
   */
  source?:
    | 'manual'
    | 'ai_assist'
    | 'ai_suggest_relationship'
    | 'import'
    | 'merge'
    | 'history_restore';
  /**
   * Free-text notes appended to the git commit message body (NOT to the
   * YAML itself). Used by ``ai_suggest_relationship`` to record the LLM's
   * decision caveats — confidence level + alternatives considered — so the
   * audit trail lives in ``git show`` instead of polluting the file.
   */
  commit_notes?: string[];
}

// Iter 5 — Merge types
export type ConflictType = 'field_modified' | 'field_removed' | 'field_type_changed';
export type ConflictDecision = 'keep_enriched' | 'accept_sap';

export interface ConflictBlock {
  id: string;
  yaml_id: string;
  field_name: string;
  conflict_type: ConflictType;
  sap_value: Record<string, unknown>;
  current_value: Record<string, unknown>;
  enriched_properties: string[];
  resolved: boolean;
  resolution: ConflictDecision | null;
  resolved_by: string | null;
  resolved_at: string | null;
}

export interface AutoAppliedChange {
  yaml_id: string;
  field_name: string;
  change_type: string;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
}

export interface MergeResult {
  silver_id: string;
  auto_applied: AutoAppliedChange[];
  conflicts: ConflictBlock[];
  baseline_updated: boolean;
}

// History types
// UX_CHANGES audit §4.4 — history is scoped per branch (3 tabs):
//   working → main (all edits / AI Assist / merges / publishes)
//   dev     → only publish-dev(<id>) commits
//   prod    → only publish-prod(<id>) commits
export type HistoryBranch = 'working' | 'dev' | 'prod';

export interface CommitEntry {
  sha: string;
  short_sha: string;
  message: string;
  author_name: string;
  author_email: string;
  timestamp: string;
}

export interface HistoryResponse {
  yaml_id: string;
  file_path: string;
  branch?: HistoryBranch;
  commits: CommitEntry[];
  page: number;
  per_page: number;
  total_count: number;
  has_more: boolean;
}

export interface DiffResult {
  yaml_id: string;
  from_sha: string;
  to_sha: string;
  unified_diff: string;
  // Both blobs are returned alongside the unified diff so the SPA can render
  // a Monaco side-by-side DiffEditor. Optional for backward compatibility with
  // older admin-api versions that only sent unified_diff.
  content_from?: string;
  content_to?: string;
}

// Stats types
export interface StatsResponse {
  total_yamls: number;
  by_layer: Record<string, number>;
  pending_conflicts: number;
  recently_updated: number;
}

// Dictionary types
export type SapModule = 'SD' | 'MM' | 'PP' | 'FI' | 'CO';

export interface PhraseEntry {
  id?: string;
  type: 'phrase';
  canonical_label: string;
  module: SapModule;
  source_system: string;
  synonyms: string;
  context_clues: string;
  disambiguation_hint: string;
  description: string;
  technical_name: string;
}

export interface DictionaryListResponse {
  entries: PhraseEntry[];
}

// AI Core types
export interface AicoreConfigStatus {
  exists: boolean;
  valid: boolean;
  auth_url: string;
  ai_api_url: string;
  client_id_preview: string;
}

export interface AicoreConfigUploadResponse {
  success: boolean;
  message: string;
  status: AicoreConfigStatus;
}

export interface DeploymentInfo {
  deployment_id: string;
  model_name: string;
}

export interface DeploymentListResponse {
  deployments: DeploymentInfo[];
}

// ── Multi-provider LLM + Embedder config (Tier 2) ────────────────────────────

export type StackMode = 'managed' | 'direct';

/** Source of truth for a single field — env var, settings.json file, or default. */
export type FieldSource = 'environment' | 'file' | 'default';

export interface ProviderConfigField {
  /** Value as stored. For sensitive fields (api_key) the server returns "***" instead. */
  value: string;
  source: FieldSource;
  masked: boolean;
}

export interface EffectiveLLMConfig {
  stack_mode: ProviderConfigField;
  llm_provider: ProviderConfigField;
  llm_model: ProviderConfigField;
  llm_api_key: ProviderConfigField;
  llm_api_base: ProviderConfigField;
  llm_api_version: ProviderConfigField;
  llm_deployment_id: ProviderConfigField;
  embedder_provider: ProviderConfigField;
  embedder_model: ProviderConfigField;
  embedder_api_key: ProviderConfigField;
  embedder_api_base: ProviderConfigField;
  embedder_api_version: ProviderConfigField;
  embedder_deployment_id: ProviderConfigField;
  /** Literal env-var map for exotic providers (Bedrock AWS_*, Vertex VERTEXAI_*). NOT masked. */
  llm_params: Record<string, string>;
  embedder_params: Record<string, string>;
}

/** Partial update payload for POST /admin/llm/config. */
export interface ProviderConfigRequest {
  stack_mode?: string | null;
  llm_provider?: string | null;
  llm_model?: string | null;
  llm_api_key?: string | null;
  llm_api_base?: string | null;
  llm_api_version?: string | null;
  llm_deployment_id?: string | null;
  llm_params?: Record<string, string> | null;
  embedder_provider?: string | null;
  embedder_model?: string | null;
  embedder_api_key?: string | null;
  embedder_api_base?: string | null;
  embedder_api_version?: string | null;
  embedder_deployment_id?: string | null;
  embedder_params?: Record<string, string> | null;
}

/** Test payload — every field falls back to settings.json when null. */
export interface TestProviderRequest {
  target: 'llm' | 'embedder';
  provider?: string | null;
  model?: string | null;
  api_key?: string | null;
  api_base?: string | null;
  api_version?: string | null;
  deployment_id?: string | null;
  params?: Record<string, string> | null;
}

export interface TestProviderResponse {
  success: boolean;
  target: string;
  provider: string;
  model: string;
  latency_ms: number;
  detail: string;
  error?: string | null;
}

// ── Setup Effective (read-only system snapshot for the SPA) ─────────────────

/** One displayable field. Sensitive values come server-masked as ``***``. */
export interface ConfigFieldRO {
  name: string;
  label?: string | null;
  value: string;
  /**
   * Where the value comes from.
   *   - environment = K8s Secret / shell var
   *   - file        = config/settings.json (legacy path; being phased out for LLM + Embedder)
   *   - encrypted   = ask-system-settings-v1 in OpenSearch (Fernet ciphertext, value masked)
   *   - plain       = ask-system-settings-v1 in OpenSearch (non-sensitive field stored as-is)
   *   - default     = no value set; the runtime falls back to a hardcoded default
   */
  source: 'environment' | 'file' | 'encrypted' | 'plain' | 'default';
  sensitive: boolean;
  help_text?: string | null;
}

/** One renderable card. ``test_target`` drives the inline test button. */
export interface ConfigSection {
  id: string;
  title: string;
  provider?: string | null;
  provider_label?: string | null;
  fields: ConfigFieldRO[];
  info?: string | null;
  /** "llm" | "embedder" | "opensearch" — or null for display-only sections. */
  test_target?: 'llm' | 'embedder' | 'opensearch' | null;
}

export interface SetupEffectiveResponse {
  sections: ConfigSection[];
}

export interface OpenSearchTestResponse {
  success: boolean;
  latency_ms: number;
  cluster_name: string;
  status: string;
  detail: string;
  error?: string | null;
}

// ── Encrypted Secrets (LLM + Embedder write path) ──────────────────────────

export type SecretsTarget = 'llm' | 'embedder';

/** One field as the SPA renders it post-PUT. Sensitive values come as "***". */
export interface SecretsFieldView {
  name: string;
  value: string;
  sensitive: boolean;
  /** "plain" / "encrypted" come from OpenSearch. "environment" wins when an OS env var overrides. */
  source: 'plain' | 'encrypted' | 'environment' | 'default';
}

export interface SecretsGetResponse {
  target: SecretsTarget;
  provider: string;
  model: string;
  fields: SecretsFieldView[];
  updated_at: string;
  updated_by: string;
}

export interface SecretsPutRequest {
  provider: string;
  model: string;
  /** Flat map. Backend uses the registry to split plain vs encrypted. */
  fields: Record<string, string>;
}

export interface SecretsTestRequest {
  target: SecretsTarget;
}

export interface SecretsTestResponse {
  success: boolean;
  target: SecretsTarget;
  provider: string;
  model: string;
  latency_ms: number;
  detail: string;
  error?: string | null;
}

export interface ProviderFieldSpec {
  name: string;
  sensitive: boolean;
}

export interface ProviderSpec {
  id: string;
  label: string;
  fields: ProviderFieldSpec[];
}

export interface ProvidersListResponse {
  providers: ProviderSpec[];
}

// ── System Prompts (editable per key) ──────────────────────────────────────

export type PromptKey = 'enrichment';

export interface SystemPromptResponse {
  key: PromptKey;
  body: string;
  is_default: boolean;
  updated_at?: string;
  updated_by?: string;
  standards_excerpt?: string;
}

export interface SystemPromptUpdateRequest {
  body: string;
}

// ── AI Enrichment ──────────────────────────────────────────────────────────

export type FieldPriority = 'empty' | 'short' | 'good';

export interface FieldScopeRow {
  name: string;
  current_description: string;
  has_description: boolean;
  has_synonyms: boolean;
  priority: FieldPriority;
  /** True for boolean / status / flag patterns — chip "FLAG?" in the checklist, NOT auto-selected. */
  is_likely_flag: boolean;
}

export interface EntityLevelScope {
  has_description: boolean;
  has_alias: boolean;
  has_business_process: boolean;
  /** Mirrors FieldScopeRow shape — current values + priority bucket. */
  current_description: string;
  current_alias: string;
  current_business_process: string;
  priority: FieldPriority;
}

export interface DefaultSelection {
  entity_level: boolean;
  field_names: string[];
}

export interface EnrichEntityScopeDefaults {
  entity_id: string;
  layer: string;
  enrichable_fields: FieldScopeRow[];
  technical_fields: string[];
  entity_level: EntityLevelScope;
  default_selection: DefaultSelection;
  /**
   * The plain-text workspace framing the backend will inject into the LLM
   * prompt — Data Products that own this entity + sibling entities + workspace
   * objective. Surfaced verbatim in the dialog so the admin sees the bias.
   * Null when no workspace_id was supplied OR the entity isn't part of any
   * DP in that workspace.
   */
  workspace_context: string | null;
}

export interface EnrichEntityScope {
  entity_level: boolean;
  field_names: string[];
}

export interface EnrichEntityRequest {
  entity_id: string;
  scope: EnrichEntityScope;
  /** Optional workspace UUID/slug — adds workspace + DP + sibling context to the prompt. */
  workspace_id?: string | null;
}

/**
 * Body for ``POST /v1/admin/enrich/entity/{id}/prompt-preview``.
 * Mirrors ``EnrichEntityRequest`` but the endpoint does NOT call the LLM —
 * it just returns the composed (system, user) pair so the admin can audit
 * exactly what the model would see for this scope.
 */
export interface PromptPreviewRequest {
  scope: EnrichEntityScope;
  workspace_id?: string | null;
}

// ── Relationship suggest (Modo 2 — Complete) ─────────────────────────────

export type RelationshipSuggestConfidence = 'high' | 'medium' | 'low';

/**
 * What the LLM returns for a SOURCE→TARGET suggestion. Mirrors the
 * Pydantic ``SuggestedRelationship`` 1:1 — same shape as a VizRelationship
 * row in the editor, so the SPA can paste it directly with no adapter.
 */
export interface SuggestedRelationship {
  target_entity: string;
  relationship_type: string | null;
  join_condition: string | null;
  semantic_label: string | null;
  traversal_cost: number | null;
  aggregation_safety: string | null;
  cross_module: boolean | null;
  description: string | null;
}

export interface RelationshipSuggestRequest {
  source_entity_id: string;
  target_entity_id: string;
  workspace_id?: string | null;
}

/**
 * Three terminal states the dialog must render:
 *   - relationship + confidence 'high' + caveats=[]               → green Apply
 *   - relationship + confidence 'medium'|'low' + caveats[]        → amber Apply
 *   - relationship=null + no_match_reason                          → red banner
 */
export interface RelationshipSuggestResponse {
  provider: string;
  model: string;
  relationship: SuggestedRelationship | null;
  confidence: RelationshipSuggestConfidence;
  caveats: string[];
  no_match_reason: string | null;
  tokens_used: number;
  elapsed_ms: number;
  diagnostic: EnrichmentDiagnostic | null;
}

export interface PromptPreviewResponse {
  entity_id: string;
  provider: string;
  model: string;
  system_message: string;
  user_message: string;
  system_chars: number;
  user_chars: number;
}

export interface ValueDiff {
  old: string;
  new: string;
}

export interface SynonymsDiff {
  old: string[];
  new: string[];
}

export interface FieldDiff {
  field_name: string;
  description?: ValueDiff | null;
  synonyms?: SynonymsDiff | null;
}

export interface EntityDiff {
  description?: ValueDiff | null;
  alias?: ValueDiff | null;
  business_process?: ValueDiff | null;
}

export interface EnrichmentDiagnostic {
  original_field_count: number;
  enriched_field_count: number;
  matched_field_count: number;
  fields_only_in_enriched: string[];
  fields_only_in_original: string[];
  response_chars: number;
  response_preview: string;
  response_tail: string;
  /** When set, the model returned malformed YAML — the value is the parser error. */
  parse_error?: string | null;
}

export interface EnrichEntityResponse {
  entity_id: string;
  provider: string;
  model: string;
  entity_diff: EntityDiff;
  field_diffs: FieldDiff[];
  fields_skipped_technical: string[];
  fields_unchanged: string[];
  /**
   * Preservation-guard caveats: messages emitted by the backend when an AI
   * description rewrite would have dropped value mappings, TABLE.FIELD
   * citations or alternative-field hints from the original. The change for
   * that key/field is cancelled and an entry is added here so the admin
   * sees what was preserved and why.
   */
  caveats?: string[];
  tokens_used: number;
  elapsed_ms: number;
  /** Populated by the backend ONLY when the diff is empty — helps debug a 0-change run. */
  diagnostic?: EnrichmentDiagnostic | null;
}

export interface EnrichFieldRequest {
  entity_id: string;
  field_name: string;
}

// ── Body-aware (draft) variants — AI on a not-yet-saved entity (§3.4) ────────

export interface EnrichEntityDraftRequest {
  raw_yaml: Record<string, unknown>;
  scope: EnrichEntityScope;
  workspace_id?: string | null;
  entity_id?: string | null;
}

export interface EnrichFieldDraftRequest {
  raw_yaml: Record<string, unknown>;
  field_name: string;
  entity_id?: string | null;
}

export interface RelationshipSuggestDraftRequest {
  source_raw_yaml: Record<string, unknown>;
  target_entity_id: string;
  workspace_id?: string | null;
  source_entity_id?: string | null;
}

// ── /derive preview (EntityDeriver normalization, no write) ──────────────────

export interface DeriveYamlRequest {
  yaml_content: string;
}

export interface DerivedFieldFlag {
  name: string;
  derived: string[];
}

export interface DeriveYamlResult {
  layer: string;
  node: Record<string, unknown>;
  entity_derived: string[];
  fields: DerivedFieldFlag[];
  validation_error: string | null;
}

export interface EnrichFieldResponse {
  entity_id: string;
  field_name: string;
  provider: string;
  model: string;
  diff: FieldDiff;
  tokens_used: number;
  elapsed_ms: number;
}

// ── Workspaces + Business Domains + Organization ───────────────────────────
// "Data Product" was renamed to "Business Domain" (UX_CHANGES audit, Iter 1).
// A Business Domain groups DataProducts (entity ids) via ``data_product_ids``
// (was ``entity_ids``). The first-class DataProduct lifecycle lives below.

export type WorkspaceRoleKind = 'curator' | 'reviewer' | 'viewer';

export interface RoleMember {
  email: string;
  role: WorkspaceRoleKind;
}

export interface Workspace {
  id: string;
  slug: string;
  name: string;
  objective: string;
  description: string;
  roles: RoleMember[];
  created_at: string;
  created_by: string;
  updated_at: string;
  updated_by: string;
}

export interface WorkspaceCreatePayload {
  slug: string;
  name: string;
  objective?: string;
  description?: string;
  roles?: RoleMember[];
}

export interface WorkspaceUpdatePayload {
  slug?: string;
  name?: string;
  objective?: string;
  description?: string;
  roles?: RoleMember[];
}

export interface BusinessDomain {
  id: string;
  workspace_id: string;
  slug: string;
  name: string;
  description: string;
  data_product_ids: string[];
  created_at: string;
  created_by: string;
  updated_at: string;
  updated_by: string;
}

export interface BusinessDomainCreatePayload {
  slug: string;
  name: string;
  description?: string;
  data_product_ids?: string[];
}

export interface BusinessDomainUpdatePayload {
  slug?: string;
  name?: string;
  description?: string;
  data_product_ids?: string[];
}

// ── DataProduct lifecycle (first-class DP = one silver/gold YAML) ───────────
// Denormalized from ``ask-entity-lifecycle-v1`` (UX_CHANGES audit §5). Read via
// GET /v1/admin/catalog (all) or GET /v1/admin/lifecycle/{entity_id} (one).

export type DataProductStatus = 'In Review' | 'Released';

export interface PublishRecord {
  version: number;
  sha: string;
  at: string;
  by: string;
}

export interface DataProductLifecycle {
  entity_id: string;
  workspace_id: string;
  business_domain_ids: string[];
  status: DataProductStatus;
  version: number;
  main_sha: string;
  dev_published: PublishRecord | null;
  prod_published: PublishRecord | null;
  updated_at: string;
  /**
   * Derived (not persisted): unresolved SAP-merge conflicts for this entity.
   * An orthogonal attribute layered on `status` — a conflicted entity is
   * already "In Review", but "In Review" does not imply a conflict.
   */
  pending_conflicts?: number;
}

// DDL → YAML AI import (Iter 6 / CH-6).
export interface DdlImportItem {
  entity_id: string | null;
  layer: string | null;
  file_path: string | null;
  outcome: 'created' | 'overwritten' | 'error';
  reason: string | null;
}

export interface DdlImportResult {
  generated_yaml: string;
  tokens_used: number;
  items: DdlImportItem[];
  /** Non-fatal robustness flags (§7.1), e.g. multi-table undercount. */
  warnings?: string[];
}

/** A code-defined source-system profile for the DDL form selector (Phase C2). */
export interface SourceProfile {
  key: string;
  label: string;
}

/** Per-DP outcome inside a domain-level bulk publish (Iter 5). */
export interface DomainPublishItem {
  entity_id: string;
  outcome: 'published' | 'skipped' | 'error';
  committed_sha: string | null;
  reason: string | null;
}

/** Result of POST /v1/admin/business-domains/{id}/publish/{env} (Iter 5). */
export interface DomainPublishResult {
  business_domain_id: string;
  env: string;
  total: number;
  published: number;
  skipped: number;
  failed: number;
  items: DomainPublishItem[];
}

/**
 * One NDJSON event from the streaming domain publish
 * (POST /business-domains/{id}/publish/{env}/stream). The SPA consumes these to
 * render per-DP progress live instead of waiting for one blocking response.
 */
export type DomainPublishStreamEvent =
  | { type: 'start'; env: string; business_domain_id: string; total: number; planned: string[] }
  | { type: 'processing'; entity_id: string; index: number }
  | {
      type: 'item';
      index: number;
      entity_id: string;
      outcome: 'published' | 'skipped' | 'error';
      committed_sha: string | null;
      reason: string | null;
    }
  | {
      type: 'done';
      env: string;
      business_domain_id: string;
      total: number;
      published: number;
      skipped: number;
      failed: number;
    };

/** Result of POST /v1/admin/yaml/index/{id}/{env} (env publish, Iter 2/4). */
export interface PublishEnvResult {
  entity_id: string;
  env: string;
  committed_sha: string | null;
  entities_indexed: number;
  fields_indexed: number;
  edges_indexed: number;
  rag_chunks_indexed: number;
  indexed_paths: string[];
  cascade_indexed: string[];
  cascade_warnings: string[];
}

export interface UnpublishEnvResult {
  entity_id: string;
  env: string;
  committed_sha: string | null;
  entities_removed: number;
  fields_removed: number;
  edges_removed: number;
  rag_chunks_removed: number;
  warnings: string[];
}

export interface Organization {
  id: string;
  company_name: string;
  /** Generic source system (system + version), e.g. "SAP S/4HANA 2023". */
  source_system: string;
  sap_version: string; // deprecated alias of source_system (read fallback)
  core_bases: string[];
  url: string;
  updated_at: string;
  updated_by: string;
}

export interface OrganizationUpdatePayload {
  company_name?: string;
  source_system?: string;
  sap_version?: string; // deprecated; backend mirrors source_system into it
  core_bases?: string[];
  url?: string;
}

// Config types
export interface HanaConfig {
  host: string;
  port: number;
  user: string;
  password: string;
  schema: string;
}

export interface PostgresConfig {
  host: string;
  port: number;
  database: string;
  user: string;
  password: string;
  sslmode: string;
}

export interface OpenSearchConfig {
  host: string;
  port: number;
  username: string;
  password: string;
  use_ssl: boolean;
  verify_certs: boolean;
}

export interface SapAiCoreConfig {
  config_path: string;
}

export interface DeploymentsConfig {
  llm: string;
  embeddings: string;
}

export interface IasConfig {
  url: string;
  client_id: string;
  client_secret: string;
}

export interface DbEnvBlock {
  db_type?: 'hana' | 'postgresql';
  hana?: Partial<HanaConfig>;
  postgresql?: Partial<PostgresConfig>;
}

export interface AppSettings {
  db_type?: 'hana' | 'postgresql';
  model_name?: string;
  schema_mode?: 'yaml' | 'documents' | 'both';
  hana?: Partial<HanaConfig>;
  postgresql?: Partial<PostgresConfig>;
  opensearch?: Partial<OpenSearchConfig>;
  sap_ai_core?: Partial<SapAiCoreConfig>;
  deployments?: Partial<DeploymentsConfig>;
  ias?: Partial<IasConfig>;
  sap_s4hana?: Partial<SapS4HanaConfig>;
  environments?: {
    dev?: DbEnvBlock;
    prod?: DbEnvBlock;
  };
}

export interface DatabaseTestRequest {
  db_type: 'hana' | 'postgresql';
  config: Partial<HanaConfig> | Partial<PostgresConfig>;
}

export interface DatabaseTestResult {
  ok: boolean;
  message: string;
}

export interface ConfigResponse {
  config: AppSettings;
}

export interface ConfigSaveResponse {
  success: boolean;
  cleared: string[];
  message: string;
}

export interface UpsertResponse {
  success: boolean;
  message: string;
}

// Knowledge Graph types
export interface LightweightEntity {
  id: string;
  name: string | null;
  layer: string | null;
}

export interface CatalogResponse {
  entities: LightweightEntity[];
}

export interface IngestionResult {
  entities_indexed: number;
  fields_indexed: number;
  edges_indexed: number;
  rag_chunks_indexed: number;
  error: string | null;
  cascade_indexed?: string[];   // entity ids auto-published (e.g. composed_of Bronces)
  cascade_warnings?: string[];  // orphan references etc., human-readable
}

// Pass I — workspace-only YAML import (Knowledge page).
export interface ImportYamlResult {
  entity_id: string;
  layer: string;
  file_path: string;
  overwritten: boolean;
}

export interface RagIndexResult {
  chunks_indexed: number;
  batches_sent: number;
  collection: string;
  skipped: boolean;
  skip_reason: string | null;
}

export interface FullIngestResult {
  kg: IngestionResult;
  rag: RagIndexResult | null;
  error: string | null;
}

// Publish workspace → runtime index (bulk + per-entity)
export interface IndexWorkspaceItem {
  entity_id: string;
  layer: string | null;
  status: string; // indexed | skipped | error
  entities_indexed: number;
  fields_indexed: number;
  edges_indexed: number;
  rag_chunks_indexed: number;
  error: string | null;
}

export interface IndexWorkspaceResult {
  total: number;
  indexed: number;
  skipped: number;
  failed: number;
  layers: string[];
  items: IndexWorkspaceItem[];
  entities_indexed: number;
  fields_indexed: number;
  edges_indexed: number;
  rag_chunks_indexed: number;
}

export interface DeletionResult {
  entities_deleted: number;
  fields_deleted: number;
  rag_chunks_deleted: number;
  error: string | null;
}

export interface ResetIndicesResult {
  dropped: string[];
  errors: string[];
  embedding_dim: number;
}

// SAP / MCP types
export interface SapS4HanaConfig {
  host: string;
  odata_path: string;
  username: string;
  password: string;
  mcp_url: string;
  port: number;
}

export interface ConnectionTestResult {
  ok: boolean;
  status_code: number | null;
  message: string;
}

// Contracts types
export interface ContractsConfig {
  server: { name: string; version: string };
  apis: unknown[];
}

export interface ContractsSaveResponse {
  success: boolean;
  message: string;
}

// Docs ingest
export interface DocIngestResult {
  chunks_indexed: number;
  batches_sent: number;
  collection: string;
  error: string | null;
}
