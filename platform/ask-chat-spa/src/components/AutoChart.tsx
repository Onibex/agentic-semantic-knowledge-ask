/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useEffect, useRef } from 'react'
import type Plotly from 'plotly.js'

// ── Chart type detection (port of charts.py auto_chart logic) ─────────────────

type Row = Record<string, unknown>

function isNumeric(values: unknown[]): boolean {
  const nonNull = values.filter((v) => v != null && v !== '')
  if (nonNull.length === 0) return false
  return nonNull.every((v) => !isNaN(Number(v)))
}

function isYearColumn(values: unknown[]): boolean {
  const nums = values.map(Number).filter((n) => !isNaN(n))
  if (nums.length === 0) return false
  return nums.every((n) => n >= 1900 && n <= 2100 && Number.isInteger(n))
}

function isDateString(values: unknown[]): boolean {
  const strs = values.filter((v) => typeof v === 'string' && v.trim() !== '')
  if (strs.length === 0) return false
  if (isYearColumn(values)) return false
  return strs.every((s) => !isNaN(Date.parse(s as string)))
}

type ChartSpec = {
  type: 'bar' | 'h_bar' | 'line'
  x: string
  y: string
  xIsDate: boolean
  xIsYear: boolean
}

function detectChart(rows: Row[]): ChartSpec | null {
  if (rows.length < 2) return null
  const keys = Object.keys(rows[0])
  if (keys.length < 2) return null

  const colValues = (k: string) => rows.map((r) => r[k])
  const numericCols = keys.filter((k) => isNumeric(colValues(k)))
  const yearCols = keys.filter((k) => isYearColumn(colValues(k)))
  const categoryCols = keys.filter((k) => !numericCols.includes(k))

  if (numericCols.length === 0) return null

  // Pick the numeric column with the highest max value (most meaningful to chart)
  const colMax = (k: string) => Math.max(...rows.map((r) => Number(r[k])))
  const y = numericCols.reduce((best, k) => (colMax(k) > colMax(best) ? k : best), numericCols[0])

  let x = categoryCols.length > 0 ? categoryCols[0] : keys[0]
  if (x === y) x = keys.find((k) => k !== y) ?? keys[0]

  const xVals = colValues(x)
  const xIsYear = yearCols.includes(x) || isYearColumn(xVals)
  const xIsDate = !xIsYear && isDateString(xVals)

  let type: ChartSpec['type'] = 'bar'
  if (xIsDate) type = 'line'
  else if (!xIsYear && rows.length > 8) type = 'h_bar'

  return { type, x, y, xIsDate, xIsYear }
}

// ── Plotly wrapper ─────────────────────────────────────────────────────────────

interface AutoChartProps {
  rows: Row[]
  title?: string
}

export function AutoChart({ rows, title = '' }: AutoChartProps) {
  const divRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!divRef.current || rows.length === 0) return

    const spec = detectChart(rows)
    if (!spec) return

    const { type, x, y, xIsDate, xIsYear } = spec

    let xVals: (string | number)[] = rows.map((r) => {
      const v = r[x]
      if (xIsYear) return String(v)
      if (xIsDate) return new Date(v as string).toISOString()
      return String(v ?? '')
    })
    const yVals = rows.map((r) => Number(r[y]))

    const BLUE_SCALE = [
      [0, '#bfdbfe'],
      [1, '#1d4ed8'],
    ]

    const layout: Partial<Plotly.Layout> = {
      title: { text: title, font: { size: 13, color: '#374151' }, x: 0, xanchor: 'left' },
      plot_bgcolor: 'rgba(0,0,0,0)',
      paper_bgcolor: 'rgba(0,0,0,0)',
      font: { family: 'Inter, sans-serif', size: 12, color: '#374151' },
      margin: { t: title ? 45 : 20, b: 50, l: 60, r: 20 },
      xaxis: { gridcolor: '#f3f4f6', linecolor: '#e5e7eb', automargin: true },
      yaxis: { gridcolor: '#f3f4f6', linecolor: '#e5e7eb', automargin: true },
    }

    let traces: Plotly.Data[] = []

    if (type === 'bar') {
      traces = [
        {
          type: 'bar',
          x: xVals,
          y: yVals,
          marker: {
            color: yVals,
            colorscale: BLUE_SCALE,
            showscale: false,
            line: { width: 0 },
          },
          text: rows.length <= 12 ? yVals.map((v) => v.toLocaleString()) : [],
          textposition: 'outside',
        } as Plotly.Data,
      ]
    } else if (type === 'h_bar') {
      const sorted = [...rows].sort((a, b) => Number(a[y]) - Number(b[y]))
      const xSorted = sorted.map((r) => Number(r[y]))
      const ySorted = sorted.map((r) => String(r[x] ?? ''))
      traces = [
        {
          type: 'bar',
          orientation: 'h',
          x: xSorted,
          y: ySorted,
          marker: {
            color: xSorted,
            colorscale: BLUE_SCALE,
            showscale: false,
            line: { width: 0 },
          },
          text: rows.length <= 15 ? xSorted.map((v) => v.toLocaleString()) : [],
          textposition: 'outside',
        } as Plotly.Data,
      ]
      layout.yaxis = { ...layout.yaxis, autorange: 'reversed' as const, automargin: true }
      layout.margin = { t: title ? 45 : 20, b: 40, l: 140, r: 40 }
    } else {
      // line
      if (xIsDate) {
        xVals = xVals.map((v) => new Date(v as string).toLocaleDateString())
      }
      traces = [
        {
          type: 'scatter',
          mode: 'lines+markers',
          x: xVals,
          y: yVals,
          line: { color: '#2563eb', width: 2.5 },
          marker: { color: '#2563eb', size: 6 },
        } as Plotly.Data,
      ]
    }

    import('plotly.js-dist-min').then((PlotlyModule) => {
      const P = (PlotlyModule as unknown as { default: typeof import('plotly.js') }).default ?? PlotlyModule
      if (divRef.current) {
        P.newPlot(divRef.current, traces, layout, {
          displayModeBar: true,
          modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
          responsive: true,
          displaylogo: false,
        })
      }
    })

    return () => {
      import('plotly.js-dist-min').then((PlotlyModule) => {
        const P = (PlotlyModule as unknown as { default: typeof import('plotly.js') }).default ?? PlotlyModule
        if (divRef.current) P.purge(divRef.current)
      })
    }
  }, [rows, title])

  return <div ref={divRef} className="w-full" style={{ minHeight: 280 }} />
}
