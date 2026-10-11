"""Read-only #3790 owner model NAME preview; no product/model runtime grant.

Four Google owner-verified source decisions are a partial catalogue.
This GET never connects to B14/Google, does not read a secret, and does not
accept a model selection or mutate state. Existing B62/Claw dispatch remains
under the separate product HOLD/entitlement contract.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from padiem_control_plane.owner_model_name_parts import google_owner_name_parts


async def owner_model_name_preview(request: Request) -> JSONResponse:
    names = google_owner_name_parts()
    return JSONResponse(
        {
            "scope": "owner_confirmed_google_subset",
            "complete_inventory": False,
            "execution_enabled": False,
            "model_names": [
                {
                    "model_id": row.model_id,
                    "product_name_prefix": row.product_name_prefix,
                    "individual_model_name": row.individual_model_name,
                    "owner_selected": row.owner_selected,
                    "customer_selectable": False,
                }
                for row in names
            ],
        },
        headers={"Cache-Control": "no-store"},
    )


# Owner-confirmed exact Google name and independently verified Claw product E2E.
# Single synthetic success is not an availability SLA or universal entitlement.
_CLAW_PRODUCT_PROVEN_IDS = frozenset({"google/gemini-3.5-flash-lite"})


async def claw_verified_model_choices(request: Request) -> JSONResponse:
    """Signed-in, read-only list. Actual model use is gated by B54/P01/B14."""
    from .auth_routes import auth_ready, current_user_id
    headers = {"Cache-Control": "no-store"}
    if not auth_ready(request) or current_user_id(request) is None:
        return JSONResponse({"ok": False, "error": {"code": "authentication_required"}},
                            status_code=401, headers=headers)
    return JSONResponse({
        "ok": True, "scope": "owner_confirmed_google_subset",
        "complete_inventory": False, "automatic_default": False,
        "model_choices": [{
            "model_id": row.model_id,
            "product_name_prefix": row.product_name_prefix,
            "individual_model_name": row.individual_model_name,
            "owner_selected": row.owner_selected,
            "product_e2e_verified": row.model_id in _CLAW_PRODUCT_PROVEN_IDS,
            "customer_selectable": row.model_id in _CLAW_PRODUCT_PROVEN_IDS,
        } for row in google_owner_name_parts()],
    }, headers=headers)
