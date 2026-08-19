# Third-Party Notices

**Onibex ASK — Agentic Semantic Knowledge**
Copyright (c) 2026 Onibex, LLC. All rights reserved.

This repository is source-available under [LICENSE](LICENSE) (PolyForm
Strict License 1.0.0 / PolyForm Free Trial License 1.0.0). That license
covers **only Onibex's own material** in this repository — the code under
`platform/packages/ask-*`, the three SPAs, and the ASK specification under
`definition/`.

This document lists the direct third-party dependencies pulled in at build
or install time. Each keeps its own license, listed below; nothing in
`LICENSE` relicenses them, and when you build or deploy the platform you are
responsible for complying with those licenses. Audited on 2026-08-13 and re-audited on 2026-08-19 over the real
transitive closure — every `package-lock.json` plus the declared Python
dependencies resolved through PyPI. Versions and licenses are current as of
that date; re-audit before a release with `python scripts/dependency_licenses.py`.

## Python — `platform/packages/*`, `platform/requirements.txt`

| Component | License |
|---|---|
| FastAPI, Uvicorn | MIT / BSD-3-Clause |
| Pydantic, pydantic-settings | MIT |
| httpx, python-dotenv | BSD License / BSD-3-Clause |
| python-multipart | Apache-2.0 |
| LangChain (`langchain`, `langchain-core`, `langgraph`, `langchain-community`, `langchain-openai`, `langchain-anthropic`, `langchain-aws`, `langchain-google-*`) | MIT |
| LiteLLM, `langchain-litellm` | MIT |
| boto3, botocore, aioboto3 | Apache-2.0 |
| openai | Apache License |
| opensearch-py | Apache-2.0 |
| `ruamel.yaml` | MIT |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| structlog | MIT / Apache-2.0 (dual) |
| GitPython | BSD-3-Clause |
| NetworkX | BSD-3-Clause |
| PyYAML | MIT |
| python-jose | MIT |
| SAP AI Core SDK (`ai-core-sdk`), `ai-api-client-sdk`, `generative-ai-hub-sdk` | SAP-published, **Other/Proprietary License** ⚠ — not OSI-approved; see each package's own terms |
| `sap-xssec` | Apache-2.0 |
| **`psycopg2-binary`** (PostgreSQL driver) | **GNU LGPL, with psycopg's linking exception** ⚠ — the exception permits use from proprietary applications; see the package's `LICENSE` for the exact exception text |
| **`hdbcli`** (SAP HANA client) | **SAP Developer License Agreement** ⚠ — not an OSI-approved open-source license; governs redistribution of the HANA client separately from this repository's license |
| `ibm-db` (IBM Db2 client) | Apache-2.0 wrapper over IBM's Db2 CLI driver — the underlying driver carries IBM's own distribution terms |
| `presto-python-client`, `snowflake-connector-python`, `databricks-sql-connector`, `clickhouse-connect`, `google-cloud-bigquery` | Apache-2.0 |
| `pyodbc` | MIT |
| `certifi` (CA bundle, transitive) | MPL-2.0 — used unmodified, so the MPL's source-disclosure obligation is not triggered |
| `orjson`, `tqdm` (transitive) | dual: MPL-2.0 AND (Apache-2.0 OR MIT) / MPL-2.0 AND MIT |

## JavaScript/TypeScript — `ask-chat-spa/`, `ask-studio-spa/`, `ask-setup-spa/`

Direct `dependencies` (audited via `license-checker`): React, React DOM,
React Router, Zustand, Axios, Zod, React Hook Form, TanStack Query, Radix UI
(`@radix-ui/*`), `lucide-react`, `sonner`, `clsx`, `tailwind-merge`,
`class-variance-authority`, Monaco Editor (`@monaco-editor/react`,
`monaco-editor` — admin SPA only), React Flow (`reactflow`, `dagre` — admin
SPA only), `plotly.js-dist-min` (chat SPA only) — **all MIT**.

