"""
OpenAPI generation for the public /external sub-app.

FastAPI natively emits OpenAPI **3.1.0**, but B2B importers — WatsonX
Orchestrate in particular — only reliably ingest **3.0.x**. Three concrete
gotchas make a raw 3.1 dump unusable for those importers:

1. ``openapi: 3.1.0``           → they reject / mis-parse it. Must be 3.0.x.
2. relative ``servers: /external`` → they build request URLs that 404. Must be
   an ABSOLUTE, externally-reachable base URL.
3. no ``securitySchemes``        → no "Connection" step (OAuth2) is offered on
   import. Must declare the ``clientCredentials`` flow.

This module owns the single source of truth for that transform. It takes the
live FastAPI-generated spec (so it never drifts from the actual routes/models)
and:

* down-converts 3.1 → 3.0.3 (nullable ``anyOf`` collapse, ``examples[]`` →
  ``example``, union ``type`` arrays, ``const`` → ``enum``);
* rewrites ``servers`` to the absolute external base URL (from ``Settings``);
* injects the ``oauth2`` clientCredentials security scheme + a global
  ``security`` requirement (token URL from ``Settings``);
* strips the manual ``authorization`` header parameter (auth is now expressed
  via the security scheme; the header param is redundant noise for importers).

The result is what ``GET /external/openapi.json`` serves — ready to import into
WatsonX Orchestrate without any hand-editing.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from ..config import Settings

# Security scheme name kept as ``oauth2`` to match the contract that imported
# successfully into WatsonX Orchestrate.
_SECURITY_SCHEME_NAME = "oauth2"


def _downconvert_31_to_30(node: Any) -> Any:
    """Recursively convert an OpenAPI 3.1 fragment to its 3.0.3 equivalent.

    Children are converted first, then the current node, so parent-level
    rewrites see already-normalised children. Every rewrite is guarded by the
    shape it targets, so walking non-schema parts of the document (``info``,
    ``paths`` keys, …) is a harmless no-op.
    """
    if isinstance(node, list):
        return [_downconvert_31_to_30(item) for item in node]
    if not isinstance(node, dict):
        return node

    node = {key: _downconvert_31_to_30(value) for key, value in node.items()}

    # 1) Nullable union: ``anyOf: [S, {"type": "null"}]`` → S + ``nullable: true``.
    any_of = node.get("anyOf")
    if isinstance(any_of, list):
        has_null = any(isinstance(v, dict) and v.get("type") == "null" for v in any_of)
        non_null = [v for v in any_of if not (isinstance(v, dict) and v.get("type") == "null")]
        if has_null:
            node.pop("anyOf")
            node["nullable"] = True
            if len(non_null) == 1:
                # Fold the sole real variant up into this node; keep sibling
                # keys (title/description/default) already present here.
                for key, value in non_null[0].items():
                    node.setdefault(key, value)
            elif non_null:
                node["anyOf"] = non_null

    # 2) Union type array: ``type: ["string", "null"]`` → ``type: "string"`` (+ nullable).
    node_type = node.get("type")
    if isinstance(node_type, list):
        if "null" in node_type:
            node["nullable"] = True
        real_types = [t for t in node_type if t != "null"]
        node["type"] = real_types[0] if len(real_types) == 1 else real_types

    # 3) ``examples: [x]`` (3.1 schema array) → ``example: x`` (3.0 singular).
    #    Media Type / Parameter ``examples`` are MAPS (dict), not lists — the
    #    isinstance(list) guard leaves those untouched.
    examples = node.get("examples")
    if isinstance(examples, list):
        node.pop("examples")
        if examples:
            node["example"] = examples[0]

    # 4) ``const: X`` (3.1) → ``enum: [X]`` (3.0).
    if "const" in node:
        node["enum"] = [node.pop("const")]

    return node


def _strip_authorization_param(spec: dict[str, Any]) -> None:
    """Remove the manual ``authorization`` header parameter from every op.

    ``validate_token`` declares it via ``Header(...)``, so FastAPI documents it
    as a request parameter. Once auth is expressed through the OAuth2 security
    scheme, that parameter is redundant — and importers would otherwise render
    it as a free-text field the integrator must fill by hand.
    """
    for methods in spec.get("paths", {}).values():
        for operation in methods.values():
            if not isinstance(operation, dict):
                continue
            params = operation.get("parameters")
            if not isinstance(params, list):
                continue
            kept = [
                p
                for p in params
                if not (p.get("name") == "authorization" and p.get("in") == "header")
            ]
            if kept:
                operation["parameters"] = kept
            else:
                operation.pop("parameters", None)


def build_external_openapi(app: FastAPI, settings: Settings) -> dict[str, Any]:
    """Build the WatsonX-ready 3.0.3 OpenAPI document for the /external sub-app.

    Caches the result on ``app.openapi_schema`` (FastAPI's own cache slot) so
    repeat requests don't rebuild it.
    """
    if app.openapi_schema:
        return app.openapi_schema

    spec = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    spec = _downconvert_31_to_30(spec)
    _strip_authorization_param(spec)

    # 1) Force 3.0.3 (importers reject 3.1).
    spec["openapi"] = "3.0.3"

    # 2) Absolute, externally-reachable server base (includes /external mount).
    spec["servers"] = [
        {
            "url": settings.external_server_url,
            "description": "ASK orchestrator external API base URL",
        }
    ]

    # 3) OAuth2 clientCredentials security scheme + global requirement.
    components = spec.setdefault("components", {})
    components.setdefault("securitySchemes", {})[_SECURITY_SCHEME_NAME] = {
        "type": "oauth2",
        "flows": {
            "clientCredentials": {
                "tokenUrl": settings.oauth_token_url,
                "scopes": {},
            }
        },
    }
    spec["security"] = [{_SECURITY_SCHEME_NAME: []}]

    app.openapi_schema = spec
    return spec
