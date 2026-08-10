"""``GET /v1/admin/me`` — return the authenticated caller's token claims.

Useful for the admin SPA to display the current user's identity and roles
without a separate user-info call to the IdP.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.validator import TokenClaims, validate_token

router = APIRouter(prefix="/v1/admin", tags=["admin/me"])


@router.get(
    "/me",
    response_model=TokenClaims,
    summary="Current token claims",
    description=(
        "Returns the sub, email, roles and issuer extracted from the bearer "
        "token used for this request. No database calls are made — the "
        "information is derived entirely from the JWT payload."
    ),
)
async def get_me(
    claims: TokenClaims = Depends(validate_token),
) -> TokenClaims:
    """Return the claims of the currently authenticated token."""
    return claims
