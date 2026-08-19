/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { type ReactNode } from 'react'

// ── Inline formatting ──────────────────────────────────────────────────────────

function parseInline(text: string): ReactNode {
  const parts: ReactNode[] = []
  // Combined regex: **bold**, *italic*, `code`, [link](url)
  const re = /(\*\*(.+?)\*\*|\*(.+?)\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\))/g
  let last = 0
  let m: RegExpExecArray | null

  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    if (m[2]) parts.push(<strong key={m.index} className="font-semibold text-gray-900">{m[2]}</strong>)
    else if (m[3]) parts.push(<em key={m.index} className="italic">{m[3]}</em>)
    else if (m[4]) parts.push(
      <code key={m.index} className="rounded bg-gray-100 px-1 py-0.5 font-mono text-[0.85em] text-blue-800">
        {m[4]}
      </code>
    )
    else if (m[5]) parts.push(
      <a key={m.index} href={m[6]} className="text-blue-600 underline hover:text-blue-800" target="_blank" rel="noreferrer">
        {m[5]}
      </a>
    )
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts.length === 1 ? parts[0] : <>{parts}</>
}

// ── Block parser ───────────────────────────────────────────────────────────────

type Block =
  | { type: 'h1' | 'h2' | 'h3' | 'h4'; text: string }
  | { type: 'hr' }
  | { type: 'ul'; items: string[] }
  | { type: 'ol'; items: string[] }
  | { type: 'code'; lang: string; body: string }
  | { type: 'blockquote'; text: string }
  | { type: 'table'; headers: string[]; rows: string[][] }
  | { type: 'p'; text: string }

