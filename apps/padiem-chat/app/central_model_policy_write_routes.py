"""#4453 S3: global-Google-admin-only D1 policy write gate, never runtime dispatch.

Preview receipts are signed by an independent server-only key and are bound to
the verified session actor, fixed global workspace, exact diff, CAS revision and
short expiry. D1 owns atomic one-use nonce, audit and rollback history.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.model_assignment_policy import (
    CatalogModel, ModelChange, VerifiedModelAdminGrant,
    _check_changes, _pack, _unpack, _updated, MAX_CHANGES, RECEIPT_TTL,
)
from .auth_routes import current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .central_model_control_routes import (
    _catalog, _registered_catalog, _central_admin, _error, _NO_STORE,
)

WORKSPACE = "padiem-global"
_ACTOR = re.compile(r"usr_[0-9a-f]{32}\Z")


def ready(request: Request) -> bool:
    return (
        isinstance(getattr(request.app.state, "central_model_policy_write_key", None), bytes)
        and len(request.app.state.central_model_policy_write_key) >= 32
        and callable(getattr(getattr(request.app.state, "central_model_policy_store", None), "commit", None))
    )


def _grant(request: Request, now: datetime) -> VerifiedModelAdminGrant:
    user_id = current_user_id(request)
    if not isinstance(user_id, str) or _ACTOR.fullmatch(user_id) is None:
        raise ValueError("invalid_server_verified_operator")
    return VerifiedModelAdminGrant(
        subject_id=user_id, workspace_id=WORKSPACE, product=None,
        permissions=frozenset({"preview", "apply", "rollback"}),
        issued_at=now - timedelta(seconds=2), expires_at=now + timedelta(minutes=1),
        authority_ref="canonical-google-d1-global-admin",
    )


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    public_base = getattr(request.app.state.settings, "public_base_url", "")
    if not origin or not isinstance(public_base, str):
        return False
    try:
        sent, trusted = urlsplit(origin), urlsplit(public_base)
    except ValueError:
        return False
    return (
        sent.scheme in {"https", "http"} and sent.scheme == trusted.scheme
        and sent.netloc == trusted.netloc and not sent.path and not sent.query
        and not sent.fragment and not sent.username and not sent.password
    )


async def _body(request: Request, keys: set[str]) -> dict | None:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return None
    try:
        data = json.loads(await read_bounded_request_body(request, max_bytes=12000))
    except (RequestBodyTooLarge, UnicodeError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and set(data) == keys else None


async def _catalog_models(request: Request) -> dict[str, CatalogModel] | None:
    registered = await _registered_catalog(request)
    selectable = await _catalog(request)
    if registered is None or selectable is None:
        return None
    ready_ids = {row["model_id"] for row in selectable}
    by_id = {row["model_id"]: row for row in registered}
    if not ready_ids <= by_id.keys() or any(
        not by_id[mid]["b14_enabled"] or by_id[mid]["owner_excluded"] for mid in ready_ids
    ):
        return None
    return {
        row["model_id"]: CatalogModel(
            model_id=row["model_id"], registered=True,
            enabled=row["b14_enabled"],
            credential_ready=row["model_id"] in ready_ids,
            owner_allowed=not row["owner_excluded"],
            capabilities=frozenset(row["capabilities"]),
        )
        for row in registered
    }


async def _authorized(request: Request, *, mutation: bool = False):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    if not ready(request):
        return _error(503, "central_model_policy_write_unavailable")
    if mutation and not _same_origin(request):
        return _error(403, "model_policy_origin_forbidden")
    return None


def _contract_error(exc: ControlPlaneContractError):
    code = exc.code
    status = 409 if code in {"model_policy_revision_conflict", "model_policy_receipt_replayed"} else 422
    if code in {"model_admin_forbidden", "model_admin_scope_forbidden"}:
        status = 403
    return _error(status, code)


async def central_model_change_preview(request: Request) -> JSONResponse:
    denied = await _authorized(request, mutation=True)
    if denied is not None:
        return denied
    body = await _body(request, {"model_id", "targets"})
    if body is None or not isinstance(body["targets"], list) or not 1 <= len(body["targets"]) <= MAX_CHANGES:
        return _error(400, "invalid_model_policy_batch")
    if not isinstance(body["model_id"], str):
        return _error(400, "invalid_model_policy_model")
    try:
        changes = tuple(
            ModelChange(product=t["product_id"], tier=t["tier"],
                        model_id=body["model_id"], action=t["action"])
            for t in body["targets"]
            if isinstance(t, dict) and set(t) == {"product_id", "tier", "action"}
        )
        if len(changes) != len(body["targets"]):
            return _error(400, "invalid_model_policy_batch")
        now = datetime.now(timezone.utc)
        grant = _grant(request, now)
        grant.authorize("preview", WORKSPACE, {c.product for c in changes}, now)
        catalog = await _catalog_models(request)
        if catalog is None:
            return _error(503, "b14_catalog_unavailable")
        _check_changes(changes, catalog)
        store = request.app.state.central_model_policy_store
        current = await store.snapshot(WORKSPACE)
        future = _updated(current, changes)
        payload = {
            "version": 1, "operation": "apply", "workspace": WORKSPACE,
            "actor": grant.subject_id, "scope": "global", "revision": current.revision,
            "changes": [c.public() for c in changes],
            "expires": int((now + RECEIPT_TTL).timestamp()),
            "nonce": __import__("secrets").token_hex(16),
        }
        receipt = _pack(payload, request.app.state.central_model_policy_write_key)
        return JSONResponse({
            "ok": True, "mode": "preview_only", "applied": False,
            "persisted": False, "runtime_enforced": False,
            "expected_revision": current.revision, "next_revision": future.revision,
            "diff": [{**c.public(), "previous": current.lookup(*c.key)} for c in changes],
            "confirmation_receipt": receipt,
        }, headers=_NO_STORE)
    except (ControlPlaneContractError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, ControlPlaneContractError):
            return _contract_error(exc)
        return _error(400, "invalid_model_policy_change")
    except Exception:
        return _error(503, "central_model_policy_store_unavailable")


async def central_model_rollback_preview(request: Request) -> JSONResponse:
    denied = await _authorized(request, mutation=True)
    if denied is not None:
        return denied
    body = await _body(request, {"target_revision"})
    if body is None or type(body["target_revision"]) is not int or body["target_revision"] < 0:
        return _error(400, "invalid_model_policy_revision")
    try:
        now = datetime.now(timezone.utc)
        grant = _grant(request, now)
        grant.authorize("rollback", WORKSPACE, {"central"}, now)
        store = request.app.state.central_model_policy_store
        current = await store.snapshot(WORKSPACE)
        target = body["target_revision"]
        previous = await store.previous_revision(WORKSPACE, target)
        if target >= current.revision or previous is None:
            return _error(422, "model_policy_rollback_target_unavailable")
        a = {r.key: r for r in current.rules}
        b = {r.key: r for r in previous.rules}
        changes = tuple(
            ModelChange(*k, b[k].action if k in b else "inherit")
            for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k)
        )
        if not 1 <= len(changes) <= MAX_CHANGES:
            return _error(422, "model_policy_rollback_batch_unavailable")
        payload = {
            "version": 1, "operation": "rollback", "workspace": WORKSPACE,
            "actor": grant.subject_id, "scope": "global", "revision": current.revision,
            "target_revision": target, "changes": [c.public() for c in changes],
            "expires": int((now + RECEIPT_TTL).timestamp()),
            "nonce": __import__("secrets").token_hex(16),
        }
        return JSONResponse({
            "ok": True, "mode": "rollback_preview_only", "applied": False,
            "persisted": False, "runtime_enforced": False, "expected_revision": current.revision,
            "diff": [{**c.public(), "previous": current.lookup(*c.key)} for c in changes],
            "confirmation_receipt": _pack(payload, request.app.state.central_model_policy_write_key),
        }, headers=_NO_STORE)
    except (ControlPlaneContractError, ValueError) as exc:
        return _contract_error(exc) if isinstance(exc, ControlPlaneContractError) else _error(400, "invalid_model_policy_scope")
    except Exception:
        return _error(503, "central_model_policy_store_unavailable")


async def central_model_change_apply(request: Request) -> JSONResponse:
    denied = await _authorized(request, mutation=True)
    if denied is not None:
        return denied
    body = await _body(request, {"confirmation_receipt"})
    if body is None or not isinstance(body["confirmation_receipt"], str):
        return _error(400, "invalid_model_policy_receipt")
    try:
        now = datetime.now(timezone.utc)
        grant = _grant(request, now)
        data = _unpack(body["confirmation_receipt"], request.app.state.central_model_policy_write_key)
        regular = {"version", "operation", "workspace", "actor", "scope",
                   "revision", "changes", "expires", "nonce"}
        rollback = regular | {"target_revision"}
        if (set(data) not in (regular, rollback) or data.get("version") != 1
                or data.get("operation") not in ("apply", "rollback")
                or (data["operation"] == "rollback") != ("target_revision" in data)
                or data.get("workspace") != WORKSPACE
                or data.get("actor") != grant.subject_id or data.get("scope") != "global"
                or type(data.get("revision")) is not int or data["revision"] < 0
                or type(data.get("expires")) is not int
                or int(now.timestamp()) >= data["expires"]
                or not isinstance(data.get("nonce"), str)
                or re.fullmatch(r"[a-f0-9]{32}", data["nonce"]) is None):
            return _error(422, "model_policy_invalid_receipt")
        raw = data["changes"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CHANGES:
            return _error(422, "model_policy_invalid_receipt")
        changes = tuple(
            ModelChange(**x) for x in raw
            if isinstance(x, dict) and set(x) == {"product", "tier", "model_id", "action"}
        )
        if len(changes) != len(raw) or len({c.key for c in changes}) != len(changes):
            return _error(422, "model_policy_invalid_receipt")
        operation = data["operation"]
        grant.authorize("rollback" if operation == "rollback" else "apply",
                        WORKSPACE, {"central"} if operation == "rollback" else {c.product for c in changes}, now)
        store = request.app.state.central_model_policy_store
        if operation == "rollback":
            target = data["target_revision"]
            if type(target) is not int or target < 0 or target >= data["revision"]:
                return _error(422, "model_policy_invalid_receipt")
            current = await store.snapshot(WORKSPACE)
            previous = await store.previous_revision(WORKSPACE, target)
            if current.revision != data["revision"]:
                return _error(409, "model_policy_revision_conflict")
            if previous is None:
                return _error(422, "model_policy_rollback_target_unavailable")
            a, b = {r.key: r for r in current.rules}, {r.key: r for r in previous.rules}
            expected = tuple(ModelChange(*k, b[k].action if k in b else "inherit")
                             for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k))
            if changes != expected:
                return _error(422, "model_policy_invalid_receipt")
        catalog = await _catalog_models(request)
        if catalog is None:
            return _error(503, "b14_catalog_unavailable")
        _check_changes(changes, catalog)
        result = await store.commit(
            grant=grant, workspace_id=WORKSPACE, expected_revision=data["revision"],
            nonce=data["nonce"], operation=operation, changes=changes, catalog=catalog, now=now,
        )
        return JSONResponse({
            "ok": True, "persisted": True, "applied_to_store": True,
            "runtime_enforced": False, "revision": result.revision,
            "rule_count": len(result.rules), "operation": operation,
        }, headers=_NO_STORE)
    except (ControlPlaneContractError, ValueError, TypeError, KeyError) as exc:
        return _contract_error(exc) if isinstance(exc, ControlPlaneContractError) else _error(422, "model_policy_invalid_receipt")
    except Exception:
        return _error(503, "central_model_policy_store_unavailable")


async def central_model_change_audit(request: Request) -> JSONResponse:
    denied = await _authorized(request)
    if denied is not None:
        return denied
    if request.query_params:
        return _error(400, "unexpected_query")
    try:
        rows = await request.app.state.central_model_policy_store.audit(WORKSPACE, limit=30)
        return JSONResponse({
            "ok": True, "mode": "stored_only", "runtime_enforced": False,
            "events": rows,
        }, headers=_NO_STORE)
    except Exception:
        return _error(503, "central_model_policy_store_unavailable")
