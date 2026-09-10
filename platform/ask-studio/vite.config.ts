/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

/**
 * Serves /config.js in `npm run dev`, the same file the container entrypoint
 * renders in production.
 *
 * The point is one mechanism, not two. The app reads `window.__ENV__` and
 * nothing else, everywhere, so a developer cannot be running a code path that
 * production does not have. The values come from the same ASK_* variables, out
 * of the process environment or a .env file.
 */
function runtimeConfigPlugin(env: Record<string, string>): Plugin {
  const value = (name: string) => env[name] ?? process.env[name] ?? ''

  return {
    name: 'ask-runtime-config',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.split('?')[0] !== '/config.js') return next()

        const mode = value('ASK_AUTH_MODE')
        if (!mode) {
          // Fail the same way the container does, for the same reason: an
          // empty auth mode used to mean "no login", silently.
          res.statusCode = 500
          res.setHeader('Content-Type', 'application/javascript')
          res.end(
            'throw new Error("ASK_AUTH_MODE is not set. Set it (and the ' +
              'Keycloak or XSUAA variables that go with it) in your ' +
              'environment or .env.local before running the dev server.")',
          )
          return
        }

        res.setHeader('Content-Type', 'application/javascript')
        res.setHeader('Cache-Control', 'no-store')
        res.end(
          `window.__ENV__ = ${JSON.stringify(
            {
              AUTH_MODE: mode,
              KEYCLOAK_URL: value('ASK_KEYCLOAK_URL'),
              KEYCLOAK_REALM: value('ASK_KEYCLOAK_REALM'),
              KEYCLOAK_CLIENT_ID: value('ASK_KEYCLOAK_CLIENT_ID'),
              XSUAA_URL: value('ASK_XSUAA_URL'),
              XSUAA_CLIENT_ID: value('ASK_XSUAA_CLIENT_ID'),
              SETUP_SPA_URL: value('ASK_SETUP_SPA_URL'),
              CHAT_URL: value('ASK_CHAT_URL'),
            },
            null,
            2,
          )}\n`,
        )
      })
    },
  }
}

export default defineConfig(({ mode }) => {
  // Prefix '' so the ASK_* names are read as-is. They are NOT exposed to the
  // bundle: this config file runs in Node, and the values reach the browser
  // only through /config.js above.
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [react(), runtimeConfigPlugin(env)],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 5173,
      proxy: {
        // Admin CRUD routes: /api/admin/* → /v1/admin/* (must be listed before catch-all)
        '/api/admin': {
          target: 'http://localhost:8081',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/admin/, '/v1/admin'),
        },
        // Viz routes: /api/* → /v1/viz/*
        '/api': {
          target: 'http://localhost:8081',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, '/v1/viz'),
        },
      },
    },
  }
})
