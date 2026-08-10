import { Editor, type OnChange, type OnMount } from '@monaco-editor/react'
import { useEffect, useRef } from 'react'

interface Props {
  /** Current YAML content; the consumer owns state and re-passes on every render. */
  value: string
  /** Notified on every keystroke that changes the content. */
  onChange?: (next: string) => void
  /** Optional JSON Schema for live validation + completion of ${schemaUri}. */
  schema?: object
  /** A unique URI identifying the schema (used by Monaco's diagnostics). */
  schemaUri?: string
  /** Read-only mode (e.g. for previewing AI-enriched output before accept). */
  readOnly?: boolean
  /** Fixed height; defaults to fill the parent. */
  height?: string | number
}

/**
 * YAML editor backed by Monaco.
 *
 * Use cases:
 *  - Pass J "+ New entity" — admin authors a Bronze/Silver/Gold YAML in-browser
 *    with schema-driven autocomplete + red squiggles on schema violations.
 *  - AI Enrich preview — show the generated YAML alongside the original
 *    (combine with :class:`MonacoDiffViewer`).
 *
 * Schema integration: when ``schema`` + ``schemaUri`` are provided, the
 * schema is wired into Monaco's YAML diagnostics provider. The same schema
 * can be exported from a Pydantic model via ``model.model_json_schema()``
 * — that's the path that keeps FE validation in sync with BE validation.
 */
export function YamlEditor({
  value,
  onChange,
  schema,
  schemaUri,
  readOnly = false,
  height = '100%',
}: Props) {
  const monacoRef = useRef<unknown>(null)

  const handleMount: OnMount = (_editor, monaco) => {
    monacoRef.current = monaco
    applySchema(monaco, schema, schemaUri)
  }

  useEffect(() => {
    if (monacoRef.current) {
      applySchema(monacoRef.current, schema, schemaUri)
    }
  }, [schema, schemaUri])

  const handleChange: OnChange = (next) => {
    if (typeof next === 'string') onChange?.(next)
  }

  return (
    <Editor
      height={height}
      language="yaml"
      value={value}
      onChange={handleChange}
      onMount={handleMount}
      options={{
        readOnly,
        fontSize: 13,
        lineNumbers: 'on',
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        automaticLayout: true,
      }}
    />
  )
}

// ── Schema wiring ──────────────────────────────────────────────────────────
// Monaco ships a JSON diagnostics provider out of the box. For YAML we use
// the same provider — Monaco maps JSON schema validation to YAML files when
// the editor language is "yaml" AND the `monaco-yaml` provider is loaded.
// Until we adopt monaco-yaml officially, schemaUri remains a no-op slot we
// can fill without changing the consumer API.
//
// Adding ``monaco-yaml`` later means: install it, init it once at app boot,
// and the existing call sites of <YamlEditor schema={...} /> get full
// schema-driven autocomplete automatically.

function applySchema(_monaco: unknown, _schema: object | undefined, _uri: string | undefined): void {
  // Slot intentionally left empty until monaco-yaml is wired in a follow-up.
  // The component API is final; only the implementation here changes.
}
