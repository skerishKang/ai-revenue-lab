"""#4453: source-only, tenant-scoped model assignment authority.

B14 remains sole catalog/secret/execution authority; this module owns no
provider connections, customer membership, D1 migration or live dispatch.
The host MUST supply a canonical verified operator grant and trusted B14
catalog projection. Never treat browser-provided identity or readiness as
authoritative. No product consumes these grants until a separate reviewed S2.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json
import re
import secrets
from typing import Any, Protocol

from .contracts import ControlPlaneContractError

PRODUCTS = frozenset({"central", "chat", "claw", "b66", "b14-router"})
TIERS = frozenset({"FREE", "PLUS", "PRO", "MAX"})
ACTIONS = frozenset({"allow", "block", "inherit"})
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
SCOPE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
MAX_CHANGES = 20
MAX_RULES = 2048
RECEIPT_TTL = timedelta(minutes=5)


def _err(code: str) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, code)


def _scope(name: str, value: str) -> str:
    if not isinstance(value, str) or not SCOPE_ID.fullmatch(value):
        raise _err("invalid_model_policy_scope")
    return value


def _now(value: datetime) -> datetime:
    if not isinstance(value, datetime) or not value.tzinfo or value.utcoffset() is None:
        raise _err("invalid_model_policy_time")
    return value.astimezone(timezone.utc)


def _model(value: str) -> str:
    if not isinstance(value, str) or not MODEL_ID.fullmatch(value) or value.startswith("b14/auto"):
        raise _err("invalid_model_policy_model")
    return value


def _canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


@dataclass(frozen=True, slots=True)
class CatalogModel:
    model_id: str
    registered: bool
    enabled: bool
    credential_ready: bool
    owner_allowed: bool
    capabilities: frozenset[str]

    def __post_init__(self) -> None:
        _model(self.model_id)
        if any(type(v) is not bool for v in (self.registered, self.enabled, self.credential_ready, self.owner_allowed)):
            raise _err("invalid_model_policy_catalog")
        if not isinstance(self.capabilities, frozenset) or any(
            not isinstance(c, str) or not SCOPE_ID.fullmatch(c) for c in self.capabilities
        ):
            raise _err("invalid_model_policy_catalog")

    @property
    def live_ready(self) -> bool:
        return self.registered and self.enabled and self.credential_ready and self.owner_allowed


@dataclass(frozen=True, slots=True)
class ModelChange:
    product: str
    tier: str
    model_id: str
    action: str

    def __post_init__(self) -> None:
        if self.product not in PRODUCTS or self.tier not in TIERS or self.action not in ACTIONS:
            raise _err("invalid_model_policy_change")
        _model(self.model_id)

    @property
    def key(self) -> tuple[str, str, str]:
        return self.product, self.tier, self.model_id

    def public(self) -> dict[str, str]:
        return {"product": self.product, "tier": self.tier,
                "model_id": self.model_id, "action": self.action}


@dataclass(frozen=True, slots=True)
class VerifiedModelAdminGrant:
    """Injected only after server-side canonical identity/workspace verification.

    product=None means global operator; product=one product means scoped
    administrator. B66-local admin alone is never a source for this value.
    """

    subject_id: str
    workspace_id: str
    product: str | None
    permissions: frozenset[str]
    issued_at: datetime
    expires_at: datetime
    authority_ref: str

    def __post_init__(self) -> None:
        _scope("subject_id", self.subject_id)
        _scope("workspace_id", self.workspace_id)
        _scope("authority_ref", self.authority_ref)
        if self.product is not None and (self.product not in PRODUCTS or self.product == "central"):
            raise _err("invalid_model_admin_product")
        if not isinstance(self.permissions, frozenset) or not self.permissions or not self.permissions <= {"preview", "apply", "rollback"}:
            raise _err("invalid_model_admin_permissions")
        if _now(self.expires_at) <= _now(self.issued_at):
            raise _err("invalid_model_admin_expiry")

    def authorize(self, action: str, workspace: str, products: set[str], now: datetime) -> None:
        at = _now(now)
        if not (self.issued_at <= at < self.expires_at):
            raise _err("model_admin_grant_expired")
        if self.workspace_id != workspace or action not in self.permissions:
            raise _err("model_admin_forbidden")
        if self.product is not None and products != {self.product}:
            raise _err("model_admin_scope_forbidden")


@dataclass(frozen=True, slots=True)
class ModelPolicySnapshot:
    workspace_id: str
    revision: int
    rules: tuple[ModelChange, ...]

    def __post_init__(self) -> None:
        _scope("workspace_id", self.workspace_id)
        if type(self.revision) is not int or self.revision < 0:
            raise _err("invalid_model_policy_revision")
        if not isinstance(self.rules, tuple) or len(self.rules) > MAX_RULES:
            raise _err("invalid_model_policy_rules")
        if any(not isinstance(row, ModelChange) or row.action == "inherit" for row in self.rules):
            raise _err("invalid_model_policy_rules")
        keys = [row.key for row in self.rules]
        if len(keys) != len(set(keys)):
            raise _err("duplicate_model_policy_rule")

    def lookup(self, product: str, tier: str, model_id: str) -> str:
        return next((r.action for r in self.rules if r.key == (product, tier, model_id)), "inherit")


@dataclass(frozen=True, slots=True)
class ModelAvailability:
    allowed: bool
    reason: str
    global_action: str
    product_action: str
    revision: int | None


def effective_model(
    snapshot: ModelPolicySnapshot | None, *,
    workspace_id: str, product: str, tier: str, model: CatalogModel | None,
    model_id: str, capability_ready: bool, trusted_policy_fresh: bool,
) -> ModelAvailability:
    """Reason-by-layer, exact model only. No implicit tier/default route."""
    _scope("workspace_id", workspace_id)
    _model(model_id)
    if product not in PRODUCTS - {"central"} or tier not in TIERS:
        raise _err("invalid_model_policy_target")
    if snapshot is None or snapshot.workspace_id != workspace_id or not trusted_policy_fresh:
        return ModelAvailability(False, "policy_unavailable", "unknown", "unknown", None)
    global_action = snapshot.lookup("central", tier, model_id)
    product_action = snapshot.lookup(product, tier, model_id)
    if model is None or model.model_id != model_id or not model.registered:
        reason = "b14_model_unknown"
    elif not model.owner_allowed:
        reason = "b14_owner_not_allowed"
    elif not model.enabled or not model.credential_ready:
        reason = "b14_model_offline"
    elif global_action == "block":
        reason = "central_blocked"
    elif global_action != "allow":
        reason = "central_unassigned"
    elif product_action == "block":
        reason = "product_blocked"
    elif product_action != "allow":
        reason = "product_unassigned"
    elif type(capability_ready) is not bool or not capability_ready:
        reason = "product_capability_blocked"
    else:
        reason = "allowed"
    return ModelAvailability(reason == "allowed", reason, global_action, product_action, snapshot.revision)


def _check_changes(changes: tuple[ModelChange, ...], catalog: dict[str, CatalogModel]) -> None:
    if not isinstance(changes, tuple) or not 1 <= len(changes) <= MAX_CHANGES:
        raise _err("invalid_model_policy_batch")
    if any(not isinstance(row, ModelChange) for row in changes):
        raise _err("invalid_model_policy_change")
    if len({r.key for r in changes}) != len(changes):
        raise _err("duplicate_model_policy_change")
    for row in changes:
        found = catalog.get(row.model_id)
        if found is None or not isinstance(found, CatalogModel) or not found.registered:
            raise _err("model_policy_unknown_model")
        if row.action == "allow" and not found.live_ready:
            raise _err("model_policy_offline_model")


def _updated(snapshot: ModelPolicySnapshot, changes: tuple[ModelChange, ...]) -> ModelPolicySnapshot:
    values = {r.key: r for r in snapshot.rules}
    for row in changes:
        if row.action == "inherit":
            values.pop(row.key, None)
        else:
            values[row.key] = row
    ordered = tuple(values[k] for k in sorted(values))
    return ModelPolicySnapshot(snapshot.workspace_id, snapshot.revision + 1, ordered)


def _pack(body: dict[str, Any], key: bytes) -> str:
    if not isinstance(key, bytes) or len(key) < 32:
        raise _err("model_policy_signer_not_configured")
    encoded = base64.urlsafe_b64encode(_canon(body)).decode("ascii").rstrip("=")
    mac = hmac.new(key, encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return encoded + "." + mac


def _unpack(receipt: str, key: bytes) -> dict[str, Any]:
    if not isinstance(receipt, str) or len(receipt) > 12000 or "." not in receipt:
        raise _err("model_policy_invalid_receipt")
    encoded, mac = receipt.rsplit(".", 1)
    if not hmac.compare_digest(_pack_from_encoded(encoded, key), mac):
        raise _err("model_policy_invalid_receipt")
    try:
        result = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (ValueError, UnicodeError):
        raise _err("model_policy_invalid_receipt") from None
    if not isinstance(result, dict):
        raise _err("model_policy_invalid_receipt")
    return result


def _pack_from_encoded(encoded: str, key: bytes) -> str:
    if not isinstance(key, bytes) or len(key) < 32:
        raise _err("model_policy_signer_not_configured")
    return hmac.new(key, encoded.encode("ascii"), hashlib.sha256).hexdigest()


class DurableModelPolicyStore(Protocol):
    def nonce_consumed(self, workspace_id: str, nonce: str) -> bool: ...
    def snapshot(self, workspace_id: str) -> ModelPolicySnapshot: ...
    def previous_revision(self, workspace_id: str, revision: int) -> ModelPolicySnapshot | None: ...
    def commit(self, *, workspace_id: str, expected_revision: int,
               nonce: str, actor_id: str, operation: str, changes: tuple[ModelChange, ...],
               now: datetime) -> ModelPolicySnapshot: ...


class ModelAssignmentService:
    """S1 host contract; not wired to any live Worker until explicit S2."""

    def __init__(self, *, store: DurableModelPolicyStore | None,
                 signing_key: bytes | None, enabled: bool = False) -> None:
        self._store = store
        self._key = signing_key
        self._enabled = enabled

    def _ready(self) -> DurableModelPolicyStore:
        if not self._enabled or self._store is None or self._key is None:
            raise _err("model_policy_apply_not_configured")
        return self._store

    def preview(self, *, grant: VerifiedModelAdminGrant, workspace_id: str,
                changes: tuple[ModelChange, ...], catalog: dict[str, CatalogModel],
                now: datetime) -> dict[str, Any]:
        store = self._ready()
        grant.authorize("preview", workspace_id, {r.product for r in changes}, now)
        _check_changes(changes, catalog)
        current = store.snapshot(workspace_id)
        future = _updated(current, changes)
        before = [dict(r.public(), previous=current.lookup(*r.key)) for r in changes]
        payload = {"version": 1, "operation": "apply", "workspace": workspace_id,
                   "actor": grant.subject_id, "scope": grant.product or "global",
                   "revision": current.revision, "changes": [c.public() for c in changes],
                   "expires": int((_now(now) + RECEIPT_TTL).timestamp()),
                   "nonce": secrets.token_hex(16)}
        return {"mode": "preview_only", "applied": False, "persisted": False,
                "dispatch_authorized": False, "expected_revision": current.revision,
                "next_revision": future.revision, "diff": before,
                "confirmation_receipt": _pack(payload, self._key)}

    def preview_rollback(self, *, grant: VerifiedModelAdminGrant,
                         workspace_id: str, target_revision: int, now: datetime) -> dict[str, Any]:
        store = self._ready()
        grant.authorize("rollback", workspace_id, {"central"}, now)
        current = store.snapshot(workspace_id)
        previous = store.previous_revision(workspace_id, target_revision)
        if previous is None or target_revision >= current.revision:
            raise _err("model_policy_rollback_target_unavailable")
        before = {r.key:r for r in current.rules}
        after = {r.key:r for r in previous.rules}
        changes = tuple(ModelChange(*k, after[k].action if k in after else "inherit")
                        for k in sorted(before.keys() | after.keys())
                        if before.get(k) != after.get(k))
        if not changes or len(changes) > MAX_CHANGES:
            raise _err("model_policy_rollback_batch_unavailable")
        payload = {"version": 1, "operation": "rollback", "workspace": workspace_id,
                   "actor": grant.subject_id, "scope": "global",
                   "revision": current.revision, "target_revision": target_revision,
                   "changes": [c.public() for c in changes],
                   "expires": int((_now(now) + RECEIPT_TTL).timestamp()),
                   "nonce": secrets.token_hex(16)}
        return {"mode": "rollback_preview_only", "applied": False, "persisted": False,
                "expected_revision": current.revision, "next_revision": current.revision+1,
                "confirmation_receipt": _pack(payload, self._key)}

    def apply(self, *, grant: VerifiedModelAdminGrant, workspace_id: str,
              receipt: str, catalog: dict[str, CatalogModel], now: datetime) -> ModelPolicySnapshot:
        store = self._ready()
        data = _unpack(receipt, self._key)
        if set(data) not in (
            {"version", "operation", "workspace", "actor", "scope", "revision", "changes", "expires", "nonce"},
            {"version", "operation", "workspace", "actor", "scope", "revision", "target_revision", "changes", "expires", "nonce"},
        ) or data.get("version") != 1 or data.get("operation") not in {"apply", "rollback"}:
            raise _err("model_policy_invalid_receipt")
        if data["workspace"] != workspace_id or data["actor"] != grant.subject_id:
            raise _err("model_policy_receipt_scope_mismatch")
        if data["scope"] != (grant.product or "global"):
            raise _err("model_policy_receipt_scope_mismatch")
        if type(data["expires"]) is not int or int(_now(now).timestamp()) >= data["expires"]:
            raise _err("model_policy_receipt_expired")
        if type(data["revision"]) is not int or data["revision"] < 0 or not isinstance(data["nonce"], str) or not re.fullmatch(r"[a-f0-9]{32}", data["nonce"]):
            raise _err("model_policy_invalid_receipt")
        raw = data["changes"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CHANGES:
            raise _err("model_policy_invalid_receipt")
        try:
            changes = tuple(ModelChange(**v) for v in raw if isinstance(v, dict) and set(v) == {"product", "tier", "model_id", "action"})
        except (ValueError, TypeError) as e:
            raise _err("model_policy_invalid_receipt") from e
        if len(changes) != len(raw):
            raise _err("model_policy_invalid_receipt")
        operation = data["operation"]
        if store.nonce_consumed(workspace_id, data["nonce"]):
            raise _err("model_policy_receipt_replayed")
        grant.authorize("rollback" if operation == "rollback" else "apply",
                        workspace_id, {"central"} if operation == "rollback" else {r.product for r in changes}, now)
        if operation == "apply":
            _check_changes(changes, catalog)
        else:
            if grant.product is not None:
                raise _err("model_admin_scope_forbidden")
            if type(data.get("target_revision")) is not int or data["target_revision"] >= data["revision"]:
                raise _err("model_policy_invalid_receipt")
            previous = store.previous_revision(workspace_id, data["target_revision"])
            if previous is None:
                raise _err("model_policy_rollback_target_unavailable")
            current = store.snapshot(workspace_id)
            if current.revision != data["revision"]:
                raise _err("model_policy_revision_conflict")
            a = {r.key:r for r in current.rules}
            b = {r.key:r for r in previous.rules}
            expected = tuple(ModelChange(*k, b[k].action if k in b else "inherit")
                             for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k))
            if expected != changes:
                raise _err("model_policy_invalid_receipt")
        return store.commit(workspace_id=workspace_id, expected_revision=data["revision"],
                            nonce=data["nonce"], actor_id=grant.subject_id, operation=operation,
                            changes=changes, now=_now(now))
