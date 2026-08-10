import { DiffEditor } from '@monaco-editor/react'

interface Props {
  /** Content of the earlier revision (left pane). */
  original: string
  /** Content of the later revision (right pane). */
  modified: string
  /** Display label for the left commit (rendered above the editor). */
  fromSha: string
  /** Display label for the right commit (rendered above the editor). */
  toSha: string
  /** Monaco language id for syntax highlighting. Defaults to ``yaml``. */
  language?: string
  /** Optional fixed height; defaults to fill the parent. */
  height?: string | number
}

/**
 * Monaco-powered diff viewer.
 *
 * Reuses the same engine VS Code ships, so the user sees side-by-side
 * highlighting, syntax-aware coloring, line numbers and a minimap — for free.
 * Replaces the legacy ``SimpleDiffViewer`` (line-by-line ``<pre>`` rendering).
 *
 * Important: this component takes the FULL content of both revisions, NOT
 * a unified diff string. The History endpoint must therefore return both
 * blobs (or this component fetches them). When only a unified diff is
 * available, fall back to ``SimpleDiffViewer``.
 */
export function MonacoDiffViewer({
  original,
  modified,
  fromSha,
  toSha,
  language = 'yaml',
  height = '100%',
}: Props) {
  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="px-3 py-2 border-b border-gray-200 shrink-0 bg-gray-50">
        <span className="text-xs font-medium text-gray-600">
          Changes from{' '}
          <span className="font-mono bg-gray-100 px-1 rounded">{fromSha.slice(0, 7)}</span>{' '}
          <span className="text-gray-400">→</span>{' '}
          <span className="font-mono bg-gray-100 px-1 rounded">{toSha.slice(0, 7)}</span>
        </span>
      </div>
      <div className="flex-1 min-h-0">
        <DiffEditor
          height={height}
          language={language}
          original={original}
          modified={modified}
          options={{
            readOnly: true,
            renderSideBySide: true,
            scrollBeyondLastLine: false,
            fontSize: 12,
            lineNumbers: 'on',
            minimap: { enabled: false },
            wordWrap: 'on',
          }}
        />
      </div>
    </div>
  )
}
