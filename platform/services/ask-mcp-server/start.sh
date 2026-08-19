#!/bin/sh
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

# Startup script: use api-config.json from PVC if available, else seed default.
CONFIG_DIR=/app/config
DEFAULT_CONFIG=/app/api-config.json
ACTIVE_CONFIG=$CONFIG_DIR/api-config.json

if [ -f "$ACTIVE_CONFIG" ]; then
  echo "[startup] api-config.json found in config volume — using it."
  cp "$ACTIVE_CONFIG" "$DEFAULT_CONFIG"
else
  echo "[startup] No api-config.json in config volume — seeding default."
  mkdir -p "$CONFIG_DIR"
  cp "$DEFAULT_CONFIG" "$ACTIVE_CONFIG"
fi

# Read SAP credentials from settings.json (Docker Compose / local env).
# Env vars set explicitly always take precedence; this only fills the gaps.
SETTINGS=$CONFIG_DIR/settings.json
if [ -f "$SETTINGS" ]; then
  _host=$(node -e "try{const s=require('$SETTINGS');process.stdout.write(s.sap_s4hana&&s.sap_s4hana.host||'')}catch(e){}" 2>/dev/null)
  _user=$(node -e "try{const s=require('$SETTINGS');process.stdout.write(s.sap_s4hana&&s.sap_s4hana.username||'')}catch(e){}" 2>/dev/null)
  _pass=$(node -e "try{const s=require('$SETTINGS');process.stdout.write(s.sap_s4hana&&s.sap_s4hana.password||'')}catch(e){}" 2>/dev/null)
  if [ -n "$_host" ]; then
    export SAP_S4_SALESORDER_BASE_URL="$_host"
    export SAP_S4_SALESORDER_URL="$_host"
    echo "[startup] SAP host loaded from settings.json: $_host"
  fi
  if [ -n "$_user" ]; then
    export SAP_S4_SALESORDER_USERNAME="$_user"
    echo "[startup] SAP username loaded from settings.json."
  fi
  if [ -n "$_pass" ]; then
    export SAP_S4_SALESORDER_PASSWORD="$_pass"
    echo "[startup] SAP password loaded from settings.json."
  fi
fi

exec npm start
