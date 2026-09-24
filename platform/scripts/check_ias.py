#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Check an SAP Cloud Identity Services application from outside, before anyone signs in.

The IAS application that ASK signs in against is configured by hand in the
tenant's administration console, and most of its settings fail without saying
so: the password gets typed and then the sign-in stops, or it completes and the
user can do nothing. This checks, from outside and without any credential, the
settings that CAN be checked that way, and says plainly which ones cannot.

Every check here was chosen because it DISCRIMINATES, which was measured
against a real tenant on 2026-09-23 rather than assumed. A check that returns
the same answer for a right and a wrong configuration proves nothing, and two
obvious candidates turned out to be exactly that:

  * The logout address. IAS answers a logout for a registered address and for
    an invented one identically, 200 with no redirect, so it is not checked.
  * XSUAA's authorize endpoint, for the record, defers the redirect check until
    after the password, so the same probe there accepted a fake address. IAS
    checks it up front, which is why the redirect check below means something.

What it checks:

  1. The tenant answers, and speaks the OIDC shape the apps are built for.
  2. The three sign-in addresses are accepted, AND an invented one is refused.
     The refusal is the control: without it an "accepted" proves nothing.
  3. The application is a public client. A token exchange with no secret and a
     fake code is refused for the CODE (invalid_grant) when public client flows
     are on, and for the CLIENT (invalid_client) when they are off. That second
     answer is exactly how XSUAA fails, and it is the one setting without which
     no sign-in can ever complete.

Nothing here needs a library outside the standard one, nor any secret.

    python scripts/check_ias.py \\
      --tenant https://<tenant>.accounts.ondemand.com \\
      --client-id <the application's client id> \\
      --domain <cluster domain>

Exit status is 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import urllib.parse

APPS = ("ask-studio", "ask-chat", "ask-setup")

# The PKCE pair from RFC 7636's own example. Any valid pair would do: the code
# sent with it is fake, so nothing is ever issued.
_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"

_failures = 0


def _report(ok: bool, what: str, fix: str = "") -> None:
    global _failures
    print(("PASS  " if ok else "FAIL  ") + what)
    if not ok:
        _failures += 1
        if fix:
            for line in fix.splitlines():
                print("      " + line)


def _request(host: str, method: str, path: str, body: str | None = None) -> tuple[int, str]:
    conn = http.client.HTTPSConnection(host, timeout=30)
    headers = {"Content-Type": "application/x-www-form-urlencoded"} if body is not None else {}
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    return resp.status, resp.read().decode("utf-8", "replace")


def check_discovery(host: str, tenant: str) -> bool:
    try:
        status, text = _request(host, "GET", "/.well-known/openid-configuration")
    except OSError as exc:
        _report(False, f"the tenant answers at {tenant}", f"It did not: {exc}.\nCheck the address, and that this machine can reach it.")
        return False
    if status != 200:
        _report(False, f"the tenant answers at {tenant}", f"It returned HTTP {status}. Is this an IAS tenant origin, with no path?")
        return False
    doc = json.loads(text)
    _report(doc.get("issuer") == tenant, f"the issuer is exactly {tenant}",
            f"The tenant calls itself {doc.get('issuer')!r}. Use that value, scheme included and no trailing slash.")
    endpoints_ok = all(doc.get(k, "").startswith(tenant + "/oauth2/")
                       for k in ("authorization_endpoint", "token_endpoint", "jwks_uri"))
    _report(endpoints_ok, "its endpoints are the /oauth2/ ones the apps call",
            "The apps build IAS's /oauth2/authorize, /oauth2/token and /oauth2/certs paths.\n"
            "This tenant advertises something else, so it is probably not IAS.")
    _report("S256" in doc.get("code_challenge_methods_supported", []), "it supports PKCE with S256",
            "The apps always send an S256 challenge and cannot sign in without it.")
    _report("groups" in doc.get("scopes_supported", []), "it offers the groups scope",
            "The apps request `groups`, which is where ASK's roles come from.")
    return True


def _authorize(host: str, client_id: str, redirect: str) -> int:
    query = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect,
        "scope": "openid groups", "state": "check_ias",
        "code_challenge": _CHALLENGE, "code_challenge_method": "S256",
    })
    status, _ = _request(host, "GET", "/oauth2/authorize?" + query)
    return status


