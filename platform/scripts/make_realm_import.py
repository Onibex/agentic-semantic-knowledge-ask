#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Build a deployable Keycloak realm from the local-demo one in this repository.

    python scripts/make_realm_import.py --password 'Chosen.Initial.Password1' \
        --host studio=https://studio.example.com \
        --host chat=https://chat.example.com \
        --host setup=https://setup.example.com \
        --out /tmp/realm.json

Three things stand between the realm committed here and one that can face a
network, and each fails in a way that points somewhere else:

**The passwords.** `keycloak-realm-config.json` is a local demo and its users
carry a password that is published on GitHub. Deploying it unchanged puts that
password on whatever address the platform ends up answering.

**The client secrets, which are the ones people miss.** Three clients are
confidential and carry their secret in cleartext in that same committed file.
`kafka-ingest` is the one that matters: it has `serviceAccountsEnabled`, and its
service account holds the `ask-admin` realm role. Nothing distinguishes a
service-account token from a person's, so that secret plus a reachable Keycloak
is the whole administrative API, with no user and no password in between.
Rotating the user passwords and leaving these alone closes the door people walk
through and leaves the one machines walk through wide open.

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
import re
import secrets
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "packages" / "ask-admin-api" / "keycloak-realm-config.json"

# The app name used on the command line, and the client id it configures.
CLIENTS = {"studio": "ask-studio", "chat": "ask-chat", "setup": "ask-setup"}

# Keycloak policy name -> (what it counts, how to say it). Read from the realm
# rather than restated here, so changing the policy in the realm changes what
# this checks and there is no second copy to drift.
_POLICY_RULES = {
    "length": (lambda p: len(p), "characters"),
    "digits": (lambda p: sum(c.isdigit() for c in p), "digits"),
    "upperCase": (lambda p: sum(c.isupper() for c in p), "upper-case letters"),
    "lowerCase": (lambda p: sum(c.islower() for c in p), "lower-case letters"),
    "specialChars": (lambda p: sum(not c.isalnum() for c in p), "special characters"),
}


def check_password_policy(password: str, policy: str) -> list[str]:
    """Return one line per rule the password fails, empty if it satisfies them all.

    Keycloak applies the realm's own ``passwordPolicy`` to the passwords inside
    an import file, and it applies it at IMPORT time. A password that violates
    it does not produce a user who must pick a better one: it aborts the import
    and the server crash-loops, which is a long way from the argument that
    caused it. Rules this does not understand are ignored rather than guessed
    at, because a false rejection here is worse than the check being partial.
    """
    violations: list[str] = []
    for rule in re.finditer(r"(\w+)\((\d+)\)", policy or ""):
        name, wanted = rule.group(1), int(rule.group(2))
        known = _POLICY_RULES.get(name)
        if known is None:
            continue
        count, noun = known[0](password), known[1]
        if count < wanted:
            violations.append(f"{name}({wanted}): needs {wanted} {noun}, has {count}")
    return violations


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

    realm = json.loads(args.source.read_text(encoding="utf-8"))

    violations = check_password_policy(args.password, realm.get("passwordPolicy") or "")
    if violations:
        print("The initial password does not satisfy the realm's own password policy:")
        for violation in violations:
            print(f"  {violation}")
        print(f"\nThe policy is: {realm.get('passwordPolicy')}")
        print(
            "\nKeycloak enforces this while IMPORTING the realm, not at first sign-in, so it\n"
            "would abort the import and crash-loop with invalidPasswordMinDigitsMessage or a\n"
            "sibling of it, twenty lines into a Quarkus startup log."
        )
        return 1

    origins: dict[str, str] = {}
    for entry in args.host:
        app, _, origin = entry.partition("=")
        if app not in CLIENTS or not origin:
            print(f"--host wants APP=ORIGIN with APP one of {', '.join(CLIENTS)}, got {entry!r}")
            return 1
        origins[CLIENTS[app]] = origin.rstrip("/")

    for client in realm.get("clients", []):
        origin = origins.get(client.get("clientId"))
        if not origin:
            continue
        # Keep what was there. The localhost entries stay useful for a port
        # forward, and removing the Kyma wildcard would break that target later.
        client["redirectUris"] = sorted(set(client.get("redirectUris", [])) | {f"{origin}/*"})
        client["webOrigins"] = sorted(set(client.get("webOrigins", [])) | {origin})

    # Confidential clients. The committed secret is a demo value, so every one
    # of them is replaced whether or not this deployment uses that client: an
    # unused client with a published secret is still a way in.
    rotated: dict[str, str] = {}
    for client in realm.get("clients", []):
        if not client.get("secret"):
            continue
        client["secret"] = secrets.token_urlsafe(32)
        rotated[client["clientId"]] = client["secret"]

    changed = []
    for user in realm.get("users", []):
        credentials = user.get("credentials") or []
        if not credentials:
            # A service account has no password. It has a client secret, which
            # is rotated above; this branch is not the place to look for it.
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

    if rotated:
        print("\nNew client secrets. This is the only time they are shown, and they are")
        print("not recoverable from the realm file once you delete it. Anything that")
        print("authenticates as one of these clients needs the new value:")
        for client_id, value in rotated.items():
            print(f"  {client_id}: {value}")
        print("\n  kafka-ingest is the Kafka Connect HTTP Sink connector's oauth2.client.secret.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
