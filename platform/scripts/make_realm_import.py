#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Build a deployable Keycloak realm from the local-demo one in this repository.

    python scripts/make_realm_import.py --password 'Chosen.Initial.Password' \
        --host studio=https://studio.example.com \
        --host chat=https://chat.example.com \
        --host setup=https://setup.example.com \
        --out /tmp/realm.json

Two things stand between the realm committed here and one that can face a
network, and both fail in ways that point somewhere else:

**The passwords.** `keycloak-realm-config.json` is a local demo and its users
carry a password that is published on GitHub. Deploying it unchanged puts that
password on whatever address the platform ends up answering.

**The redirect URIs.** They list `localhost` ports, which is right for a port
forward and wrong for anything else. A missing one does not degrade the login,
it stops it with `Invalid parameter: redirect_uri` after the user has already
typed their password.

Every password written here is marked temporary, so Keycloak requires a change
at first sign-in and the shared initial value stops working the moment each
person has used it once.

The output carries credentials. Send it to a Secret, never to a ConfigMap and
never to the repository:

    kubectl -n <ns> create secret generic ask-realm \
      --from-file=ask-platform-realm.json=/tmp/realm.json
    rm /tmp/realm.json

A realm is imported ONLY on a first boot. Against a Keycloak that already has
its state on a volume, this file is ignored and the change belongs in the admin
console instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "packages" / "ask-admin-api" / "keycloak-realm-config.json"

# The app name used on the command line, and the client id it configures.
CLIENTS = {"studio": "ask-studio", "chat": "ask-chat", "setup": "ask-setup"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--password",
        required=True,
        help="Initial password for every user, and temporary: each one must change it at first sign-in.",
    )
    parser.add_argument(
        "--host",
        action="append",
        default=[],
        metavar="APP=ORIGIN",
        help="Public origin of an app, scheme included and no trailing slash. Repeatable. "
        f"APP is one of: {', '.join(CLIENTS)}.",
    )
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if len(args.password) < 12:
        print("The initial password is shared until each user changes it, so keep it long.")
        return 1

    origins: dict[str, str] = {}
    for entry in args.host:
        app, _, origin = entry.partition("=")
        if app not in CLIENTS or not origin:
            print(f"--host wants APP=ORIGIN with APP one of {', '.join(CLIENTS)}, got {entry!r}")
            return 1
        origins[CLIENTS[app]] = origin.rstrip("/")

    realm = json.loads(args.source.read_text(encoding="utf-8"))

    for client in realm.get("clients", []):
        origin = origins.get(client.get("clientId"))
        if not origin:
            continue
        # Keep what was there. The localhost entries stay useful for a port
        # forward, and removing the Kyma wildcard would break that target later.
        client["redirectUris"] = sorted(set(client.get("redirectUris", [])) | {f"{origin}/*"})
        client["webOrigins"] = sorted(set(client.get("webOrigins", [])) | {origin})

    changed = []
    for user in realm.get("users", []):
        credentials = user.get("credentials") or []
        if not credentials:
            # A service account has no password to set.
            continue
        for credential in credentials:
            if credential.get("type") == "password":
                credential["value"] = args.password
                credential["temporary"] = True
        actions = set(user.get("requiredActions") or [])
        actions.add("UPDATE_PASSWORD")
        user["requiredActions"] = sorted(actions)
        changed.append(user.get("username"))

    args.out.write_text(json.dumps(realm, indent=2), encoding="utf-8")

    print(f"wrote {args.out}")
    print(f"  users that must change their password at first sign-in: {', '.join(changed)}")
    for client in realm.get("clients", []):
        if client.get("clientId") in origins.values() or client.get("clientId") in CLIENTS.values():
            print(f"  {client['clientId']}: {', '.join(client.get('redirectUris', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