function parseBlocks(content: string): Block[] {
  const lines = content.split('\n')
  const blocks: Block[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Fenced code block
    if (line.trimStart().startsWith('```')) {
      const lang = line.replace(/^```/, '').trim()
      const body: string[] = []
      i++
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) {
        body.push(lines[i])
        i++
      }
      blocks.push({ type: 'code', lang, body: body.join('\n') })
      i++
      continue
    }

    // HR
    if (/^(\s*[-*_]){3,}\s*$/.test(line)) {
      blocks.push({ type: 'hr' })
      i++
      continue
    }

    // Headings
    const h4 = line.match(/^####\s+(.+)/)
    const h3 = line.match(/^###\s+(.+)/)
    const h2 = line.match(/^##\s+(.+)/)
    const h1 = line.match(/^#\s+(.+)/)
    if (h4) { blocks.push({ type: 'h4', text: h4[1] }); i++; continue }
    if (h3) { blocks.push({ type: 'h3', text: h3[1] }); i++; continue }
    if (h2) { blocks.push({ type: 'h2', text: h2[1] }); i++; continue }
    if (h1) { blocks.push({ type: 'h1', text: h1[1] }); i++; continue }

    // Blockquote
    if (line.startsWith('> ')) {
      const text = line.slice(2)
      blocks.push({ type: 'blockquote', text })
      i++
      continue
    }

    // Markdown table
    if (line.includes('|') && i + 1 < lines.length && lines[i + 1].match(/^\|?[\s:|-]+\|/)) {
      const parseRow = (r: string) =>
        r.split('|').map((c) => c.trim()).filter((_, idx, arr) => idx > 0 && idx < arr.length - 1)
      const headers = parseRow(line)
      i += 2 // skip separator
      const rows: string[][] = []
      while (i < lines.length && lines[i].includes('|')) {
        rows.push(parseRow(lines[i]))
        i++
      }
      if (headers.length > 0) {
        blocks.push({ type: 'table', headers, rows })
        continue
      }
    }

    // Unordered list
    if (/^[-*+]\s/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^[-*+]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*+]\s/, ''))
        i++
      }
      blocks.push({ type: 'ul', items })
      continue
    }

    // Ordered list
    if (/^\d+\.\s/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s/, ''))
        i++
      }
      blocks.push({ type: 'ol', items })
      continue
    }

    // Blank line
    if (line.trim() === '') {
      i++
      continue
    }

    // Paragraph — merge consecutive lines not consumed by any specific handler.
    // Use the EXACT same conditions as each handler above so that lines starting
    // with `**bold**` (not a list item) are NOT mistakenly excluded here, which
    // would cause an infinite loop in the outer while.
    const pLines: string[] = []
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !lines[i].trimStart().startsWith('```') &&
      !/^(\s*[-*_]){3,}\s*$/.test(lines[i]) &&
      !/^#{1,4}\s/.test(lines[i]) &&
      !/^>\s/.test(lines[i]) &&
      !/^[-*+]\s/.test(lines[i]) &&
      !/^\d+\.\s/.test(lines[i])
    ) {
      pLines.push(lines[i])
      i++
    }
    if (pLines.length > 0) {
      blocks.push({ type: 'p', text: pLines.join(' ') })
    } else {
      // Safety: if nothing matched and nothing was consumed, advance i to
      // prevent an infinite loop on unrecognised line patterns.
      i++
    }
  }

  return blocks
}

// ── Block renderers ────────────────────────────────────────────────────────────

function renderBlock(block: Block, idx: number): ReactNode {
  switch (block.type) {
    case 'h1':
      return <h1 key={idx} className="text-xl font-bold text-gray-900 mt-6 mb-2 first:mt-0">{parseInline(block.text)}</h1>
    case 'h2':
      return <h2 key={idx} className="text-lg font-semibold text-gray-900 mt-5 mb-2 border-b border-gray-100 pb-1">{parseInline(block.text)}</h2>
    case 'h3':
      return <h3 key={idx} className="text-base font-semibold text-gray-800 mt-4 mb-1.5">{parseInline(block.text)}</h3>
    case 'h4':
      return <h4 key={idx} className="text-sm font-semibold text-gray-700 mt-3 mb-1">{parseInline(block.text)}</h4>
    case 'hr':
      return <hr key={idx} className="my-4 border-gray-200" />
    case 'blockquote':
      return (
        <blockquote key={idx} className="border-l-4 border-blue-200 pl-4 py-1 text-gray-600 italic bg-blue-50/50 rounded-r-md my-2">
          {parseInline(block.text)}
        </blockquote>
      )
    case 'code':
      return (
        <div key={idx} className="my-3 rounded-lg border border-gray-200 overflow-hidden">
          {block.lang && (
            <div className="bg-gray-100 px-3 py-1 text-[10px] font-mono font-semibold text-gray-500 uppercase">
              {block.lang}
            </div>
          )}
          <pre className="overflow-x-auto bg-gray-50 px-4 py-3 text-[12px] leading-relaxed font-mono text-gray-800 whitespace-pre">
            {block.body}
          </pre>
        </div>
      )
    case 'ul':
      return (
        <ul key={idx} className="my-2 space-y-1 pl-5 list-none">
          {block.items.map((item, j) => (
            <li key={j} className="text-gray-700 flex items-start gap-2">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-400" />
              <span>{parseInline(item)}</span>
            </li>
          ))}
        </ul>
      )
    case 'ol':
      return (
        <ol key={idx} className="my-2 space-y-1 pl-5">
          {block.items.map((item, j) => (
            <li key={j} className="text-gray-700 flex items-start gap-2">
              <span className="shrink-0 w-5 text-right text-xs font-semibold text-blue-500 tabular-nums">
                {j + 1}.
              </span>
              <span>{parseInline(item)}</span>
            </li>
          ))}
        </ol>
      )
    case 'table':
      return (
        <div key={idx} className="my-3 overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                {block.headers.map((h, j) => (
                  <th key={j} className="px-4 py-2 text-left text-xs font-semibold text-gray-600">
                    {parseInline(h)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, j) => (
                <tr key={j} className={`border-b border-gray-100 ${j % 2 === 1 ? 'bg-gray-50/50' : 'bg-white'}`}>
                  {row.map((cell, k) => (
                    <td key={k} className="px-4 py-2 text-gray-700">{parseInline(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    case 'p':
      return (
        <p key={idx} className="text-gray-700 leading-relaxed">
          {parseInline(block.text)}
        </p>
      )
    default:
      return null
  }
}

// ── Public component ───────────────────────────────────────────────────────────

export function MarkdownContent({ content }: { content: string }) {
  const blocks = parseBlocks(content)
  return (
    <div className="space-y-2 text-sm">
      {blocks.map((block, i) => renderBlock(block, i))}
    </div>
  )
}
