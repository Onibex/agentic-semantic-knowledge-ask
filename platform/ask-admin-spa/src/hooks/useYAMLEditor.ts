/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useEditorStore } from '../store/editorStore';

export function useYAMLEditor() {
  const store = useEditorStore();
  return {
    editBuffer:       store.editBuffer,
    isDirty:          store.isDirty,
    isSaving:         store.isSaving,
    saveError:        store.saveError,
    startEdit:        store.startEdit,
    cancelEdit:       store.cancelEdit,
    save:             store.save,
    updateFieldProp:  store.updateFieldProp,
    updateNodeProp:   store.updateNodeProp,
    updateJoinGraph:  store.updateJoinGraph,
    authorName:       store.authorName,
    authorEmail:      store.authorEmail,
    setAuthor:        store.setAuthor,
  };
}
