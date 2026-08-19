#!/usr/bin/env node
/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

// Sync the canonical design files into each SPA (single source of truth).
//
//   node scripts/sync-design-tokens.mjs           # copy design/*.css -> each app/src/*.css
//   node scripts/sync-design-tokens.mjs --check    # assert copies are byte-identical (CI)
//
// The copy model (no monorepo workspace yet — plan decision #3) keeps the
// design layer as ONE authored source while each app's Dockerfile still builds
// from its own folder. CI runs `--check` so the copies can never silently
// drift. Two files are synced:
//   tokens.css  — raw CSS custom properties (values), framework-agnostic
//   theme.css   — the Tailwind v4 @theme mapping (values -> utilities)

import { readFileSync, writeFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const APPS = ['ask-admin-spa', 'ask-chat-spa', 'ask-setup-spa']
const FILES = ['tokens.css', 'theme.css']

const check = process.argv.includes('--check')
let drift = false

for (const file of FILES) {
  const canonical = readFileSync(join(ROOT, 'design', file), 'utf8')
  for (const app of APPS) {
    const dest = join(ROOT, app, 'src', file)
    let current = null
    try {
      current = readFileSync(dest, 'utf8')
    } catch {
      /* missing */
    }
    if (check) {
      if (current !== canonical) {
        drift = true
        console.error(`DRIFT: ${app}/src/${file} differs from design/${file}`)
      }
    } else if (current !== canonical) {
      writeFileSync(dest, canonical)
      console.log(`synced  -> ${app}/src/${file}`)
    } else {
      console.log(`ok      -> ${app}/src/${file}`)
    }
  }
}

if (check && drift) {
  console.error('\nDesign files drifted. Run: node scripts/sync-design-tokens.mjs')
  process.exit(1)
}
console.log(check ? '\nDesign files in sync.' : '\nDesign files synced.')
