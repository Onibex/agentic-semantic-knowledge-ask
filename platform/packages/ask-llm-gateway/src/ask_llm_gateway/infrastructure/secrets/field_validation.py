# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Shape checks for provider fields, run before they are stored.

A credential that cannot work, saved in ASK Setup, otherwise surfaces much
later as a failed question in chat, far from where it was typed. Only fields
with a shape worth checking are listed here; every other field passes through.

Messages name what is wrong and never echo the value: these fields are secrets.
"""

from __future__ import annotations

import json
from collections.abc import Mapping


def validate_provider_fields(provider: str, fields: Mapping[str, str]) -> None:
    """Raise ``ValueError`` when a field cannot work for ``provider``.

    Blank values are not checked. On an update, a blank sensitive field keeps
    the stored value, and a missing credential is already reported by the
    connection's ``configured`` flag.
    """
    if provider == "sap":
        _check_sap_service_key(fields.get("AICORE_SERVICE_KEY") or "")


def _check_sap_service_key(raw: str) -> None:
    if not raw.strip():
        return
    try:
        key = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"The SAP AI Core service key is not valid JSON ({exc.msg}, line {exc.lineno} "
            f"column {exc.colno}). Paste the whole key as SAP BTP shows it."
        ) from None
    if not isinstance(key, dict):
        raise ValueError(
            "The SAP AI Core service key must be a JSON object. Paste the whole key "
            "as SAP BTP shows it."
        )

    missing: list[str] = []
    if not key.get("clientid"):
        missing.append("clientid")
    # A key is issued either with a client secret or, on request, with an x509
    # certificate; LiteLLM accepts both.
    if not key.get("clientsecret") and not (key.get("certificate") and key.get("key")):
        missing.append("clientsecret (or certificate and key)")
    if not key.get("url") and not key.get("certurl"):
        missing.append("url")
    service_urls = key.get("serviceurls")
    if not isinstance(service_urls, dict) or not service_urls.get("AI_API_URL"):
        missing.append("serviceurls.AI_API_URL")
    if missing:
        raise ValueError(
            "The SAP AI Core service key is missing "
            + ", ".join(missing)
            + ". Paste the whole key as SAP BTP shows it, not part of it."
        )