def check_redirects(host: str, client_id: str, domain: str) -> int:
    """Returns how many of the three sign-in addresses were accepted.

    That count also says whether the client id is real: IAS only accepts an
    address for a client it knows, so one acceptance proves the id exists.
    Nothing else can: IAS returns the same error page, word for word, for an
    unknown client and for a known client with an unregistered address.
    """
    # The control first. If an invented address is accepted, an "accepted" for
    # the real ones proves nothing, so they are not reported as passing.
    fake = "https://check-ias-invented-address.invalid/login/callback"
    fake_status = _authorize(host, client_id, fake)
    if fake_status == 200:
        _report(False, "an invented sign-in address is refused",
                "It was accepted, so the application lists a wildcard that matches anything.\n"
                "Nothing below about addresses can be trusted until this passes.")
        return 0
    _report(True, f"an invented sign-in address is refused (HTTP {fake_status}), so the next checks mean something")
    accepted = 0
    for app in APPS:
        address = f"https://{app}.{domain}/login/callback"
        status = _authorize(host, client_id, address)
        accepted += status == 200
        _report(status == 200, f"{address} is accepted",
                f"HTTP {status}. Add it under the application's OpenID Connect Configuration, Redirect URIs.\n"
                "Without it IAS shows its error page the moment the app sends someone to sign in.")
    return accepted


def check_public_client(host: str, client_id: str, domain: str) -> str:
    """Returns the OAuth error the tenant answered with."""
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code", "client_id": client_id,
        "code": "check-ias-fake-code", "code_verifier": _VERIFIER,
        "redirect_uri": f"https://{APPS[0]}.{domain}/login/callback",
    })
    status, text = _request(host, "POST", "/oauth2/token", body)
    try:
        error = json.loads(text).get("error", "")
    except ValueError:
        error = ""
    if error == "invalid_grant":
        _report(True, "the application is a public client: a secretless exchange is refused for the code, not the client")
    elif error == "invalid_client":
        _report(False, "the application is a public client",
                "It is not: a secretless exchange was refused for the CLIENT (invalid_client).\n"
                "Turn on Client Authentication > Enable Public Client Flows. Until then no sign-in can complete.\n"
                "Each run of this check while it is off may count as a failed client logon, and the\n"
                "application locks after five if Client ID Lock is on, so do not loop it.")
    else:
        _report(False, "the application is a public client",
                f"Unexpected answer, HTTP {status}: {text[:200]!r}. Check the client id.")
    return error


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant", required=True, help="The IAS tenant origin, e.g. https://<tenant>.accounts.ondemand.com")
    ap.add_argument("--client-id", required=True, help="The IAS application's client id, from Client Authentication")
    ap.add_argument("--domain", required=True, help="The cluster domain the apps are published under, no leading dot")
    args = ap.parse_args()

    tenant = args.tenant.rstrip("/")
    host = urllib.parse.urlparse(tenant).netloc
    if not host or not tenant.startswith("https://"):
        print(f"--tenant must be an https origin, got {args.tenant!r}", file=sys.stderr)
        return 2

    if check_discovery(host, tenant):
        accepted = check_redirects(host, args.client_id, args.domain.lstrip("."))
        error = check_public_client(host, args.client_id, args.domain.lstrip("."))
        if accepted == 0 and error == "invalid_client":
            # Every per-check hint above assumes the client id is right. When
            # nothing about the client worked, that assumption is the likely
            # fault, and following those hints would send someone to a console
            # where everything is already configured.
            print()
            print("READ THIS FIRST: nothing about this client worked, and that usually means the client id")
            print("itself is wrong, not each setting above. Copy it again from the application's")
            print("Client Authentication page; it is not the Application ID shown at the top of the")
            print("application, which looks similar. Only once it is right do the hints above apply.")

    print()
    print("Not checkable from outside, and each needs a look in the IAS console or a real sign-in:")
    print("  - the application emits the `groups` and `email` attributes")
    print("  - the groups ask-admin and ask-user exist, and hold the right people")
    print("  - the three /login addresses, used when signing out (IAS answers the same for any address)")
    print("  - the grant types, and Maximum Sessions per User")
    print("The page 'Sign in with SAP Cloud Identity Services' says where to look for each.")

    print()
    print("All checks passed." if _failures == 0 else f"{_failures} check(s) failed.")
    return 0 if _failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
