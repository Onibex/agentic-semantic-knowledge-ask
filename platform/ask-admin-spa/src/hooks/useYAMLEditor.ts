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
