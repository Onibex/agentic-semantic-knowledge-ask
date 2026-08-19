/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { create } from 'zustand';
import { updateYaml } from '../api/client';
import { invalidateLifecycle } from '../hooks/queries/catalogQueries';
import { useGraphStore } from './graphStore';
import { useAuthStore } from './authStore';
import type {
  YAMLNode,
  VizField,
  VizJoinCondition,
  VizFieldUpdate,
  VizRelationship,
  VizNormalization,
  YAMLUpdateRequest,
} from '../api/types';

interface EditorStore {
  editingNodeId: string | null;
  editBuffer: YAMLNode | null;
  originalNode: YAMLNode | null;
  isDirty: boolean;
  isSaving: boolean;
  saveError: string | null;
  authorName: string;
  authorEmail: string;
  /**
   * Caveats accumulated within this edit session — driven by AI-suggest
   * applies. When non-empty at save time, the commit is tagged as
   * ``ai_suggest_relationship`` and these strings ride along in the commit
   * message body. The YAML body itself stays clean.
   */
  commitNotes: string[];

  /** Set when a STRUCTURAL edit happens (add/remove/rename/retype field, key,
   *  source, composed_of, grain). Drives save() to send the full-replace
   *  payload (fields_full/composed_of/grain) instead of the per-field patch. */
  structuralDirty: boolean;

  startEdit(node: YAMLNode): void;
  updateFieldProp(fieldName: string, prop: keyof VizField, value: unknown): void;
  updateNodeProp(
    prop: 'description' | 'alias' | 'module' | 'db_table_name' | 'classification' | 'entity_role',
    value: string | null,
  ): void;
  updateJoinGraph(conditions: VizJoinCondition[]): void;
  updateRelationships(relationships: VizRelationship[]): void;
  updateNormalization(normalization: VizNormalization | null): void;
  // ── Structural edits (edit-in-full) ──────────────────────────────────────
  // composed_of + grain.entity_grain + entity_role are NOT here: they're
  // auto-derived (recomputed server-side on save), never set by the client.
  addField(): void;
  removeFieldAt(index: number): void;
  updateFieldAt(index: number, prop: keyof VizField, value: unknown): void;
  /** Append caveats from an AI-suggest apply. Cleared on cancel/save. */
  addCommitNotes(notes: string[]): void;
  cancelEdit(): void;
  save(onSuccess?: (updated: YAMLNode) => void): Promise<void>;
  setAuthor(name: string, email: string): void;
}

function deepClone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj));
}

const storedName  = localStorage.getItem('yamlViz_authorName')  ?? '';
const storedEmail = localStorage.getItem('yamlViz_authorEmail') ?? '';

