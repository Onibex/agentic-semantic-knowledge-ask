# Changelog

All notable changes to Onibex ASK are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

One version covers the whole repository. What each number means here:

- **MAJOR** — a contract someone already depends on breaks: the semantic-layer
  YAML contract, an existing `/v1` endpoint, a required environment variable,
  or an index change that forces a reindex.
- **MINOR** — backward-compatible capability: a new SQL-generation mode, a new
  connector, an optional YAML field, a new flow in the UI.
- **PATCH** — a fix that changes no contract: bug fixes, security patches,
  documentation, dependency bumps.

The `/v1` in the HTTP routes is the API contract version and moves far more
slowly than the product version.

## [Unreleased]

### Changed

- Every manifest now states the same version as the release. The Python
  packages said `0.1.0` and the SPAs `0.0.0` while the product was tagged
  `v1.0.0` — none of them is published to an index, so the number was pure
  signal, and it signalled unstable components inside a stable product.
  `scripts/versions.py` moves them together and CI fails if they drift or if a
  tag disagrees with what the code claims.
- `services/ask-mcp-server` is marked `private`, like the three SPAs. Without
  it, an accidental `npm publish` would put source-available code on a public
  registry, which the license does not permit.

### Added

- This changelog, and a supported-versions policy in `SECURITY.md`.

## [1.0.0] — 2026-08-19

First tagged release. ASK has been in development before this point; the tag
marks where its licensing became complete and consistent enough to publish.

### Added

- **The ASK specification** under `definition/` — the runtime-neutral YAML
  contract for Bronze/Silver/Gold data products.
- **The Onibex ASK Platform** under `platform/` — orchestrator, ASK Studio,
  ASK Chat, ASK Setup, and the manual under `platform/docs/`.
- `llms.txt`, published at
  <https://onibex.github.io/agentic-semantic-knowledge-ask/llms.txt>, so an AI
  agent can establish what this project is and whether it may use it.
- `scripts/license_headers.py` and `scripts/dependency_licenses.py` — the
  license header pass and the dependency audit, both enforced in CI.

### Changed

- Licensing moved to a dual **PolyForm Strict 1.0.0 OR PolyForm Free Trial
  1.0.0** grant, with commercial use covered separately by
  `COMMERCIAL-LICENSE.md`.
- Copyright holder settled as **Onibex, LLC** across every licensing file,
  README, and source header.
- Every source file that can carry a comment now carries an SPDX header —
  652 files — with a required CI job and a pre-commit hook to keep it that way.
- Trademark attribution completed for the Apache Software Foundation, SAP SE,
  Confluent, Inc., Amazon Web Services, and Red Hat.

### Fixed

- `CITATION.cff` did not validate: CFF 1.2.0 accepts only identifiers from the
  official SPDX License List, and PolyForm is not on it. The licenses now live
  in `license-url`, so "Cite this repository" works.
- `THIRD-PARTY-NOTICES.md` claimed every runtime dependency of the SPAs was
  MIT. `dompurify` (MPL-2.0 OR Apache-2.0) reaches the admin bundle through
  `monaco-editor`; Onibex elects Apache-2.0 for it. The MPL-licensed Python
  transitives are listed as well.

[Unreleased]: https://github.com/Onibex/agentic-semantic-knowledge-ask/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Onibex/agentic-semantic-knowledge-ask/releases/tag/v1.0.0
