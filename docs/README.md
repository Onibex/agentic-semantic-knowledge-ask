<!--
SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
Copyright (c) 2026 Onibex, LLC. All rights reserved.
-->

# GitHub Pages site

The public website for this repository. GitHub Pages publishes from `main` at `/docs`, so
everything in this folder is served at
**<https://onibex.github.io/agentic-semantic-knowledge-ask/>**.

It is a landing page: the pitch, one screenshot, and the links onward. The documentation
itself lives in [`platform/docs/`](../platform/docs/) for the manual and
[`definition/`](../definition/) for the specification. Publishing a page to the site and
adding one to the manual are separate decisions, so a page written there does not appear
here.

| | |
|---|---|
| `index.md` | The landing page, served at the site root. It mirrors the pitch on the repository front page: when [`../README.md`](../README.md) changes what ASK is or how you start it, change it here too |
| `llms.txt` | A copy of [`../llms.txt`](../llms.txt). The root one is authoritative, because that is where agents look for it, and Pages needs its own to serve it from the site root. CI compares the two with `cmp`, so **change both or the build fails** |
| `images/` | Only what the landing page and the repository front page use. The manual's screenshots are in [`platform/docs/images/`](../platform/docs/images/) |

`images/ask-banner.png` is generated from `images/ask-banner.svg`, which is the editable
source. Keep them together.

---

[← Back to the repository overview](../README.md)
