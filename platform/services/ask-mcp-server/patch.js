/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * patch.js — Patches odata-mcp-proxy for Basic Auth and OData V4 error messages.
 * Runs automatically via postinstall. Safe to re-run.
 */
const fs   = require('fs');
const path = require('path');

// ── Patch 1: Basic Auth in destination-service.js ─────────────────────────────

const destTarget = path.join(
  __dirname,
  'node_modules/odata-mcp-proxy/dist/client/destination-service.js'
);

if (!fs.existsSync(destTarget)) {
  console.log('[patch] destination-service.js not found — skipping Basic Auth patch.');
} else {
  const destOriginal = fs.readFileSync(destTarget, 'utf8');
  const BASIC_AUTH_MARKER = '// [BASIC-AUTH-PATCH]';

  if (destOriginal.includes(BASIC_AUTH_MARKER)) {
    console.log('[patch] Basic Auth already patched — skipping.');
  } else {
    const BASIC_AUTH_BLOCK = `
    ${BASIC_AUTH_MARKER}
    const _basicUser = process.env[\`\${prefix}_USERNAME\`];
    const _basicPass = process.env[\`\${prefix}_PASSWORD\`];
    if (_basicUser && _basicPass) {
        const _rawUrl = process.env[\`\${prefix}_BASE_URL\`] || baseUrl || '';
        const _normalizedUrl = _rawUrl.replace(/\\/+$/, '');
        logger.info('Destination resolved via Basic Auth patch', {
            destinationName,
            baseUrl: _normalizedUrl,
        });
        return {
            url: _normalizedUrl,
            authentication: 'BasicAuthentication',
            username: _basicUser,
            password: _basicPass,
            isTrustingAllCertificates: true,
        };
    }
    `;

    const INSERTION_POINT = 'if (!baseUrl)';
    if (!destOriginal.includes(INSERTION_POINT)) {
      console.warn('[patch] WARNING: Could not find "if (!baseUrl)" insertion point — Basic Auth patch skipped.');
    } else {
      const patched = destOriginal.replace(INSERTION_POINT, BASIC_AUTH_BLOCK + INSERTION_POINT);
      fs.writeFileSync(destTarget, patched, 'utf8');
      console.log('[patch] Basic Auth patch applied.');
    }
  }
}

// ── Patch 3: CSRF token from service root (not entity set) ───────────────────
// The SDK auto-fetches the CSRF token from the mutation URL (e.g. A_SalesOrder)
// which can return 38MB+ and times out. This patch pre-fetches from the
// lightweight service root instead and injects the token manually.

const odataClientTarget = path.join(
  __dirname,
  'node_modules/odata-mcp-proxy/dist/client/odata-client.js'
);

if (!fs.existsSync(odataClientTarget)) {
  console.log('[patch] odata-client.js not found — skipping CSRF root patch.');
} else {
  const clientOriginal = fs.readFileSync(odataClientTarget, 'utf8');
  const CSRF_ROOT_MARKER = '// [CSRF-ROOT-PATCH-v2]';

  if (clientOriginal.includes(CSRF_ROOT_MARKER)) {
    console.log('[patch] CSRF root patch already applied — skipping.');
  } else {
    // Step A: disable SDK's auto-fetch by replacing the csrfProtected ternary.
    // Regex handles any whitespace variation around the ternary.
    const TERNARY_RE = /this\.csrfProtected\s*\?\s*undefined\s*:\s*\{\s*fetchCsrfToken:\s*false\s*\}/;
    if (!TERNARY_RE.test(clientOriginal)) {
      console.warn('[patch] WARNING: csrfProtected ternary not found — CSRF root patch skipped.');
    } else {
      // Step B: insert our pre-fetch block just before the `const response = await executeHttpRequest` call.
      // The anchor is the Content-Type header assignment which immediately precedes that call.
      const INSERT_RE = /(headers\['Content-Type'\]\s*=\s*'application\/json';\s*\})\s*(const response\s*=\s*await executeHttpRequest)/;
      if (!INSERT_RE.test(clientOriginal)) {
        console.warn('[patch] WARNING: Could not find insertion anchor — CSRF root patch skipped.');
      } else {
        let patched = clientOriginal;

        // Disable SDK CSRF auto-fetch
        patched = patched.replace(TERNARY_RE, '{ fetchCsrfToken: false }');

        // Insert CSRF pre-fetch before executeHttpRequest
        patched = patched.replace(INSERT_RE, `$1
        ${CSRF_ROOT_MARKER}
        if (this.csrfProtected) {
            try {
                const _csrfResp = await executeHttpRequest(destination, {
                    method: 'GET',
                    url: this.pathPrefix,
                    headers: { 'X-CSRF-Token': 'Fetch' },
                    signal: AbortSignal.timeout(10000),
                }, { fetchCsrfToken: false });
                const _csrfToken = (_csrfResp.headers || {})['x-csrf-token'];
                if (_csrfToken) { headers['X-CSRF-Token'] = _csrfToken; }
                // Forward session cookie — SAP validates CSRF against the session that issued it
                const _setCookie = (_csrfResp.headers || {})['set-cookie'];
                if (_setCookie) {
                    const _cookieArr = Array.isArray(_setCookie) ? _setCookie : [_setCookie];
                    headers['Cookie'] = _cookieArr.map(function(c) { return c.split(';')[0]; }).join('; ');
                }
            } catch (_e) {}
        }
        $2`);

        if (patched === clientOriginal) {
          console.warn('[patch] WARNING: CSRF root patch had no effect — skipping write.');
        } else {
          fs.writeFileSync(odataClientTarget, patched, 'utf8');
          console.log('[patch] CSRF root patch v2 applied — token fetched from service root.');
        }
      }
    }
  }
}

// ── Patch 2: OData V4 error message parsing in odata-error.js ────────────────
// The proxy was written for OData V2 errors: { error: { message: { value: "..." } } }
// SAP S/4HANA OData V4 returns:            { error: { message: "plain string" } }
// This patch fixes parseODataError to also read the V4 plain-string format.

const errorTarget = path.join(
  __dirname,
  'node_modules/odata-mcp-proxy/dist/client/odata-error.js'
);

if (!fs.existsSync(errorTarget)) {
  console.log('[patch] odata-error.js not found — skipping error-parser patch.');
} else {
  const errOriginal = fs.readFileSync(errorTarget, 'utf8');
  const ERROR_MARKER = '// [ODATAV4-ERROR-PATCH]';

  if (errOriginal.includes(ERROR_MARKER)) {
    console.log('[patch] OData V4 error parser already patched — skipping.');
  } else {
    // Replace the V2-only message extraction with V2+V4 combined
    const V2_ONLY   = 'const message = parsed.error?.message?.value;';
    const V4_AWARE  = `${ERROR_MARKER}
    const _rawMsg = parsed.error?.message;
    const message = (typeof _rawMsg === 'object' ? _rawMsg?.value : _rawMsg) ?? undefined;`;

    if (!errOriginal.includes(V2_ONLY)) {
      console.warn('[patch] WARNING: Could not find OData V2 message extraction — error-parser patch skipped.');
    } else {
      // Apply to both occurrences (the function has two branches: object + string)
      const patched = errOriginal.replaceAll(V2_ONLY, V4_AWARE);
      fs.writeFileSync(errorTarget, patched, 'utf8');
      console.log('[patch] OData V4 error parser patch applied — SAP V4 error messages now visible.');
    }
  }
}
