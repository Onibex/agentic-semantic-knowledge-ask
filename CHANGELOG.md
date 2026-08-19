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

- **Infrastructure names move from the legacy `agenticai` prefix to `ask`**, which
  is what the Compose service names already used. Containers are now
  `ask-orchestrator`, `ask-admin-api`, `ask-mcp` and so on; the Compose project
  is `onibex-ask`, the network `ask-net`, the images `ask-*`. On Kubernetes the
  namespace becomes `onibex-ask` and the objects the manifests consume are
  `xsuaa-ask-secret`, `keycloak-ask-secret` and `ask-config-pvc`.

  **This requires a fresh install. No migration path is provided.** The Compose
  project name prefixes the volumes, so the existing `opensearch-data` and
  `keycloak-data` will not be found under the new name: the stack comes up with
  no published semantic layer and no Keycloak realm. Anyone with a deployment
  that must keep its data should copy the volumes across before upgrading. The
  Kubernetes objects are consumed, not created, by these manifests, so the
  namespace, the XSUAA binding secret and the PVC have to exist under the new
  names before applying them.

  Two names were reached that are not infrastructure: the Entity Selector's
  system prompt said "Onibex AgenticAI pipeline", and generated documents ended
  with "Document prepared by AgenticAI Analytics" — visible to whoever receives
  the document. Both now say Onibex ASK.

- **`ask-admin-spa` is now `ask-studio-spa`.** The interface calls itself ASK
  Studio on every screen; only the code still said admin. The directory, the
  image, the container, the Kubernetes manifests and the Keycloak client id all
  move together — the client id matters, because the realm seed, the SPA default
  and `KEYCLOAK_CLIENT_ID` have to agree or nobody logs in.

  Deliberately left alone: `agentic-ai` as a keyword in `CITATION.cff`, in the
  GitHub topics and in the prose of `definition/README.md`. There it is the
  industry term people search for, not our prefix.

### Fixed

- `services/ask-mcp-server` declared its dependency as `latest` and shipped no
  lockfile, so its 189-package tree was invisible to the licence audit and
  could change on any install. Pinned to `odata-mcp-proxy` 1.3.0 with a
  lockfile committed. The audit that this made possible found three components
  that are not open source and were undocumented: `@sap/xssec` (SAP Developer
  License Agreement), `@sap/xsenv` and `ai-api-client-sdk`. All three are now
  named in `THIRD-PARTY-NOTICES.md`. The image build uses `npm ci` against that
  lockfile, so what ships is what was audited — copying only `package.json` and
  running `npm install` would have left the pin decorative.
- `scripts/dependency_licenses.py` read `A OR B` as an obligation under both.
  `node-forge` (BSD-3-Clause OR GPL-2.0) was reported as copyleft when the
  licensor offers a choice; false alarms are how a report stops being read. It
  now elects the permissive option and reports the choice. It also flags
  licences that are not open source at all, which it previously passed as fine.

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
