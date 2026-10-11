"""#3790 model preview and dynamic Claw B14 model choices.

The historical four-Google read-only preview remains a partial source inventory.
Claw's actual chooser follows the same B14 owner-allowed/ready list as B66,
without requiring another product-specific model/provider live evaluation.
"""
from __future__ import annotations

import re

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


async def claw_verified_model_choices(request: Request) -> JSONResponse:
    """Read live-ready exact model IDs from B14's trusted read-only resolver.

    Registration and optional model quality/E2E assessments are separate.
    B54/P01/B14 still enforce final per-request execution authorization.
    """
    from .auth_routes import auth_ready, current_user_id

    headers = {"Cache-Control": "no-store"}
    if not auth_ready(request) or current_user_id(request) is None:
        return JSONResponse(
            {"ok": False, "error": {"code": "authentication_required"}},
            status_code=401, headers=headers,
        )
    authority = getattr(request.app.state, "b14_model_choice_resolver", None)
    list_fn = getattr(authority, "list_selectable_models", None)
    if not callable(list_fn):
        return JSONResponse(
            {"ok": False, "error": {"code": "model_catalog_unavailable"}},
            status_code=503, headers=headers,
        )
    try:
        models = await list_fn()
        if not isinstance(models, list) or len(models) > 256:
            raise ValueError("invalid B14 model roster")
        rows = []
        seen = set()
        for model in models:
            if not isinstance(model, dict):
                raise ValueError("invalid B14 model row")
            model_id, name = model.get("model_id"), model.get("name")
            if (not isinstance(model_id, str)
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}", model_id) is None
                    or model_id in seen
                    or not isinstance(name, str) or not (0 < len(name) <= 100)):
                raise ValueError("invalid B14 model identity")
            seen.add(model_id)
            rows.append({
                "model_id": model_id,
                "individual_model_name": name,
                "product_name_prefix": "파디엠플러스",
                "customer_selectable": True,
            })
    except Exception:
        return JSONResponse(
            {"ok": False, "error": {"code": "model_catalog_unavailable"}},
            status_code=503, headers=headers,
        )

    return JSONResponse({
        "ok": True,
        "scope": "b14_owner_allowed_live_ready",
        "complete_inventory": True,
        "automatic_default": False,
        "model_choices": rows,
    }, headers=headers)
