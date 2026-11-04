"""#3790 dynamic Claw B14 model choices.

The public model-name preview was removed (#6828): users choose a PADIEM grade,
never a model identity. Claw's grade status endpoint follows the same B14
owner-allowed/ready readiness list as B66, without requiring another
product-specific live evaluation. It reports only whether the requested grade
has an executable server-side route; it never returns a model identity.
"""
from __future__ import annotations

import asyncio
import os
import re
import time

from starlette.requests import Request
from starlette.responses import JSONResponse

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
#: Stale-while-revalidate ceiling for an expired entry. The 261102 first-load
#: measurement: a blocking refresh cost 1.2~1.5 s (two serial B14 GETs, and
#: 1.2~1.5 s again whenever the 30 s window expired mid-load). Serving a roster
#: fetched within this ceiling costs the request path nothing and revalidates
#: in the background; past it a roster is no longer trusted as even nearly
#: current and the requester waits for a fresh read as before. 5 min is ten
#: times the #6460 admin-visibility delay, and the roster is read-only
#: catalog data whose per-request tier filtering still runs on every reply.
_ROSTER_MAX_STALE_SECONDS = 300.0
#: Entries hold the resolver itself, so a recycled ``id`` can never hand one
#: request (or one test) another resolver's rows. The fourth slot is when the
#: rows were fetched, the anchor for the stale-while-revalidate ceiling.
_ROSTER_CACHE: dict[int, tuple[float, tuple[tuple[str, str], ...], object, float]] = {}
_ROSTER_LOCKS: dict[int, tuple[object, asyncio.Lock]] = {}
_ROSTER_REFRESH: dict[int, tuple[object, "asyncio.Future[None]"]] = {}


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
    _ROSTER_REFRESH.clear()


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
    """The B14 roster inside the short shared window, single-flight per resolver.

    An expired entry whose fetch is still inside the stale ceiling is served
    as-is while one background task revalidates it, so a screen load never
    waits on B14 for a value the window has only just released. Past the
    ceiling -- or with nothing cached -- the requester waits for a fresh read,
    and the lock keeps that wait single-flight exactly as before.
    """
    owner = _roster_owner(list_fn)
    key = id(owner)
    ttl = roster_cache_ttl()
    now = time.monotonic()
    if ttl > 0:
        cached = _ROSTER_CACHE.get(key)
        if cached is not None and cached[2] is owner:
            expires_at, rows, _cached_owner, fetched_at = cached
            if expires_at > now:
                return rows
            if fetched_at + _ROSTER_MAX_STALE_SECONDS > now:
                _schedule_roster_refresh(key, owner, list_fn, ttl)
                return rows
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
            _ROSTER_CACHE[key] = (now + ttl, rows, owner, now)
        return rows


def _schedule_roster_refresh(key: int, owner: object, list_fn, ttl: float) -> None:
    """At most one in-flight revalidation per resolver; reads never await it."""
    running = _ROSTER_REFRESH.get(key)
    if running is not None and running[0] is owner and not running[1].done():
        return
    future = asyncio.ensure_future(_refresh_roster(key, owner, list_fn, ttl))
    _ROSTER_REFRESH[key] = (owner, future)


async def _refresh_roster(key: int, owner: object, list_fn, ttl: float) -> None:
    entry = _ROSTER_LOCKS.get(key)
    if entry is None or entry[0] is not owner:
        entry = (owner, asyncio.Lock())
        _ROSTER_LOCKS[key] = entry
    try:
        async with entry[1]:
            now = time.monotonic()
            cached = _ROSTER_CACHE.get(key)
            if (cached is not None and cached[2] is owner
                    and cached[0] > now):
                # A blocking refresh (past the stale ceiling, or the switch
                # re-reading under the lock) already produced a fresher value.
                return
            rows = _validated_models(await list_fn())
            _ROSTER_CACHE[key] = (now + ttl, rows, owner, now)
    except Exception as exc:
        # A failed revalidation is recorded on the host log and changes
        # nothing else: the last good rows stay cached until the stale
        # ceiling, and the next expired read schedules another attempt.
        print(f"ROSTER_REFRESH_FAILED resolver={type(owner).__name__} "
              f"error={type(exc).__name__}", flush=True)


async def claw_verified_model_choices(request: Request) -> JSONResponse:
    """Grade-only readiness for the server-approved Claw grade (#6828).

    Users choose a PADIEM grade only; no model identity reaches the browser.
    Registration and optional model quality/E2E assessments are separate.
    B54/P01/B14 still enforce final per-request execution authorization.

    The readiness follows the server-approved route for the requested grade:
    a centrally stored per-product/per-grade row is the administrator's exact
    selection, and the shared static product contract is used only while no
    such row exists. A disabled central row fails closed instead of silently
    widening back to the previous static lane, and no model name is hardcoded
    here, so renaming a model in the administrator console needs no code edit.
    The response carries only the grade key, its availability and whether the
    server-side route is configured -- never a model id or display name.
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
    # Existence only, never the identity: the readiness read proves the
    # server-side route candidates are actually listed by B14, but neither
    # ids nor names leave this function. A stored central row is the
    # administrator's exact selection for this product/grade. Without a row
    # the shared static contract decides: the free lane is the contract's own
    # free route, and a paid grade keeps the owner-allowed catalog ceiling.
    try:
        roster = await _model_roster(list_fn)
        listed_ids = {model_id for model_id, _name in roster}
        route_ids = {
            model_id for model_id in (route.model_id, route.fallback_model_id)
            if isinstance(model_id, str) and model_id
        }
        if admin_lane or route.source == "central" or requested_tier == "free":
            available = bool(route_ids & listed_ids)
        else:
            available = bool(listed_ids)
    except Exception:
        return JSONResponse(
            {"ok": False, "error": {"code": "model_catalog_unavailable"}},
            status_code=503, headers=headers,
        )

    return JSONResponse({
        "ok": True,
        "scope": "b14_tier_ready",
        "complete_inventory": True,
        "automatic_default": True,
        "route_source": route.source,
        # The ledger revision that governs this grade. 0 means no stored row
        # governs it, so an operator never reads an unrelated revision as an
        # applied decision.
        "route_revision": route_revision,
        "tier": requested_tier,
        "available": available,
    }, headers=headers)
