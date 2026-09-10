/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * fetch-contracts.js
 *
 * Fetches this server's API contracts from the admin API at boot and writes
 * them to /app/api-config.json, which is what the proxy reads.
 *
 * It replaces two copies of the same file: one baked into this image and one
 * mounted from ./config, where the mounted one silently shadowed the baked one
 * at runtime. A file that the platform writes is what forced a ReadWriteOnce
 * volume in Kubernetes, and that volume is what forced the pod affinity that
 * kept two backends from scheduling at all.
 *
 * THE FAILURE MODE IS THE POINT. If the admin API cannot be reached, or has no
 * contracts stored for this environment, this script keeps retrying and never
 * exits successfully, so `npm start` never runs, nothing listens on the health
 * port, and the container stays unready. It must never fall back to an empty
 * contract set: that would expose zero tools while reporting healthy, which is
 * the exact defect class this move exists to remove.
 */

const fs = require('fs');

const TARGET = process.env.MCP_CONFIG_PATH || '/app/api-config.json';

// Backoff: 2s, 4s, 8s, 16s, then every 30s. Capped so a long outage does not
// turn into an hours-long wait, and slow enough not to hammer a booting API.
const BACKOFF_MS = [2000, 4000, 8000, 16000];
const MAX_BACKOFF_MS = 30000;
const REQUEST_TIMEOUT_MS = 10000;

function required(name) {
  const value = (process.env[name] || '').trim();
  if (!value) {
    console.error(
      `[contracts] FATAL: ${name} is not set. This server reads its API ` +
        'contracts from the admin API and has no file to fall back to. ' +
        'Set it and restart.'
    );
    process.exit(1);
  }
  return value;
}

function delayFor(attempt) {
  return attempt < BACKOFF_MS.length ? BACKOFF_MS[attempt] : MAX_BACKOFF_MS;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function attemptFetch(url, apiKey) {
  const response = await fetch(url, {
    headers: { 'X-API-Key': apiKey, Accept: 'application/json' },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });

  if (response.status === 404) {
    throw new Error(
      'no contracts stored for this environment yet; save them on the ' +
        'Setup Contracts page'
    );
  }
  if (response.status === 401 || response.status === 403) {
    throw new Error(
      `authentication rejected (HTTP ${response.status}); check that ` +
        'ASK_INGEST_API_KEY matches the admin API'
    );
  }
  if (response.status === 503) {
    throw new Error(
      'admin API reports its ingest API key is not configured (HTTP 503)'
    );
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  const body = await response.json();
  const config = body && body.config;
  if (!config || typeof config !== 'object') {
    throw new Error('response had no usable `config` object');
  }
  return config;
}

async function main() {
  const baseUrl = required('ASK_ADMIN_API_URL').replace(/\/+$/, '');
  const apiKey = required('ASK_INGEST_API_KEY');
  const env = (process.env.ASK_ENV || 'dev').trim();
  const url = `${baseUrl}/v1/internal/api-contracts?env=${encodeURIComponent(env)}`;

  for (let attempt = 0; ; attempt += 1) {
    try {
      const config = await attemptFetch(url, apiKey);
      fs.writeFileSync(TARGET, JSON.stringify(config, null, 2), 'utf8');
      const apiCount = Array.isArray(config.apis) ? config.apis.length : 0;
      console.log(
        `[contracts] loaded ${apiCount} api(s) for env=${env} from ${url} ` +
          `-> ${TARGET}`
      );
      return;
    } catch (err) {
      const wait = delayFor(attempt);
      // The URL is named on every retry on purpose: the usual cause is a wrong
      // host or a service that is not up yet, and a message without the URL
      // sends the reader looking in the wrong place.
      console.error(
        `[contracts] attempt ${attempt + 1} failed for ${url}: ` +
          `${err && err.message ? err.message : err}. ` +
          `Retrying in ${wait / 1000}s. The server stays unready until this succeeds.`
      );
      await sleep(wait);
    }
  }
}

main();
