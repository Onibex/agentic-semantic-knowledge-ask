<!--
SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
Copyright (c) 2026 Onibex, LLC. All rights reserved.
-->

# Repository checks

Small, dependency-free scripts. Each one runs locally exactly as it runs in CI, and each
exists because something decayed silently once.

| Script | Guards |
|---|---|
| `docs_links.py` | Every relative link and `#anchor` resolves; every manual page is in the index, carries a way back, and is called by one name. |
| `docs_terms.py` | The surfaces keep the names the product gives them, including across a line wrap. |
| `license_headers.py` | Every source file carries its SPDX header. |
| `versions.py` | One repository, one version: fifteen files agree, and a release tag matches. |
| `dependency_licenses.py` | No dependency arrives with a licence the two tracks cannot ship. |

```bash
python scripts/docs_links.py --check
python scripts/docs_terms.py --check
```

**Run them after `git add`.** All of them read what git tracks, so an unstaged new file passes
locally and fails in CI.
