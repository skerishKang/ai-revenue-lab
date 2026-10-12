"""#4428 CENTRAL model management S0: truthful catalog and bounded policy preview.

Global admin authority must be injected by the trusted host. The B66 product
admin is NOT a central administrator. No write, key management, dispatch,
provider fallback, or durable policy changes are implemented in this slice.
"""
from __future__ import annotations

import inspect
import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body

_NO_STORE = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
PRODUCTS = ("central", "chat", "claw", "b66", "b14-router")
TIERS = ("FREE", "PLUS", "PRO", "MAX")
ACTIONS = ("allow", "block", "inherit")
MAX_MODELS = 256
MAX_PREVIEW_TARGETS = 20


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code}},
        status_code=status, headers=_NO_STORE,
    )


async def _central_admin(request: Request) -> JSONResponse | None:
    # Global admins are independently authorized. Never infer this role from
    # email text, a B66 membership/admin role, a browser flag or query params.
    owner = current_user_id(request) if auth_ready(request) else None
    if not owner:
        return _error(401, "authentication_required")
    authority = getattr(request.app.state, "central_model_admin_authorizer", None)
    verify = getattr(authority, "is_global_model_admin", None)
    if not callable(verify):
        return _error(503, "central_admin_not_configured")
    try:
        result = verify(user_id=owner)
        is_admin = await result if inspect.isawaitable(result) else result
    except Exception:
        return _error(503, "central_admin_authority_unavailable")
    if is_admin is not True:
        return _error(403, "global_model_admin_forbidden")
    return None


async def _catalog(request: Request) -> list[dict[str, str]] | None:
    resolver = getattr(request.app.state, "b14_model_choice_resolver", None)
    list_fn = getattr(resolver, "list_selectable_models", None)
    if not callable(list_fn):
        return None
    try:
        result = list_fn()
        rows = await result if inspect.isawaitable(result) else result
        if not isinstance(rows, list) or len(rows) > MAX_MODELS:
            return None
        found: set[str] = set()
        safe: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                return None
            model_id, name = row.get("model_id"), row.get("name")
            if (
                not isinstance(model_id, str) or _MODEL_ID.fullmatch(model_id) is None
                or model_id in found or not isinstance(name, str)
                or not (0 < len(name) <= 100)
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
            ):
                return None
            found.add(model_id)
            safe.append({"model_id": model_id, "name": name})
        return sorted(safe, key=lambda item: item["model_id"])
    except Exception:
        return None


async def central_model_admin_me(request: Request) -> JSONResponse:
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    return JSONResponse(
        {"ok": True, "admin": True, "write_enabled": False,
         "authority": "global_model_admin_only"},
        headers=_NO_STORE,
    )


async def central_model_admin_snapshot(request: Request) -> JSONResponse:
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    if request.query_params:
        return _error(400, "unexpected_query")
    models = await _catalog(request)
    if models is None:
        return _error(503, "b14_catalog_unavailable")

    # This is B14's owner-allowed/live-ready *selectable subset*, not the
    # complete B14 registration inventory. Report provenance honestly.
    products: dict[str, dict[str, Any]] = {
        "central": {"status": "not_wired", "source": "central_entitlements"},
        "chat": {"status": "not_wired", "source": "product_tier_routes"},
        "claw": {"status": "not_wired", "source": "b14_model_choice_resolver"},
        "b14-router": {"status": "not_wired", "source": "b14_external_router"},
        "b66": {"status": "unavailable", "source": "b66_membership_d1"},
    }
    store = getattr(request.app.state, "b66_member_admin_store", None)
    read_policy = getattr(store, "model_policy", None)
    if callable(read_policy):
        try:
            value = read_policy()
            raw = await value if inspect.isawaitable(value) else value
            if isinstance(raw, dict):
                revision = raw.get("revision")
                tiers = raw.get("tiers")
                disabled = raw.get("disabled_models")
                active = raw.get("active")
                # D1 is a trusted but independent product policy source.
                if (
                    type(revision) is int and revision >= 0
                    and type(active) is bool
                    and isinstance(tiers, dict) and set(tiers) == set(TIERS)
                    and all(isinstance(tiers[t], list) and
                            len(tiers[t]) <= MAX_MODELS and
                            all(isinstance(mid, str) and _MODEL_ID.fullmatch(mid)
                                for mid in tiers[t]) for t in TIERS)
                    and isinstance(disabled, list) and len(disabled) <= MAX_MODELS
                    and all(isinstance(mid, str) and _MODEL_ID.fullmatch(mid)
                            for mid in disabled)
                ):
                    products["b66"] = {
                        "status": "connected", "source": "b66_membership_d1",
                        "revision": revision, "active": active,
                        "tiers": {tier: sorted(set(tiers[tier])) for tier in TIERS},
                        "disabled_models": sorted(set(disabled)),
                    }
        except Exception:
            pass

    return JSONResponse({
        "ok": True, "mode": "read_only",
        "write_enabled": False, "policy_apply_enabled": False,
        "b14": {
            "scope": "owner_allowed_live_ready",
            "complete_registration_inventory": False,
            "registered_count_known": False,
            "models": models,
        },
        "products": products,
        "tiers": list(TIERS),
        "product_ids": list(PRODUCTS),
        "flow": ["central_control_plane", "product_policy", "b14_model_dispatch"],
    }, headers=_NO_STORE)


async def central_model_admin_preview(request: Request) -> JSONResponse:
    """Server-validated change plan. PREVIEW ONLY — deliberately zero writes."""
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "json_required")
    try:
        raw = await read_bounded_request_body(request, max_bytes=8192)
        data = json.loads(raw)
    except (RequestBodyTooLarge, UnicodeDecodeError, ValueError, TypeError):
        return _error(400, "invalid_preview_request")
    if not isinstance(data, dict) or set(data) != {"model_id", "targets"}:
        return _error(400, "invalid_preview_fields")
    model_id, targets = data["model_id"], data["targets"]
    if not isinstance(model_id, str) or _MODEL_ID.fullmatch(model_id) is None:
        return _error(400, "invalid_model_id")
    if not isinstance(targets, list) or not (1 <= len(targets) <= MAX_PREVIEW_TARGETS):
        return _error(400, "invalid_preview_targets")
    unique: set[tuple[str, str]] = set()
    for target in targets:
        if not isinstance(target, dict) or set(target) != {"product_id", "tier", "action"}:
            return _error(400, "invalid_preview_target")
        product, tier, action = target.values() if False else (
            target["product_id"], target["tier"], target["action"]
        )
        if (
            product not in PRODUCTS or tier not in TIERS or action not in ACTIONS
            or not all(isinstance(x, str) for x in (product, tier, action))
            or (product, tier) in unique
        ):
            return _error(400, "invalid_preview_target")
        unique.add((product, tier))
    models = await _catalog(request)
    if models is None:
        return _error(503, "b14_catalog_unavailable")
    if model_id not in {m["model_id"] for m in models}:
        return _error(422, "model_not_live_ready")
    return JSONResponse({
        "ok": True, "mode": "preview_only", "applied": False,
        "persisted": False, "dispatch_authorized": False,
        "model_id": model_id,
        "targets": targets,
        "limitations": [
            "central_global_rbac_write_not_composed",
            "product_policy_persistence_not_wired",
            "b14_registry_mutation_not_performed",
            "no_product_dispatch_changed",
        ],
    }, headers=_NO_STORE)
