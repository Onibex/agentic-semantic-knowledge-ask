# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""SAP Cloud Identity Services (IAS) tokens: what ASK accepts, and what it must not.

The orchestrator carries its own copy of the validator, duplicated from the
admin API's on purpose (see the module docstring there). This file is the
matching copy of ask-admin-api/tests/unit/test_ias_validation.py: testing only
one of the two would let the other drift, and the orchestrator is the one that
answers chat.

The property that matters most here is the AUDIENCE, and it is tested with real
RSA-signed tokens going through the real verification path, not by inspecting
claims. An IAS tenant is the customer's whole corporate directory: every one of
their applications is registered in it and a user's groups are the same in all
of them. Checking only the signature would let a token minted for any other
application in the tenant into ASK, carrying `ask-admin` because the user is in
that group. The Keycloak path gets away with signature-only because the realm
belongs to this deployment alone; this one cannot.

Shapes used below were read off a real IAS tenant on 2026-09-23. In particular,
a token from an application that does not emit the groups attribute has NO
`groups` claim at all, not an empty list.

The signed-token tests import python-jose inside themselves, so the rest of the
file still runs where it is not installed; CI installs it as a declared runtime
dependency, and there they all run.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from ask_orchestrator.auth import validator
from ask_orchestrator.auth.validator import TokenClaims, _extract_roles_ias, _validate_ias

_TENANT = "https://cliente.accounts.ondemand.com"
_ASK_CLIENT = "ask-client-0001"
_KID = "test-key-1"


# ── Reading groups ───────────────────────────────────────────────────────────


def test_groups_become_roles() -> None:
    assert _extract_roles_ias({"groups": ["ask-admin", "ask-user"]}) == ["ask-admin", "ask-user"]


def test_a_single_group_sent_as_a_string_still_counts() -> None:
    """A single-valued attribute mapping can produce a string instead of a list."""
    assert _extract_roles_ias({"groups": "ask-admin"}) == ["ask-admin"]


def test_no_groups_claim_means_no_roles() -> None:
    """The measured shape: an application not configured to emit groups sends none.

    This is why a user who signs in and is then refused everywhere is almost
    always missing the groups ATTRIBUTE on the IAS application, not the group.
    """
    measured = {"aud": _ASK_CLIENT, "iss": _TENANT, "sub": "someone@example.com", "sap_id_type": "user"}
    assert _extract_roles_ias(measured) == []


def test_token_claims_accepts_ias_as_an_issuer() -> None:
    """The issuer Literal did not include "ias" when the mode was first added.

    Every IAS request would then have passed signature and audience and failed
    building this model: a pydantic ValidationError, a 500 on every call.
    """
    claims = TokenClaims(sub="u", email="u@example.com", roles=["ask-user"], issuer="ias")
    assert claims.issuer == "ias"


# ── Failing closed ───────────────────────────────────────────────────────────


def test_without_a_client_id_every_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """No client id means no audience to check, and accepting anyway is the hole."""
    monkeypatch.setenv("IAS_URL", _TENANT)
    monkeypatch.delenv("IAS_CLIENT_ID", raising=False)
    monkeypatch.delenv("IAS_JWKS_URL", raising=False)

    assert _validate_ias("any.token.at-all") is None


def test_without_a_tenant_every_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IAS_URL", raising=False)
    monkeypatch.delenv("IAS_JWKS_URL", raising=False)
    monkeypatch.setenv("IAS_CLIENT_ID", _ASK_CLIENT)

    assert _validate_ias("any.token.at-all") is None


# ── Real signed tokens through the real verification path ────────────────────


@pytest.fixture
def ias(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A signing key, its public half served as the tenant's JWKS, and a minter."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jose import jwk, jwt

    def keypair() -> tuple[bytes, dict[str, Any]]:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        public_pem = key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        public_jwk = jwk.construct(public_pem, "RS256").to_dict()
        public_jwk["kid"] = _KID
        return private_pem, public_jwk

    tenant_private, tenant_public = keypair()
    stranger_private, _ = keypair()

    monkeypatch.setenv("IAS_URL", _TENANT)
    monkeypatch.setenv("IAS_CLIENT_ID", _ASK_CLIENT)
    monkeypatch.delenv("IAS_JWKS_URL", raising=False)
    served: list[str] = []

    def fake_fetch(url: str) -> list[dict[str, Any]]:
        served.append(url)
        return [tenant_public]

    monkeypatch.setattr(validator, "_fetch_jwks", fake_fetch)

    class Minter:
        jwks_urls = served

        @staticmethod
        def token(*, signed_by: bytes | None = None, **overrides: Any) -> str:
            now = int(time.time())
            claims = {
                "iss": _TENANT,
                "aud": _ASK_CLIENT,
                "sub": "someone@example.com",
                "email": "someone@example.com",
                "groups": ["ask-admin"],
                "iat": now,
                "exp": now + 600,
            }
            claims.update(overrides)
            return jwt.encode(claims, signed_by or tenant_private, algorithm="RS256", headers={"kid": _KID})

        stranger = stranger_private

    return Minter


def test_a_token_issued_to_ask_is_accepted_with_its_groups(ias: Any) -> None:
    claims = _validate_ias(ias.token())

    assert claims is not None
    assert claims.roles == ["ask-admin"]
    assert claims.issuer == "ias"
    assert claims.email == "someone@example.com"


def test_the_keys_are_fetched_from_the_path_ias_really_serves(ias: Any) -> None:
    """`/oauth2/certs`, read off a real tenant's discovery document."""
    _validate_ias(ias.token())

    assert ias.jwks_urls == [f"{_TENANT}/oauth2/certs"]


def test_a_token_issued_to_another_application_in_the_tenant_is_rejected(ias: Any) -> None:
    """The point of the audience check.

    Same tenant, same key, same user, same `ask-admin` group: the only thing
    wrong is that it was issued to some other application. Signature-only
    validation would let this in with admin rights.
    """
    foreign = ias.token(aud="some-other-app-in-the-tenant")

    assert _validate_ias(foreign) is None


def test_aud_as_a_list_that_names_ask_is_accepted(ias: Any) -> None:
    """IAS may list several audiences; ASK only has to be one of them."""
    claims = _validate_ias(ias.token(aud=["some-other-app", _ASK_CLIENT]))

    assert claims is not None


def test_a_token_signed_by_a_key_the_tenant_does_not_publish_is_rejected(ias: Any) -> None:
    forged = ias.token(signed_by=ias.stranger)

    assert _validate_ias(forged) is None


def test_an_expired_token_is_rejected(ias: Any) -> None:
    now = int(time.time())
    expired = ias.token(iat=now - 7200, exp=now - 3600)

    assert _validate_ias(expired) is None


def test_email_falls_back_to_the_subject_when_ias_sends_none(ias: Any) -> None:
    """Measured: the tenant's token carried no `email` claim, only `sub`."""
    now = int(time.time())
    token = ias.token(email=None, sub="login-name@example.com", iat=now, exp=now + 600)
    claims = _validate_ias(token)

    assert claims is not None
    assert claims.email == "login-name@example.com"
