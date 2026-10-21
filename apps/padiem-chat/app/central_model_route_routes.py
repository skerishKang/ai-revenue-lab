"""#4428: global-admin per-product/tier route write gate.

Preview receipts are signed with the existing server-only policy key and are
bound to the verified session actor, fixed global workspace, exact diff, CAS
revision and short expiry. D1 owns the atomic one-use nonce, route history and
audit. Only the central per-grade routes are runtime-enforced; the older
allow/block rule ledger keeps its separate, stored-only contract.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.model_assignment_policy import (
    MAX_CHANGES, RECEIPT_TTL, _pack, _unpack,
)
from padiem_control_plane.model_tier_routes import (
    ROUTE_PRODUCTS, TierRouteChange, TierRouteSnapshot,
    _check_route_changes, _route_diff, _updated_routes, project_shared_routes,
)

from .central_model_control_routes import (
    _central_admin, _catalog, _error, _registered_catalog, _NO_STORE,
)
from .central_model_policy_write_routes import (
    WORKSPACE, _body, _catalog_models, _contract_error, _grant, _same_origin,
)

_SET_KEYS = {"product", "tier", "action", "primary_model_id", "fallback_model_id", "enabled"}
_RESET_KEYS = {"product", "tier", "action"}
_REGULAR_KEYS = {"version", "operation", "workspace", "actor", "scope",
                 "revision", "changes", "expires", "nonce"}
_ROLLBACK_KEYS = _REGULAR_KEYS | {"target_revision"}
_NONCE = re.compile(r"[a-f0-9]{32}\Z")


def _store(request: Request):
    return getattr(request.app.state, "central_model_route_store", None)


def _route_contract_error(exc: ControlPlaneContractError) -> JSONResponse:
    # The shared helper knows only the older policy-ledger codes; route CAS and
    # nonce replays are conflicts on this ledger too, not unprocessable input.
    if exc.code in {"model_route_revision_conflict", "model_route_receipt_replayed"}:
        return _error(409, exc.code)
    return _contract_error(exc)


def route_ready(request: Request) -> bool:
    key = getattr(request.app.state, "central_model_policy_write_key", None)
    store = _store(request)
    return (
        isinstance(key, bytes) and len(key) >= 32
        and callable(getattr(store, "commit", None))
        and callable(getattr(store, "snapshot", None))
    )


async def _authorized(request: Request, *, mutation: bool = False) -> JSONResponse | None:
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    if not route_ready(request):
        return _error(503, "central_model_route_write_unavailable")
    if mutation and not _same_origin(request):
        return _error(403, "model_route_origin_forbidden")
    return None


def _change_from_body(body: dict) -> TierRouteChange | None:
    action = body.get("action")
    if action == "reset":
        return TierRouteChange(product=body["product"], tier=body["tier"], action="reset")
    if action != "set":
        return None
    return TierRouteChange(
        product=body["product"], tier=body["tier"], action="set",
        primary_model_id=body.get("primary_model_id"),
        fallback_model_id=body.get("fallback_model_id"),
        enabled=body.get("enabled"),
    )


def _static_contract() -> dict[str, dict[str, object]]:
    from padiem_control_plane.product_tier_routes import (
        FREE_FALLBACK_B14_MODEL_ID, ProductTierLabel, ProductTierRoutesError, active_route_for,
    )
    from .b66_grade_models import B66_GRADE_MODEL_IDS

    result: dict[str, dict[str, object]] = {}
    labels = {
        "FREE": ProductTierLabel.FREE, "PLUS": ProductTierLabel.PLUS,
        "PRO": ProductTierLabel.PRO, "MAX": ProductTierLabel.MAX,
    }
    for product in ("chat", "claw"):
        result[product] = {}
        for tier, label in labels.items():
            try:
                route = active_route_for(label)
            except ProductTierRoutesError:
                route = None
            result[product][tier] = {
                "primary_model_id": route.model_id if route is not None else None,
                "fallback_model_id": FREE_FALLBACK_B14_MODEL_ID if tier == "FREE" else None,
            }
    result["b66"] = {
        tier.upper(): {"primary_model_id": model_id, "fallback_model_id": None}
        for tier, model_id in B66_GRADE_MODEL_IDS.items()
    }
    return result


async def central_model_routes_get(request: Request) -> JSONResponse:
    denied = await _authorized(request)
    if denied is not None:
        return denied
    if request.query_params:
        return _error(400, "unexpected_query")
    try:
        current = await _store(request).snapshot(WORKSPACE)
        if not isinstance(current, TierRouteSnapshot):
            raise ValueError("invalid route snapshot")
        events = await _store(request).audit(WORKSPACE, limit=12)
        return JSONResponse({
            "ok": True, "workspace": WORKSPACE, "revision": current.revision,
            "routes": [row.public() for row in project_shared_routes(current)],
            "static": _static_contract(),
            "write_enabled": True, "runtime_enforced": True,
            "events": events,
        }, headers=_NO_STORE)
    except Exception:
        return _error(503, "central_model_route_store_unavailable")


async def central_model_route_preview(request: Request) -> JSONResponse:
    denied = await _authorized(request, mutation=True)
    if denied is not None:
        return denied
    body = await _body(request, _SET_KEYS | _RESET_KEYS)
    if body is None:
        return _error(400, "invalid_model_route_change")
    action = body.get("action")
    if action not in ("set", "reset"):
        return _error(400, "invalid_model_route_action")
    if set(body) != (_SET_KEYS if action == "set" else _RESET_KEYS):
        return _error(400, "invalid_model_route_change")
    try:
        change = _change_from_body(body)
        if change is None:
            return _error(400, "invalid_model_route_change")
        now = datetime.now(timezone.utc)
        grant = _grant(request, now)
        grant.authorize("preview", WORKSPACE, {change.product}, now)
        catalog = await _catalog_models(request)
        if catalog is None:
            return _error(503, "b14_catalog_unavailable")
        _check_route_changes((change,), catalog)
        current = await _store(request).snapshot(WORKSPACE)
        future = _updated_routes(current, (change,))
        payload = {
            "version": 1, "operation": "route_apply", "workspace": WORKSPACE,
            "actor": grant.subject_id, "scope": "global", "revision": current.revision,
            "changes": [change.public()],
            "expires": int((now + RECEIPT_TTL).timestamp()),
            "nonce": secrets.token_hex(16),
        }
        return JSONResponse({
            "ok": True, "mode": "route_preview_only", "applied": False,
            "persisted": False, "runtime_enforced": True,
            "expected_revision": current.revision, "next_revision": future.revision,
            "diff": _route_diff(current, (change,)),
            "confirmation_receipt": _pack(payload, request.app.state.central_model_policy_write_key),
        }, headers=_NO_STORE)
    except ControlPlaneContractError as exc:
        return _route_contract_error(exc)
    except (ValueError, TypeError, KeyError):
        return _error(400, "invalid_model_route_change")
    except Exception:
        return _error(503, "central_model_route_store_unavailable")


async def central_model_route_rollback_preview(request: Request) -> JSONResponse:
    denied = await _authorized(request, mutation=True)
    if denied is not None:
        return denied
    body = await _body(request, {"target_revision"})
    if body is None or type(body["target_revision"]) is not int or body["target_revision"] < 0:
        return _error(400, "invalid_model_route_revision")
    try:
        now = datetime.now(timezone.utc)
        grant = _grant(request, now)
        store = _store(request)
        current = await store.snapshot(WORKSPACE)
        target = body["target_revision"]
        previous = await store.previous_revision(WORKSPACE, target)
        if target >= current.revision or previous is None:
            return _error(422, "model_route_rollback_target_unavailable")
        changes = _route_rollback_changes(current, previous)
        if not 1 <= len(changes) <= MAX_CHANGES:
            return _error(422, "model_route_rollback_batch_unavailable")
        grant.authorize("rollback", WORKSPACE, {c.product for c in changes}, now)
        payload = {
            "version": 1, "operation": "route_rollback", "workspace": WORKSPACE,
            "actor": grant.subject_id, "scope": "global", "revision": current.revision,
            "target_revision": target, "changes": [c.public() for c in changes],
            "expires": int((now + RECEIPT_TTL).timestamp()),
            "nonce": secrets.token_hex(16),
        }
        return JSONResponse({
            "ok": True, "mode": "route_rollback_preview_only", "applied": False,
            "persisted": False, "runtime_enforced": True,
            "expected_revision": current.revision,
            "diff": _route_diff(current, changes),
            "confirmation_receipt": _pack(payload, request.app.state.central_model_policy_write_key),
        }, headers=_NO_STORE)
    except ControlPlaneContractError as exc:
        return _route_contract_error(exc)
    except Exception:
        return _error(503, "central_model_route_store_unavailable")


def _route_rollback_changes(
    current: TierRouteSnapshot, previous: TierRouteSnapshot,
) -> tuple[TierRouteChange, ...]:
    keys = sorted({row.key for row in current.routes} | {row.key for row in previous.routes})
    changes: list[TierRouteChange] = []
    for product, tier in keys:
        before, after = current.lookup(product, tier), previous.lookup(product, tier)
        if before == after:
            continue
        if after is None:
            changes.append(TierRouteChange(product=product, tier=tier, action="reset"))
        else:
            changes.append(TierRouteChange(
                product=product, tier=tier, action="set",
                primary_model_id=after.primary_model_id,
                fallback_model_id=after.fallback_model_id,
                enabled=after.enabled,
            ))
    return tuple(changes)


async def central_model_route_apply(request: Request) -> JSONResponse:
    denied = await _authorized(request, mutation=True)
    if denied is not None:
        return denied
    body = await _body(request, {"confirmation_receipt"})
    if body is None or not isinstance(body["confirmation_receipt"], str):
        return _error(400, "invalid_model_route_receipt")
    try:
        now = datetime.now(timezone.utc)
        grant = _grant(request, now)
        key = request.app.state.central_model_policy_write_key
        data = _unpack(body["confirmation_receipt"], key)
        operation = data.get("operation")
        if (set(data) not in (_REGULAR_KEYS, _ROLLBACK_KEYS)
                or data.get("version") != 1
                or operation not in ("route_apply", "route_rollback")
                or (operation == "route_rollback") != ("target_revision" in data)
                or data.get("workspace") != WORKSPACE
                or data.get("actor") != grant.subject_id or data.get("scope") != "global"
                or type(data.get("revision")) is not int or data["revision"] < 0
                or type(data.get("expires")) is not int
                or int(now.timestamp()) >= data["expires"]
                or not isinstance(data.get("nonce"), str)
                or _NONCE.fullmatch(data["nonce"]) is None):
            return _error(422, "model_route_invalid_receipt")
        raw = data["changes"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CHANGES:
            return _error(422, "model_route_invalid_receipt")
        changes = []
        for item in raw:
            if not isinstance(item, dict) or set(item) != {
                "product", "tier", "action", "primary_model_id", "fallback_model_id", "enabled",
            }:
                return _error(422, "model_route_invalid_receipt")
            changes.append(TierRouteChange(
                product=item["product"], tier=item["tier"], action=item["action"],
                primary_model_id=item["primary_model_id"],
                fallback_model_id=item["fallback_model_id"],
                enabled=item["enabled"],
            ))
        changes = tuple(changes)
        if len({c.key for c in changes}) != len(changes):
            return _error(422, "model_route_invalid_receipt")
        grant.authorize(
            "rollback" if operation == "route_rollback" else "apply",
            WORKSPACE, {c.product for c in changes}, now,
        )
        store = _store(request)
        if operation == "route_rollback":
            target = data["target_revision"]
            if type(target) is not int or target < 0 or target >= data["revision"]:
                return _error(422, "model_route_invalid_receipt")
            current = await store.snapshot(WORKSPACE)
            if current.revision != data["revision"]:
                return _error(409, "model_route_revision_conflict")
            previous = await store.previous_revision(WORKSPACE, target)
            if previous is None:
                return _error(422, "model_route_rollback_target_unavailable")
            if changes != _route_rollback_changes(current, previous):
                return _error(422, "model_route_invalid_receipt")
        catalog = await _catalog_models(request)
        if catalog is None:
            return _error(503, "b14_catalog_unavailable")
        _check_route_changes(changes, catalog)
        result = await store.commit(
            grant=grant, workspace_id=WORKSPACE, expected_revision=data["revision"],
            nonce=data["nonce"],
            operation="rollback" if operation == "route_rollback" else "apply",
            changes=changes, catalog=catalog, now=now,
        )
        return JSONResponse({
            "ok": True, "persisted": True, "applied_to_store": True,
            "runtime_enforced": True, "revision": result.revision,
            "route_count": len(result.routes),
            "operation": "rollback" if operation == "route_rollback" else "apply",
        }, headers=_NO_STORE)
    except ControlPlaneContractError as exc:
        return _route_contract_error(exc)
    except (ValueError, TypeError, KeyError):
        return _error(422, "model_route_invalid_receipt")
    except Exception:
        return _error(503, "central_model_route_store_unavailable")


__all__ = [
    "ROUTE_PRODUCTS",
    "central_model_route_apply",
    "central_model_route_preview",
    "central_model_route_rollback_preview",
    "central_model_routes_get",
    "route_ready",
]
