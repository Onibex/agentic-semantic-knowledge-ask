# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""What an XSUAA token has to look like for ASK to read any role out of it.

These tests exist because the failure they pin is invisible from the outside.
The scope names are decided in `platform/deploy/kyma/xs-security.json`, which is
handed to SAP BTP when the service instance is created, and nothing checks the
two against each other: get them wrong and XSUAA still issues a perfectly valid,
correctly signed token. The user signs in, every redirect works, and then every
request is refused with 403 because the validator extracted zero roles.

That is not hypothetical. The descriptor archived from the Cloud Foundry era
declares `oneconnect-agenticai` with a scope named `admin`, which produces
exactly that. Reusing it would have cost a debugging session pointed at the
identity provider, which is the one place where nothing is wrong.

The tests read the committed descriptor rather than restating its values, so a
rename there fails here instead of on a cluster.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ask_admin_api.auth.validator import _extract_roles_xsuaa

# platform/packages/ask-admin-api/tests/unit/ -> platform/
_PLATFORM = Path(__file__).resolve().parents[4]
_DESCRIPTOR = _PLATFORM / "deploy" / "kyma" / "xs-security.json"

# The two roles the platform actually checks. ask-admin guards every ASK Studio
# route and the admin API; ask-user is the default that reaches ASK Chat.
_ROLES = ("ask-admin", "ask-user")


def _descriptor() -> dict:
    return json.loads(_DESCRIPTOR.read_text(encoding="utf-8"))


def _token_scope(xsappname: str, scope_name: str, tenant: str = "t847") -> str:
    """Render one scope the way XSUAA puts it in a token.

    `$XSAPPNAME` is not substituted literally: on a dedicated tenant XSUAA
    appends `!t<id>` to the application name, so the descriptor's
    `$XSAPPNAME.ask-admin` arrives as `ask.platform!t847.ask-admin`. Getting
    this shape wrong is what makes a naive reading of the descriptor look fine.
    """
    return f"{xsappname}!{tenant}.{scope_name}"


def test_descriptor_is_valid_json_and_declares_both_roles() -> None:
    d = _descriptor()
    declared = {s["name"].removeprefix("$XSAPPNAME.") for s in d["scopes"]}
    assert declared == set(_ROLES), (
        f"xs-security.json declares {sorted(declared)}. The platform checks "
        f"{sorted(_ROLES)} and nothing else; a scope by any other name is a "
        "role nobody can be granted."
    )


def test_application_name_survives_the_prefix_filter() -> None:
    """The validator keeps only scopes starting with `ask.`, so the app name must."""
    xsappname = _descriptor()["xsappname"]
    assert xsappname.startswith("ask."), (
        f"xsappname is {xsappname!r}. The validator drops every scope that does "
        "not start with 'ask.', so this name makes ASK read zero roles from a "
        "valid token: sign-in succeeds and every request 403s."
    )


@pytest.mark.parametrize("role", _ROLES)
def test_a_real_token_scope_resolves_to_the_role_the_code_checks(role: str) -> None:
    """End to end over the naming: descriptor -> XSUAA token -> role string."""
    xsappname = _descriptor()["xsappname"]
    scope = _token_scope(xsappname, role)

    assert _extract_roles_xsuaa({"scope": scope}) == [role]


def test_both_roles_arrive_together_for_an_administrator() -> None:
    """The ASKAdministrator template grants both scopes, so both must come back."""
    xsappname = _descriptor()["xsappname"]
    payload = {"scope": " ".join(_token_scope(xsappname, r) for r in _ROLES)}

    assert sorted(_extract_roles_xsuaa(payload)) == sorted(_ROLES)


def test_the_archived_cloud_foundry_descriptor_would_have_granted_nothing() -> None:
    """The regression this file exists for, kept executable rather than retold.

    `oneconnect-agenticai` with a scope named `admin`: a valid, signed token
    carrying real authorization, out of which ASK reads no roles at all.
    """
    payload = {"scope": _token_scope("oneconnect-agenticai", "admin")}

    assert _extract_roles_xsuaa(payload) == []


def test_a_scope_from_some_other_btp_application_is_ignored() -> None:
    """Tokens carry scopes from other subscriptions; none of them is an ASK role."""
    payload = {
        "scope": " ".join(
            [
                "openid",
                "uaa.resource",
                _token_scope("some.other.app", "ask-admin"),
                _token_scope(_descriptor()["xsappname"], "ask-user"),
            ]
        )
    }

    assert _extract_roles_xsuaa(payload) == ["ask-user"]
