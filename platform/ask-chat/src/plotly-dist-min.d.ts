/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

// `plotly.js-dist-min` ships no type declarations and `@types/plotly.js`
// only declares the `plotly.js` specifier, so importing the dist-min bundle
// trips TS7016 (implicit any) under `noImplicitAny`. Declare the module so the
// build type-checks; the import stays effectively `any` (same as before).
declare module 'plotly.js-dist-min';
