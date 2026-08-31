<!--
SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
Copyright (c) 2026 Onibex, LLC. All rights reserved.
-->

# This folder is the website, not the documentation

GitHub Pages is configured to publish this repository from `main` at `/docs`, so everything
here is served at **<https://onibex.github.io/agentic-semantic-knowledge-ask/>**.

**The documentation does not live here.** The manual is [`platform/docs/`](../platform/docs/)
and the specification is [`definition/`](../definition/). Adding a page to this folder puts it
on the public site; adding one to the manual does not. Those are different decisions, and this
README exists because the folder name suggests otherwise.

| | |
|---|---|
| `index.md` | The landing page. Jekyll serves it at the site root |
| `llms.txt` | **A copy.** The authoritative one is [`../llms.txt`](../llms.txt) at the repository root, because that is where agents look for it. Pages needs its own copy to serve it from the site root, so the file exists twice and CI compares the two with `cmp`. **Change both or the build fails.** |
| `images/` | Only what the landing page and the repository front page use. The manual's screenshots live in `platform/docs/images/` |

`images/ask-banner.png` is generated from `images/ask-banner.svg`, which is the editable
source. Keep them together.

---

[← Back to the repository overview](../README.md)
