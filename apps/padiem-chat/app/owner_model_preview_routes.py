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