Build-time-only tooling (Vite, Rolldown, TypeScript, `lightningcss`) pulls in
a handful of non-MIT licenses (Apache-2.0, BSD-3-Clause, 0BSD, and MPL-2.0 for
`lightningcss`); these run only at build time and do not ship inside the built
application bundle.

One runtime dependency is not MIT: **`dompurify`**, pulled in by
`monaco-editor` in the admin SPA, is dual-licensed **MPL-2.0 OR Apache-2.0**.
It does ship in that bundle. Onibex elects **Apache-2.0** for it, so no MPL
obligation attaches; the library is used unmodified in either case.

## JavaScript — `platform/services/ask-mcp-server/`

This service wraps a published proxy rather than implementing the MCP protocol
itself. Its dependency tree is now pinned and locked so that it can be audited;
before that it resolved `latest` on every install, which left the set of
components — and their licenses — unpredictable.

| Component | License |
|---|---|
| `odata-mcp-proxy` (the proxy this service runs) | MIT |
| `@hono/node-server`, `@modelcontextprotocol/*`, `winston` and the rest of the tree (189 packages) | MIT, ISC, BSD-2-Clause, BSD-3-Clause |
| `@mcp-ui/server`, `@sap-cloud-sdk/*` | Apache-2.0 |
| **`@sap/xssec`** (SAP XSUAA security) | **SAP Developer License Agreement** ⚠ — not an OSI-approved license; governs redistribution separately from this repository's license |
| **`@sap/xsenv`** (SAP service bindings) | **SAP-published**, terms in the package's own LICENSE file ⚠ — not OSI-approved |
| `node-forge` | dual **BSD-3-Clause OR GPL-2.0**; Onibex elects **BSD-3-Clause**, so no GPL obligation attaches |

The npm `@sap/xssec` above is a different package from the Python `sap-xssec`
listed earlier, which is Apache-2.0.

## Notes

- Any DB driver you enable via `EXECUTOR_EXTRAS` beyond the ones listed above
  is your own addition and carries its own license — check it before enabling.
- SAP HANA, SAP BTP, and SAP AI Core are trademarks of SAP SE. Apache, Apache
  Kafka, and the Apache feather logo are trademarks of the Apache Software
  Foundation. OpenSearch is a registered trademark of Amazon Web Services.
  Keycloak is a trademark of Red Hat, Inc. CONFLUENT is a registered trademark
  of Confluent, Inc. Onibex is not affiliated with, and is not endorsed by, the
  Apache Software Foundation. All marks are used for identification only.

## Closing clause

Third-party components retain their own licenses; nothing in `LICENSE`
relicenses them. The Onibex license applies only to Onibex's own material in
this repository — the code under the `ask-*` packages/SPAs and the ASK
specification under `definition/`.

================================================================================
Apache License 2.0 — full text (applies to the Apache-2.0-licensed components above)
================================================================================


                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the union of the acting entity and all
      other entities that control, are controlled by, or are under common
      control with that entity. For the purposes of this definition,
      "control" means (i) the power, direct or indirect, to cause the
      direction or management of such entity, whether by contract or
      otherwise, or (ii) ownership of fifty percent (50%) or more of the
      outstanding shares, or (iii) beneficial ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or
          Derivative Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and
          do not modify the License. You may add Your own attribution
          notices within Derivative Works that You distribute, alongside
          or as an addendum to the NOTICE text from the Work, provided
          that such additional attribution notices cannot be construed
          as modifying the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on Your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS

   APPENDIX: How to apply the Apache License to your work.

      To apply the Apache License to your work, attach the following
      boilerplate notice, with the fields enclosed by brackets "[]"
      replaced with your own identifying information. (Don't include
      the brackets!)  The text should be enclosed in the appropriate
      comment syntax for the file format. We also recommend that a
      file or class name and description of purpose be included on the
      same "printed page" as the copyright notice for easier
      identification within third-party archives.

   Copyright [yyyy] [name of copyright owner]

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
