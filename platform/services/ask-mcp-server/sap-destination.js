/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * sap-destination.js — keeps SAP_S4_SALESORDER_* in step with the store.
 *
 * WHAT THIS REPLACES
 *
 * The SAP host, user and password used to be four environment variables in
 * every .env and every deployment file, while ASK Setup wrote the same
 * connection to the encrypted store in OpenSearch. Two sources of truth that
 * never spoke: saving the connection in the UI did not make a tool call work,
 * and the failure said the variable was not set while the screen showed the
 * connection as configured.
 *
 * Now the store is the only source and the variables are derived from it.
 *
 * WHY A PRELOADED MODULE RATHER THAN A FETCH-THEN-EXEC SCRIPT
 *
 * `patch.js` reads process.env at the moment it resolves a destination, which
 * is per request rather than at import. So updating process.env inside the
 * running server is enough for the next call to use the new value, and that is
 * what makes a refresh possible without a restart.
 *
 * It matters more than it sounds. Restarting the MCP after a change is what
 * the Restart MCP button in ASK Setup was for, and that button cannot work on
 * Kubernetes: it drives a container runtime socket, and a pod has none. A
 * process that notices on its own removes the need for the button rather than
 * papering over it.
 *
 * FAILURE IS QUIET ON PURPOSE, ONCE
 *
 * A server whose SAP connection is not configured yet must still start: its
 * other tools work, and the existing error message when a SAP tool is called
 * already names exactly what is missing. So a 404 logs once and the refresh
 * keeps going. What is NOT quiet is a rejected API key, because that is a
 * deployment mistake rather than a pending setup step.
 */

const REFRESH_MS = Number(process.env.SAP_DESTINATION_REFRESH_MS || 60000);
const REQUEST_TIMEOUT_MS = 10000;

// The four names are the response body's own keys, so the admin API decides
// the mapping and this file does not restate it.
let lastSignature = null;
let warnedNotConfigured = false;

function baseUrl() {
  return (process.env.ASK_ADMIN_API_URL || '').trim().replace(/\/+$/, '');
}

async function fetchDestination() {
  const url = `${baseUrl()}/v1/internal/sap-destination`;
  const response = await fetch(url, {
    headers: { 'X-API-Key': process.env.ASK_INGEST_API_KEY || '', Accept: 'application/json' },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });

  if (response.status === 404) return null;
  if (response.status === 401 || response.status === 403) {
    throw new Error(
      `authentication rejected (HTTP ${response.status}); check that ` +
        'ASK_INGEST_API_KEY matches the admin API'
    );
  }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);

  const body = await response.json();
  const env = body && body.env;
  if (!env || typeof env !== 'object') {
    throw new Error('response had no usable `env` object');
  }
  return env;
}

function apply(env) {
  // Signed by content so an unchanged connection does not log every minute.
  const signature = JSON.stringify(Object.keys(env).sort().map((k) => [k, env[k]]));
  const changed = signature !== lastSignature;
  for (const [name, value] of Object.entries(env)) {
    process.env[name] = value;
  }
  lastSignature = signature;
  if (changed) {
    console.log(
      `[sap-destination] applied ${Object.keys(env).length} variable(s) from the ` +
        `encrypted store; base url ${env.SAP_S4_SALESORDER_BASE_URL || '(none)'}`
    );
  }
  warnedNotConfigured = false;
}

async function refresh() {
  if (!baseUrl() || !process.env.ASK_INGEST_API_KEY) {
    // Nothing to talk to. The pre-existing behaviour applies: whatever is in
    // the environment stands, which is how a standalone run still works.
    return;
  }
  try {
    const env = await fetchDestination();
    if (env) {
      apply(env);
    } else if (!warnedNotConfigured) {
      warnedNotConfigured = true;
      console.log(
        '[sap-destination] no SAP connection stored yet. Save it on the ASK ' +
          'Setup SAP page; this server will pick it up within ' +
          `${Math.round(REFRESH_MS / 1000)}s without a restart.`
      );
    }
  } catch (err) {
    console.error(`[sap-destination] refresh failed: ${err.message}`);
  }
}

// Once now, so the first tool call after boot already has it, and then on a
// timer. unref() so this never holds the process open by itself.
refresh();
setInterval(refresh, REFRESH_MS).unref();

module.exports = { refresh };
