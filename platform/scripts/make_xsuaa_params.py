#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Turn the committed XSUAA descriptor into something SAP BTP will accept.

`deploy/kyma/xs-security.json` is the source of truth for the application name,
the scopes and the role collections, and it is written to be READ: JSON has no
comments, so the reasoning lives in `_comment_*` keys. Two things therefore have
to happen before BTP sees it, and doing them by hand is how they get forgotten:

  * the `_comment_*` keys come out, because they are ours and not XSUAA's;
  * `<CLUSTER_DOMAIN>` is replaced in the redirect URIs, which differ per
    cluster and are the difference between a sign-in that completes and one
    that stops with `redirect_uri` rejected after the password was typed.

The output is the `spec.parameters` of a `ServiceInstance`, or the whole
manifest with --manifest. Nothing here is a secret: the descriptor declares
which roles exist, not who holds them.

    python scripts/make_xsuaa_params.py --domain ff90b8d.kyma.ondemand.com \
      --manifest --namespace onibex-ask
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_DEFAULT_DESCRIPTOR = Path(__file__).resolve().parent.parent / "deploy" / "kyma" / "xs-security.json"
_PLACEHOLDER = "<CLUSTER_DOMAIN>"


def strip_comments(node: object) -> object:
    """Drop every `_comment_*` key, at any depth."""
    if isinstance(node, dict):
        return {k: strip_comments(v) for k, v in node.items() if not k.startswith("_comment")}
    if isinstance(node, list):
        return [strip_comments(v) for v in node]
    return node


def substitute_domain(node: object, domain: str) -> object:
    if isinstance(node, dict):
        return {k: substitute_domain(v, domain) for k, v in node.items()}
    if isinstance(node, list):
        return [substitute_domain(v, domain) for v in node]
    if isinstance(node, str):
        return node.replace(_PLACEHOLDER, domain)
    return node


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--domain",
        required=True,
        help="The cluster's wildcard domain, with no leading dot, e.g. ff90b8d.kyma.ondemand.com. "
        "Read it with: kubectl get gateway -n kyma-system kyma-gateway "
        "-o jsonpath='{.spec.servers[*].hosts}'",
    )
    ap.add_argument("--descriptor", type=Path, default=_DEFAULT_DESCRIPTOR)
    ap.add_argument("--manifest", action="store_true", help="Emit the whole ServiceInstance, not just the parameters")
    ap.add_argument("--namespace", default="onibex-ask")
    ap.add_argument("--name", default="ask-xsuaa", help="Name of the ServiceInstance object")
    args = ap.parse_args()

    if args.domain.startswith("."):
        print(f"--domain is {args.domain!r}: drop the leading dot.", file=sys.stderr)
        return 2
    if args.domain.startswith("*"):
        print(
            f"--domain is {args.domain!r}. Pass the domain itself, not the wildcard: "
            "the redirect URIs name one host each.",
            file=sys.stderr,
        )
        return 2

    descriptor = json.loads(args.descriptor.read_text(encoding="utf-8"))
    params = substitute_domain(strip_comments(descriptor), args.domain)

    remaining = [u for u in params["oauth2-configuration"]["redirect-uris"] if _PLACEHOLDER in u]
    if remaining:
        print(f"{_PLACEHOLDER} still present in: {remaining}", file=sys.stderr)
        return 1

    # XSUAA rejects the whole instance over this one, five minutes into a
    # provisioning that reports "being created" the entire time. Catching it
    # here turns that into an immediate, readable failure.
    xsappname = params["xsappname"]
    illegal = {c for c in xsappname if not (c.isascii() and (c.isalnum() or c in "_-/"))}
    if illegal:
        print(
            f"xsappname is {xsappname!r}, which XSUAA will refuse over {sorted(illegal)}. "
            "It allows only a-z, A-Z, 0-9, '_', '-' and '/'. A dot in particular is not "
            "allowed, whatever an older descriptor may suggest.",
            file=sys.stderr,
        )
        return 1

    if not args.manifest:
        print(json.dumps(params, indent=2))
        return 0

    indented = "\n".join("    " + line for line in json.dumps(params, indent=2).splitlines())
    print(
        f"""apiVersion: services.cloud.sap.com/v1
kind: ServiceInstance
metadata:
  name: {args.name}
  namespace: {args.namespace}
spec:
  serviceOfferingName: xsuaa
  servicePlanName: application
  externalName: {args.name}-{args.namespace}
  parameters:
{indented}
"""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
