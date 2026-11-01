"""#3790 model preview and dynamic Claw B14 model choices.

The historical four-Google read-only preview remains a partial source inventory.
Claw's actual chooser follows the same B14 owner-allowed/ready list as B66,
without requiring another product-specific model/provider live evaluation.
"""
from __future__ import annotations

import asyncio
import os
import re
import time

from starlette.requests import Request
from starlette.responses import JSONResponse

from padiem_control_plane.owner_model_name_parts import google_owner_name_parts
from .member_grade_access import selected_grade_denial, selected_admin_denial
from .model_policy import ADMIN_B14_MODEL_ID


#: The B14 roster is read-only catalog data. One Claw screen load asked for
#: it repeatedly and every request paid a fresh upstream read (#6460 4-1,
#: second round). The window is deliberately short and switchable: an
#: administrator change becomes visible within it, and nothing user-specific
#: is stored -- the per-tier filtering below still runs on every request.
ROSTER_CACHE_TTL_ENV = "PADIEM_CHAT_MODEL_ROSTER_CACHE_SECONDS"
_ROSTER_CACHE_TTL_DEFAULT = 30.0
_ROSTER_CACHE_TTL_MAX = 300.0
#: Entries hold the resolver itself, so a recycled ``id`` can never hand one
#: request (or one test) another resolver's rows.
_ROSTER_CACHE: dict[int, tuple[float, tuple[tuple[str, str], ...], object]] = {}
_ROSTER_LOCKS: dict[int, tuple[object, asyncio.Lock]] = {}


def roster_cache_ttl() -> float:
    raw = os.getenv(ROSTER_CACHE_TTL_ENV)
    if raw is None or not raw.strip():
        return _ROSTER_CACHE_TTL_DEFAULT
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _ROSTER_CACHE_TTL_DEFAULT
    if value != value or value < 0 or value > _ROSTER_CACHE_TTL_MAX:
        return _ROSTER_CACHE_TTL_DEFAULT
    return value


def clear_roster_cache() -> None:
    _ROSTER_CACHE.clear()


def _roster_owner(list_fn) -> object:
    # Bound methods are compared by the resolver they belong to, so a test or a
    # redeployed client never reads another instance's rows.
    return getattr(list_fn, "__self__", list_fn)


def _validated_models(models: object) -> tuple[tuple[str, str], ...]:
    """B14 model rows, validated once; raises ``ValueError`` on any bad row."""
    if not isinstance(models, list) or len(models) > 256:
        raise ValueError("invalid B14 model roster")
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
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
        rows.append((model_id, name))
    return tuple(rows)


async def _model_roster(list_fn) -> tuple[tuple[str, str], ...]:
    """The B14 roster inside the short shared window, single-flight per resolver."""
    owner = _roster_owner(list_fn)
    key = id(owner)
    ttl = roster_cache_ttl()
    now = time.monotonic()
    if ttl > 0:
        cached = _ROSTER_CACHE.get(key)
        if cached is not None and cached[0] > now and cached[2] is owner:
            return cached[1]
    entry = _ROSTER_LOCKS.get(key)
    if entry is None or entry[0] is not owner:
        entry = (owner, asyncio.Lock())
        _ROSTER_LOCKS[key] = entry
    async with entry[1]:
        now = time.monotonic()
        if ttl > 0:
            cached = _ROSTER_CACHE.get(key)
            if cached is not None and cached[0] > now and cached[2] is owner:
                return cached[1]
        rows = _validated_models(await list_fn())
        if ttl > 0:
            _ROSTER_CACHE[key] = (now + ttl, rows, owner)
        return rows


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
    """Read live-ready exact model IDs for the server-approved Claw grade.

    Registration and optional model quality/E2E assessments are separate.
    B54/P01/B14 still enforce final per-request execution authorization.

    The offered set follows the server-approved route for the requested grade:
    a centrally stored per-product/per-grade row is the administrator's exact
    selection, and the shared static product contract is used only while no
    such row exists. A disabled central row fails closed instead of silently
    widening back to the previous static lane, and no model name is hardcoded
    here, so renaming a model in the administrator console needs no code edit.
    """
    from .auth_routes import auth_ready, current_user_id
    from .central_model_route_runtime import resolve_claw_tier_model_view

    headers = {"Cache-Control": "no-store"}
    if not auth_ready(request) or current_user_id(request) is None:
        return JSONResponse(
            {"ok": False, "error": {"code": "authentication_required"}},
            status_code=401, headers=headers,
        )
    # Query-string tier is a request, not authority: member grade is re-read
    # from the signed owner account and checked before listing any model.
    requested_tier = request.query_params.get("tier", "free").strip().lower()
    admin_lane = requested_tier == "admin"
    denial = (await selected_admin_denial(request, current_user_id(request))
              if admin_lane else await selected_grade_denial(request, current_user_id(request), requested_tier))
    if denial is not None:
        return denial
    authority = getattr(request.app.state, "b14_model_choice_resolver", None)
    list_fn = getattr(authority, "list_selectable_models", None)
    if not callable(list_fn):
        return JSONResponse(
            {"ok": False, "error": {"code": "model_catalog_unavailable"}},
            status_code=503, headers=headers,
        )
    if admin_lane:
        from types import SimpleNamespace
        route, route_revision = SimpleNamespace(
            ok=True, model_id=ADMIN_B14_MODEL_ID, fallback_model_id=None, source="admin"
        ), 0
    else:
        try:
            route, route_revision = await resolve_claw_tier_model_view(request, requested_tier)
        except Exception:
            route, route_revision = None, 0
    if route is None or not route.ok or not isinstance(route.model_id, str) or not route.model_id:
        # A disabled or unresolvable central grade never falls back to a wider
        # model set; the customer sees the grade as unavailable instead.
        return JSONResponse(
            {"ok": False, "error": {"code": "tier_unavailable"}},
            status_code=503, headers=headers,
        )
    route_ids = {
        model_id for model_id in (route.model_id, route.fallback_model_id)
        if isinstance(model_id, str) and model_id
    }
    # A stored central row is the administrator's exact selection for this
    # product/grade. Without a row the shared static contract decides: the free
    # lane is the contract's own free route, and a paid grade keeps the
    # owner-allowed catalog ceiling.
    if admin_lane or route.source == "central" or requested_tier == "free":
        allowed_ids: frozenset[str] | None = frozenset(route_ids)
    else:
        allowed_ids = None
    try:
        roster = await _model_roster(list_fn)
        rows = []
        for model_id, name in roster:
            if allowed_ids is not None and model_id not in allowed_ids:
                continue
            rows.append({
                "model_id": model_id,
                "individual_model_name": name,
                "product_name_prefix": "파디엠프리" if requested_tier == "free" else "파디엠플러스",
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
        "route_source": route.source,
        # The ledger revision that governs this grade. 0 means no stored row
        # governs it, so an operator never reads an unrelated revision as an
        # applied decision.
        "route_revision": route_revision,
        "model_choices": rows,
    }, headers=headers)
