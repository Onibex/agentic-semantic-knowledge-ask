---
name: update-manual
description: >-
  Update or extend the Onibex ASK Platform user manual at platform/docs/ in THIS repo.
  Use when the user says "actualiza la documentación" / "update the docs/manual" after a
  code change, when adding or editing a manual flow/page, or when asked to sync the docs
  with the current UI. Handles the code→doc mapping, screenshots, house conventions and
  commit rules.
---

# Update the ASK Platform manual

The manual lives in **this repo** at `platform/docs/` — same tree as the code it
documents. A code change and its doc update belong in the same PR.

## Where things are
- **Code**: `platform/` — packages, the three SPAs, compose.
- **Manual**: `platform/docs/` — `README.md` (index), `01-installation.md`,
  `02-concepts.md`, `ask-studio/` (authoring flows), `ask-chat/`, `reference/`, `images/`.
- **Engine docs** (same folder, different audience): `FLASH.md`, `PRECISE.md`,
  `SMART.md`, `semantic-layer/`, `runbooks/`.
- **Spec** the manual references: `definition/` in this same repo — link RELATIVELY
  (e.g. from `platform/docs/ask-studio/` → `../../../definition/docs/...`).
- **`platform/docs/_authoring/`** (`DEMO_DATA.md`, `SCREENSHOTS.md`, `AUTHORING.md`) is
  **git-ignored** — internal aids, never shipped.

## Procedure
1. **Scope the change** — what did the code touch, especially user-facing UI (labels,
   buttons, dialogs, flows, new pages)?
2. **Edit** — read the actual component(s) under `platform/`, then edit the affected
   `.md` in `platform/docs/`: exact UI labels, steps, tables, cross-links.
3. **Screenshots** — if the UI changed, mark the affected shots in
   `platform/docs/_authoring/SCREENSHOTS.md` as **RE-CAPTURE** (with a one-line reason).
   **Never fabricate or edit images — only the user recaptures.** List which files need
   re-shooting.
4. **Commit** on a branch `docs/<feature>`; if the doc change accompanies a code change,
   same branch/PR. **Do NOT push or merge without the user's explicit "ok".**
5. **Report** — pages changed + screenshots flagged for re-capture + the branch name.

## Conventions (must hold — this is client-facing documentation)
- **Formal, icon-free.** No emoji/glyphs (`⚠ ⋯ ⚙ ✓ 🔒 ▸ …`) — name UI controls in words.
  Keep only typographic `→` (nav/journeys), `—`, `·`, `…`.
- **No authoring artifacts in shipped docs**: no `<!-- CAPTURE -->` comments, no
  "Screenshots to capture" tables, no "Save all images" notes.
- **One illustrative scenario**: SAP Production Planning — Production Orders
  (AFKO / AFPO / AUFK / AFRU; Silver `production_order`, Gold `production_performance`).
  Use `_authoring/DEMO_DATA.md` values verbatim; keep each page's "examples are
  illustrative — substitute your own Data Products" note.
- **Naming**: product = *Onibex ASK Platform*; the three surfaces = *ASK Studio*
  (authoring), *ASK Chat*, *ASK Setup*; the queryable unit = *Data Product* (never
  "entity" in user-facing copy).
- **Images**: committed PNGs under `platform/docs/images/`, referenced with relative
  paths — NOT GitHub user-attachments.
- **New page** mirrors the template: Who/Time/Prerequisites table → "Where this fits"
  breadcrumb → Concepts (30-second version) → numbered steps with exact UI labels →
  the illustrative-example note.

## Verify before reporting
- All internal `.md` links resolve; image refs point under `images/`.
- No emoji/glyphs, no `<!-- CAPTURE -->`, no "Screenshots to capture" tables.
- Any Mermaid edge label with special characters (`()`, `=`) is wrapped in quotes:
  `-->|"label"|`.
