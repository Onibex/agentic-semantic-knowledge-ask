# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""What an XSUAA token has to look like for ASK to read any role out of it.

The failure these pin is invisible from the outside. XSUAA issues a perfectly
valid, correctly signed token whatever the descriptor says, so a mismatch
between `platform/deploy/kyma/xs-security.json` and the validator shows up only
as a working sign-in followed by 403 on every request.

Every shape used below was MEASURED against a real XSUAA instance on
2026-09-23, not taken from documentation. That is the point of this file: the
first version was written from documentation and was wrong twice over.

  * XSUAA rejects a dot in an xsappname, so the validator's old literal prefix
    `ask.` could never match any legal configuration.
  * `scope` arrives as a JSON ARRAY, and the old code called `.split()` on it.

The binding for application `ask-platform` reported
`xsappname = ask-platform!t20611`, so that is the prefix used here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ask_admin_api.auth.validator import _extract_roles_xsuaa

# platform/packages/ask-admin-api/tests/unit/ -> platform/
_PLATFORM = Path(__file__).resolve().parents[4]
_DESCRIPTOR = _PLATFORM / "deploy" / "kyma" / "xs-security.json"

# The tenant suffix XSUAA appended on the real subaccount. Any value would do
# for the logic; this one is kept because it is the one that was observed.
_TENANT_SUFFIX = "!t20611"

# The two roles the platform checks. ask-admin guards every ASK Studio route
# and the admin API; ask-user is the default that reaches ASK Chat.
_ROLES = ("ask-admin", "ask-user")

# XSUAA's own characters for an xsappname, from the error it returns when one
# is outside them. A dot is not among them.
_XSAPPNAME_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-/")


def _descriptor() -> dict:
    return json.loads(_DESCRIPTOR.read_text(encoding="utf-8"))


def _xsappname_in_token() -> str:
    """The prefix XSUAA really uses: the descriptor's name plus the tenant."""
    return _descriptor()["xsappname"] + _TENANT_SUFFIX


def _scope(role: str, xsappname: str | None = None) -> str:
    return f"{xsappname or _xsappname_in_token()}.{role}"


@pytest.fixture
def bound(monkeypatch: pytest.MonkeyPatch) -> str:
    """The environment a pod gets from the service binding."""
    xsappname = _xsappname_in_token()
    monkeypatch.setenv("XSUAA_XSAPPNAME", xsappname)
    return xsappname


# ── The descriptor ───────────────────────────────────────────────────────────


def test_descriptor_declares_exactly_the_two_roles_the_code_checks() -> None:
    declared = {s["name"].removeprefix("$XSAPPNAME.") for s in _descriptor()["scopes"]}
    assert declared == set(_ROLES), (
        f"xs-security.json declares {sorted(declared)}. The platform checks "
        f"{sorted(_ROLES)} and nothing else; a scope by any other name is a "
        "role nobody can be granted."
    )


def test_xsappname_uses_only_characters_xsuaa_accepts() -> None:
    """XSUAA refused `ask.platform` five minutes into provisioning. Fail here instead."""
    xsappname = _descriptor()["xsappname"]
    illegal = set(xsappname) - _XSAPPNAME_ALLOWED
    assert not illegal, (
        f"xsappname {xsappname!r} contains {sorted(illegal)}, which XSUAA rejects: "
        "it allows only a-z, A-Z, 0-9, '_', '-' and '/'."
    )


# ── Reading roles out of a real-shaped token ─────────────────────────────────


@pytest.mark.parametrize("role", _ROLES)
def test_a_real_token_scope_resolves_to_the_role_the_code_checks(bound: str, role: str) -> None:
    """Descriptor -> XSUAA token -> role string, with `scope` as the array it really is."""
    assert _extract_roles_xsuaa({"scope": [_scope(role)]}) == [role]


def test_an_administrator_gets_both_roles(bound: str) -> None:
    """The ASKAdministrator template grants both scopes, so both must come back."""
    payload = {"scope": [_scope(r) for r in _ROLES]}

    assert sorted(_extract_roles_xsuaa(payload)) == sorted(_ROLES)


def test_scope_as_an_array_does_not_raise(bound: str) -> None:
    """The regression: the old code called `.split()` on a list and raised."""
    payload = {"scope": ["uaa.resource", "openid", _scope("ask-user")]}

    assert _extract_roles_xsuaa(payload) == ["ask-user"]


def test_scope_as_a_space_separated_string_still_works(bound: str) -> None:
    """Other OIDC providers do send a string, so both shapes are accepted."""
    payload = {"scope": f"openid {_scope('ask-admin')}"}

    assert _extract_roles_xsuaa(payload) == ["ask-admin"]


def test_the_measured_client_credentials_token_grants_nothing(bound: str) -> None:
    """What the binding's own client really received: `uaa.resource` and no app scope."""
    assert _extract_roles_xsuaa({"scope": ["uaa.resource"]}) == []


# ── What must NOT be read as an ASK role ─────────────────────────────────────


def test_the_same_scope_name_from_another_application_is_ignored(bound: str) -> None:
    """A subaccount holds other applications, and scope names are not unique across them.

    This is the property the old prefix never had: it looked at the part after
    the last dot, so `some-other-app!t9.ask-admin` would have been read as ours.
    """
    payload = {"scope": [_scope("ask-admin", xsappname="some-other-app!t9"), _scope("ask-user")]}

    assert _extract_roles_xsuaa(payload) == ["ask-user"]


def test_the_archived_cloud_foundry_descriptor_would_have_granted_nothing(bound: str) -> None:
    """`oneconnect-agenticai` with a scope named `admin`, kept executable."""
    payload = {"scope": [_scope("admin", xsappname="oneconnect-agenticai!t847")]}

    assert _extract_roles_xsuaa(payload) == []


def test_the_old_literal_prefix_is_not_a_back_door(bound: str) -> None:
    """A scope shaped for the old `ask.` rule must not grant anything any more."""
    payload = {"scope": ["ask.anything!t1.ask-admin"]}

    assert _extract_roles_xsuaa(payload) == []


# ── Without the binding ──────────────────────────────────────────────────────


def test_no_xsappname_means_no_roles_rather_than_a_guess(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the binding's name there is no safe way to tell ASK's scopes apart.

    Guessing would reintroduce exactly the cross-application leak above, so it
    grants nothing and says why in the log.
    """
    monkeypatch.delenv("XSUAA_XSAPPNAME", raising=False)

    assert _extract_roles_xsuaa({"scope": [_scope("ask-admin")]}) == []
