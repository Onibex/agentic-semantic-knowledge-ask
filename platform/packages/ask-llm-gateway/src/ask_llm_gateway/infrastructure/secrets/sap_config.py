# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Read the SAP S/4HANA connection out of the encrypted store.

Twin of :mod:`db_config`, and deliberately the same shape: go through
:class:`SecretsProvider` so Fernet decryption happens once per TTL rather than
per call, and coerce the string-stored ``port`` back to an int so callers see a
native type.

**What this section is, in plain terms.** The connection to the customer's SAP
system: where it lives (``host`` plus the OData service path), who logs in
(``username`` / ``password``), and the MCP server that talks to it (``mcp_url``
and ``port``). ``password`` is the only sensitive field, and it is the reason
this moved: it used to sit in CLEARTEXT in ``config/settings.json``, a file
three services mounted from a shared writable volume.

Two consumers, and they fail differently, which is worth knowing when something
breaks:

  * ``routers/sap_connection`` and ``routers/mcp`` in the admin API. A failure
    here is visible: the Setup screen says so.
  * ``ask_action_execution.application.factory``, which builds the MCP adapter
    only when ``mcp_url`` is set. A failure here is NOT visible on any screen:
    action execution from chat silently loses its adapter.

Everything is empty when nothing is configured; guard with
:func:`is_sap_configured` rather than checking individual keys.
"""

from __future__ import annotations

import logging
from typing import Any

from .provider import SecretsProvider, get_secrets_provider
from .registry import sap_fields
from .repository import SAP_TARGET

logger = logging.getLogger(__name__)


def _coerce(fields: dict[str, Any]) -> dict[str, Any]:
    """Cast each field back to the ``kind`` the registry declares.

    The store keeps everything as strings, because Fernet operates on strings
    and plain values are stringified on write. ``port`` is the only non-string
    today; a bad value is dropped rather than raised, since a malformed port
    should not take down a connection whose host is fine.
    """
    kinds = {name: kind for name, _sensitive, kind in sap_fields()}
    out: dict[str, Any] = {}
    for name, value in fields.items():
        kind = kinds.get(name, "str")
        if kind == "int":
            try:
                out[name] = int(str(value).strip())
            except (TypeError, ValueError):
                logger.warning("sap_s4hana.%s is not an integer (%r); dropping it", name, value)
            continue
        out[name] = value
    return out


def resolve_sap_config(*, provider: SecretsProvider | None = None) -> dict[str, Any]:
    """The decrypted ``sap_s4hana`` section, or ``{}`` when unconfigured.

    ``provider`` is injectable for tests; it defaults to the process-wide
    singleton so the Fernet round-trip is cached.
    """
    sp = provider or get_secrets_provider()
    try:
        resolved = sp.get(SAP_TARGET)
    except PermissionError:
        # A stored cipher does not match the current master key. Surfacing this
        # as "unconfigured" would be a lie that sends the reader looking at the
        # Setup screen instead of at ONIBEX_ENCRYPTION_KEY.
        logger.error("ENCRYPTION_KEY_MISMATCH while resolving the SAP connection")
        raise
    if not resolved:
        return {}
    return _coerce(dict(resolved.get("fields") or {}))


def is_sap_configured(*, provider: SecretsProvider | None = None) -> bool:
    """True when a host is stored, which is the minimum to attempt anything."""
    try:
        return bool(resolve_sap_config(provider=provider).get("host"))
    except PermissionError:
        return False
