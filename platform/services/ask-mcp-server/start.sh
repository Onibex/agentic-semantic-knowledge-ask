#!/bin/sh
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

# The API contracts come from the admin API, fetched once at boot, and there is
# no file to fall back to. fetch-contracts.js retries with backoff and only
# returns once it has written /app/api-config.json, so an unreachable admin API
# or an environment with no contracts saved keeps this container unready rather
# than starting it with zero tools.
#
# What used to be here: a copy of api-config.json out of a mounted config
# volume, and a read of sap_s4hana credentials out of config/settings.json.
# Both are gone.
#
# The SAP credentials are not read here either. sap-destination.js is preloaded
# into the server process by `npm start` and keeps SAP_S4_SALESORDER_* in step
# with the encrypted store, refreshing on a timer. That is why a connection
# saved in ASK Setup now takes effect without restarting this container, which
# matters because the Restart MCP button cannot work on Kubernetes.

node /app/fetch-contracts.js || exit 1

exec npm start
