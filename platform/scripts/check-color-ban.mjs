#!/usr/bin/env node
// Color-ban ratchet for the SPA design system.
//
// Fails when an app gains NEW hardcoded Tailwind palette color utilities (or
// arbitrary [#hex] color classes) beyond its committed baseline. The large
// pre-existing tail documented in
// docs/ImplementationPlan/ITERATION_SPA_DESIGN_UNIFICATION_PLAN.md is
// grandfathered by the baseline; only net-new literals are blocked. As the
// tail is migrated to semantic tokens, run `--update` to ratchet the ceiling
// down so it can never regrow.
//
// Usage:
//   node scripts/check-color-ban.mjs            # check against baseline (CI)
//   node scripts/check-color-ban.mjs --update   # rewrite baseline to current counts
//
// Pure Node (no ripgrep dependency) so it runs identically locally and in CI.

import { readFileSync, writeFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname, extname, basename } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const APPS = ['ask-admin-spa', 'ask-chat-spa', 'ask-setup-spa']
const SCAN_EXT = new Set(['.ts', '.tsx', '.css'])
const SKIP_DIRS = new Set(['node_modules', 'dist', '.git', '.vite'])
// The canonical design-token files legitimately carry raw colors; they are the
// single allowed home for them and are drift-checked separately.
const SKIP_FILES = new Set(['tokens.css', 'theme.css'])
const BASELINE_PATH = join(ROOT, 'scripts', 'color-ban-baseline.json')

const PALETTE =
  /\b(bg|text|border|ring|fill|stroke|from|via|to|divide|outline|placeholder|caret|decoration|shadow|accent)-(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-[0-9]{2,3}\b/g
const HEX = /\[#[0-9a-fA-F]{3,8}\]/g

function walk(dir, acc = []) {
  let entries
  try {
    entries = readdirSync(dir)
  } catch {
    return acc
  }
  for (const name of entries) {
    const full = join(dir, name)
    const s = statSync(full)
    if (s.isDirectory()) {
      if (!SKIP_DIRS.has(name)) walk(full, acc)
    } else if (SCAN_EXT.has(extname(name)) && !SKIP_FILES.has(basename(name))) {
      acc.push(full)
    }
  }
  return acc
}

function countApp(app) {
  let n = 0
  for (const f of walk(join(ROOT, app, 'src'))) {
    const text = readFileSync(f, 'utf8')
    n += text.match(PALETTE)?.length ?? 0
    n += text.match(HEX)?.length ?? 0
  }
  return n
}

const current = Object.fromEntries(APPS.map((a) => [a, countApp(a)]))

if (process.argv.includes('--update')) {
  writeFileSync(BASELINE_PATH, JSON.stringify(current, null, 2) + '\n')
  console.log('Updated color-ban baseline:', current)
  process.exit(0)
}

let baseline
try {
  baseline = JSON.parse(readFileSync(BASELINE_PATH, 'utf8'))
} catch {
  console.error(`Missing baseline ${BASELINE_PATH}. Run: node scripts/check-color-ban.mjs --update`)
  process.exit(2)
}

let failed = false
let improved = false
console.log('Color-ban ratchet — hardcoded palette utilities per app:')
for (const app of APPS) {
  const cur = current[app] ?? 0
  const base = baseline[app] ?? 0
  const delta = cur - base
  const status =
    delta > 0 ? `FAIL (+${delta} net-new)` : delta < 0 ? `ok (${delta}; ratchet-down available)` : 'ok'
  console.log(`  ${app.padEnd(16)} ${String(cur).padStart(5)} (baseline ${base}) ${status}`)
  if (delta > 0) failed = true
  if (delta < 0) improved = true
}

if (failed) {
  console.error(
    '\nERROR: new hardcoded palette color utilities were added.\n' +
      'Use a semantic token instead (see design/tokens.css and the theme utilities:\n' +
      'bg-brand / text-foreground / bg-muted / border-border / ring-ring / bg-bronze …).',
  )
  process.exit(1)
}
if (improved) {
  console.log('\nCounts dropped below baseline — run `node scripts/check-color-ban.mjs --update` to lock it in.')
}
console.log('\nColor-ban OK.')