export const useEditorStore = create<EditorStore>((set, get) => ({
  editingNodeId: null,
  editBuffer: null,
  originalNode: null,
  isDirty: false,
  isSaving: false,
  saveError: null,
  authorName: storedName,
  authorEmail: storedEmail,
  commitNotes: [],
  structuralDirty: false,

  startEdit(node: YAMLNode) {
    const clone = deepClone(node);
    set({
      editingNodeId: node.id,
      editBuffer: clone,
      originalNode: deepClone(node),
      isDirty: false,
      saveError: null,
      commitNotes: [],
      structuralDirty: false,
    });
  },

  updateFieldProp(fieldName: string, prop: keyof VizField, value: unknown) {
    const { editBuffer } = get();
    if (!editBuffer) return;
    const newFields = editBuffer.fields.map((f) =>
      f.name === fieldName ? { ...f, [prop]: value } : f,
    );
    const newBuffer = { ...editBuffer, fields: newFields };
    set({
      editBuffer: newBuffer,
      // Optimistic: any edit marks dirty. The PRECISE field/join/rel/norm diff
      // runs once at save() time — doing a full double JSON.stringify of the
      // whole node on every keystroke was the dominant typing-lag cost.
      isDirty: true,
    });
  },

  updateNodeProp(
    prop: 'description' | 'alias' | 'module' | 'db_table_name' | 'classification' | 'entity_role',
    value: string | null,
  ) {
    const { editBuffer } = get();
    if (!editBuffer) return;
    const newBuffer = { ...editBuffer, [prop]: value };
    set({
      editBuffer: newBuffer,
      // Optimistic: any edit marks dirty. The PRECISE field/join/rel/norm diff
      // runs once at save() time — doing a full double JSON.stringify of the
      // whole node on every keystroke was the dominant typing-lag cost.
      isDirty: true,
    });
  },

  updateJoinGraph(conditions: VizJoinCondition[]) {
    const { editBuffer } = get();
    if (!editBuffer) return;
    const newBuffer = { ...editBuffer, join_graph: conditions };
    set({
      editBuffer: newBuffer,
      // Optimistic: any edit marks dirty. The PRECISE field/join/rel/norm diff
      // runs once at save() time — doing a full double JSON.stringify of the
      // whole node on every keystroke was the dominant typing-lag cost.
      isDirty: true,
    });
  },

  updateRelationships(relationships: VizRelationship[]) {
    const { editBuffer } = get();
    if (!editBuffer) return;
    const newBuffer = { ...editBuffer, relationships };
    set({
      editBuffer: newBuffer,
      // Optimistic: any edit marks dirty. The PRECISE field/join/rel/norm diff
      // runs once at save() time — doing a full double JSON.stringify of the
      // whole node on every keystroke was the dominant typing-lag cost.
      isDirty: true,
    });
  },

  updateNormalization(normalization: VizNormalization | null) {
    const { editBuffer } = get();
    if (!editBuffer) return;
    const newBuffer = { ...editBuffer, normalization };
    set({
      editBuffer: newBuffer,
      // Optimistic: any edit marks dirty. The PRECISE field/join/rel/norm diff
      // runs once at save() time — doing a full double JSON.stringify of the
      // whole node on every keystroke was the dominant typing-lag cost.
      isDirty: true,
    });
  },

  addCommitNotes(notes: string[]) {
    if (!notes || notes.length === 0) return;
    const { commitNotes } = get();
    set({ commitNotes: [...commitNotes, ...notes] });
  },

  addField() {
    const { editBuffer } = get();
    if (!editBuffer) return;
    const isBronze = editBuffer.layer === 'bronze';
    const blank: VizField = {
      name: '',
      type: 'STRING(40)',
      alias: null,
      key_field: false,
      description: '',
      source: '',
      field_role: isBronze ? null : 'dimension',
      aggregation_behavior: null,
      synonyms: [],
      normalization_flag: null,
    };
    set({ editBuffer: { ...editBuffer, fields: [...editBuffer.fields, blank] }, isDirty: true, structuralDirty: true });
  },

  removeFieldAt(index: number) {
    const { editBuffer } = get();
    if (!editBuffer) return;
    set({
      editBuffer: { ...editBuffer, fields: editBuffer.fields.filter((_, i) => i !== index) },
      isDirty: true,
      structuralDirty: true,
    });
  },

  updateFieldAt(index: number, prop: keyof VizField, value: unknown) {
    const { editBuffer } = get();
    if (!editBuffer) return;
    const fields = editBuffer.fields.map((f, i) => (i === index ? { ...f, [prop]: value } : f));
    set({ editBuffer: { ...editBuffer, fields }, isDirty: true, structuralDirty: true });
  },

  cancelEdit() {
    set({
      editingNodeId: null,
      editBuffer: null,
      originalNode: null,
      isDirty: false,
      isSaving: false,
      saveError: null,
      commitNotes: [],
      structuralDirty: false,
    });
  },

  async save(onSuccess?: (updated: YAMLNode) => void) {
    const { editingNodeId, editBuffer, originalNode, authorName, authorEmail, structuralDirty } = get();
    if (!editingNodeId || !editBuffer || !originalNode) return;

    const changedFields: VizFieldUpdate[] = editBuffer.fields
      .filter((f, i) => JSON.stringify(f) !== JSON.stringify(originalNode.fields[i]))
      .map((f) => ({
        name: f.name,
        alias: f.alias,
        description: f.description,
        field_role: f.field_role,
        aggregation_behavior: f.aggregation_behavior,
        // Axis 2 of the aggregation contract (REQ_ADDITIVITY_CONTRACT.md). Both
        // keys must ride along: omitting them from this whitelist would silently
        // revert a curator's semi_additive to the additive default on the next
        // save — the same shape of defect the contract was written to kill.
        additivity: f.additivity,
        non_additive_over: f.non_additive_over,
        synonyms: f.synonyms,
        normalization_flag: f.normalization_flag,
      }));

    const joinGraphChanged =
      JSON.stringify(editBuffer.join_graph) !== JSON.stringify(originalNode.join_graph);
    const relationshipsChanged =
      JSON.stringify(editBuffer.relationships) !== JSON.stringify(originalNode.relationships);
    const normalizationChanged =
      JSON.stringify(editBuffer.normalization ?? null) !==
      JSON.stringify(originalNode.normalization ?? null);

    // Author is the verified login (the backend derives it from the JWT anyway).
    const user = useAuthStore.getState().user;

    const { commitNotes } = get();
    const hasCaveats = commitNotes.length > 0;

    const request: YAMLUpdateRequest = {
      author_name: user?.email ? user.email.split('@')[0] : authorName || undefined,
      author_email: user?.email ?? authorEmail ?? undefined,
      description: editBuffer.description,
      alias: editBuffer.alias,
      // Core structural fields — sent only when actually changed so we don't
      // rewrite (or, for entity_role on Bronze, attempt to write) untouched values.
      db_table_name:
        editBuffer.db_table_name !== originalNode.db_table_name
          ? editBuffer.db_table_name
          : undefined,
      // entity_role: SILVER never sends it — it is derived from classification and
      // recomputed server-side on every save (Standards §5.1). GOLD authors it, so
      // it is sent when changed; the backend no longer recomputes it for Gold.
      entity_role:
        editBuffer.layer === 'gold' && editBuffer.entity_role !== originalNode.entity_role
          ? editBuffer.entity_role
          : undefined,
      classification:
        editBuffer.classification !== originalNode.classification
          ? editBuffer.classification
          : undefined,
      // Enrichment-only edit → per-field patch. Structural edit → full replace
      // (fields_full) so add/remove/rename/retype/key/source all persist; the
      // backend re-normalizes + re-validates. composed_of + grain are NOT sent:
      // composed_of is set via the create-time bronze picker (read-only here),
      // and grain.entity_grain is recomputed from the identifier fields on save.
      fields: !structuralDirty && changedFields.length > 0 ? changedFields : undefined,
      fields_full: structuralDirty
        ? editBuffer.fields
            .filter((f) => (f.name ?? '').trim())
            .map((f) => ({
              name: f.name,
              type: f.type,
              description: f.description,
              alias: f.alias,
              key_field: f.key_field,
              // Only a real bronze lineage travels. The Source column is Silver-only,
              // so on a Gold this is always empty — sending it made the backend write
              // `source: ''` into every field of the file on each save.
              source: f.source?.trim() ? f.source : undefined,
              field_role: f.field_role,
              aggregation_behavior: f.aggregation_behavior,
              additivity: f.additivity,
              non_additive_over: f.non_additive_over,
              synonyms: f.synonyms,
            }))
        : undefined,
      module: structuralDirty && typeof editBuffer.module === 'string' ? editBuffer.module : undefined,
      join_graph: joinGraphChanged ? editBuffer.join_graph : undefined,
      relationships: relationshipsChanged ? editBuffer.relationships : undefined,
      normalization: normalizationChanged ? (editBuffer.normalization ?? null) : undefined,
      // If AI-suggest applies happened in this session, tag the commit so the
      // git log reflects how the change reached the workspace and ship the
      // caveats in the commit message body (kept OUT of the YAML).
      source: hasCaveats ? 'ai_suggest_relationship' : undefined,
      commit_notes: hasCaveats ? commitNotes : undefined,
    };

    set({ isSaving: true, saveError: null });
    try {
      const updated = await updateYaml(editingNodeId, request);
      get().cancelEdit();
      useGraphStore.getState().replaceNode(updated);  // local swap, no full refetch
      invalidateLifecycle();  // an edit flips status → In Review; refresh all lifecycle views
      onSuccess?.(updated);
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : String(err);
      set({ isSaving: false, saveError: msg });
    }
  },

  setAuthor(name: string, email: string) {
    localStorage.setItem('yamlViz_authorName', name);
    localStorage.setItem('yamlViz_authorEmail', email);
    set({ authorName: name, authorEmail: email });
  },
}));
