"""#4453 S2: Cloudflare D1 adapter for the common model policy store.

Schema migration 039 MUST be applied in an independently approved operation.
This adapter never creates schema, elects an admin, reads provider keys, makes
a provider call, or authorizes a product dispatch. No production route currently
creates or calls it; runtime APPLY and policy enforcement remain OFF.

Atomic db.batch() is required. The CAS UPDATE -> changes()-guarded NOT NULL
nonce INSERT forces the entire D1 batch to roll back on stale revisions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

from padiem_control_plane.model_assignment_policy import (
    MAX_CHANGES, MAX_RULES, CatalogModel, ModelChange, ModelPolicySnapshot,
    VerifiedModelAdminGrant,
)
from padiem_control_plane.contracts import ControlPlaneContractError

from .history import _row_to_dict, _rows_from_result

_WORKSPACE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_ACTOR = re.compile(r"usr_[0-9a-f]{32}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")


def _error(code: str) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, code)


def _utc(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _error("model_policy_invalid_timestamp")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _validate_id(workspace_id: str) -> None:
    if not isinstance(workspace_id, str) or _WORKSPACE.fullmatch(workspace_id) is None:
        raise _error("invalid_model_policy_scope")


def _decode_rows(raw: str, workspace_id: str, revision: int) -> ModelPolicySnapshot:
    try:
        rows = json.loads(raw)
        if not isinstance(rows, list):
            raise ValueError()
        result = tuple(ModelChange(**v) for v in rows)
        return ModelPolicySnapshot(workspace_id, revision, result)
    except (TypeError, ValueError) as exc:
        raise _error("model_policy_storage_corrupt") from exc


class D1CentralModelPolicyStore:
    """Async adapter with atomic CAS/nonce/audit, NEVER a runtime allow-list."""

    def __init__(self, db: Any):
        if db is None or not callable(getattr(db, "prepare", None)) or not callable(getattr(db, "batch", None)):
            raise ValueError("canonical PADIEM_CHAT_DB D1 with batch() required")
        self.db = db

    def _stmt(self, sql: str, *values: Any) -> Any:
        stmt = self.db.prepare(sql)
        return stmt.bind(*values) if values else stmt

    async def snapshot(self, workspace_id: str) -> ModelPolicySnapshot:
        _validate_id(workspace_id)
        header = _row_to_dict(await self._stmt(
            "SELECT revision FROM central_model_policy_state WHERE workspace_id=?",
            workspace_id,
        ).first())
        if header is None:
            return ModelPolicySnapshot(workspace_id, 0, ())
        revision = header.get("revision")
        if type(revision) is not int or revision < 0:
            raise _error("model_policy_storage_corrupt")
        raw = await self._stmt(
            "SELECT product,tier,model_id,action FROM central_model_policy_rules "
            "WHERE workspace_id=? ORDER BY product,tier,model_id",
            workspace_id,
        ).run()
        rows = _rows_from_result(raw)
        if not isinstance(rows, list) or len(rows) > MAX_RULES:
            raise _error("model_policy_storage_corrupt")
        try:
            rules = tuple(ModelChange(
                product=r["product"], tier=r["tier"], model_id=r["model_id"], action=r["action"],
            ) for r in rows)
            return ModelPolicySnapshot(workspace_id, revision, rules)
        except (TypeError, KeyError, ValueError) as exc:
            raise _error("model_policy_storage_corrupt") from exc

    async def previous_revision(self, workspace_id: str, revision: int) -> ModelPolicySnapshot | None:
        _validate_id(workspace_id)
        if type(revision) is not int or revision < 0:
            raise _error("invalid_model_policy_revision")
        if revision == 0:
            return ModelPolicySnapshot(workspace_id, 0, ())
        item = _row_to_dict(await self._stmt(
            "SELECT rules_json FROM central_model_policy_history "
            "WHERE workspace_id=? AND revision=?", workspace_id, revision,
        ).first())
        if item is None:
            return None
        return _decode_rows(item["rules_json"], workspace_id, revision)

    async def nonce_consumed(self, workspace_id: str, nonce: str) -> bool:
        _validate_id(workspace_id)
        if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
            raise _error("model_policy_invalid_receipt")
        item = await self._stmt(
            "SELECT 1 AS found FROM central_model_policy_nonces WHERE workspace_id=? AND nonce=?",
            workspace_id, nonce,
        ).first()
        return _row_to_dict(item) is not None

    async def audit(self, workspace_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        _validate_id(workspace_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise _error("invalid_model_policy_audit_limit")
        raw = await self._stmt(
            "SELECT revision,actor_user_id,operation,changed_at,diff_json "
            "FROM central_model_policy_audit WHERE workspace_id=? "
            "ORDER BY revision DESC LIMIT ?", workspace_id, limit,
        ).run()
        rows = _rows_from_result(raw)
        return [{"revision": r["revision"], "actor": r["actor_user_id"],
                 "operation": r["operation"], "at": r["changed_at"],
                 "changes": json.loads(r["diff_json"])} for r in rows]

    async def commit(
        self, *, grant: VerifiedModelAdminGrant, workspace_id: str, expected_revision: int,
        nonce: str, operation: str, changes: tuple[ModelChange, ...],
        catalog: dict[str, CatalogModel], now: datetime,
    ) -> ModelPolicySnapshot:
        """Trusted server-only operation. Not exposed through any route.

        Production controller must re-verify an actor/tenant-scoped signed
        confirmation receipt, freshness, CSRF and owner B14 readiness before
        invoking this port. No UI or product runtime consumes rows today.
        """
        _validate_id(workspace_id)
        if type(expected_revision) is not int or expected_revision < 0:
            raise _error("invalid_model_policy_revision")
        if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
            raise _error("model_policy_invalid_receipt")
        if not isinstance(changes, tuple) or not 1 <= len(changes) <= MAX_CHANGES:
            raise _error("invalid_model_policy_batch")
        if any(not isinstance(r, ModelChange) for r in changes):
            raise _error("invalid_model_policy_change")
        if len({r.key for r in changes}) != len(changes):
            raise _error("duplicate_model_policy_change")
        if operation not in ("apply", "rollback"):
            raise _error("model_policy_invalid_operation")
        if not isinstance(grant, VerifiedModelAdminGrant):
            raise _error("model_admin_forbidden")
        grant.authorize(
            "rollback" if operation == "rollback" else "apply",
            workspace_id,
            {"central"} if operation == "rollback" else {r.product for r in changes},
            now,
        )
        if _ACTOR.fullmatch(grant.subject_id) is None:
            raise _error("model_admin_forbidden")
        if operation == "rollback" and grant.product is not None:
            raise _error("model_admin_scope_forbidden")
        if not isinstance(catalog, dict):
            raise _error("model_policy_catalog_unavailable")
        for change in changes:
            row = catalog.get(change.model_id)
            if not isinstance(row, CatalogModel) or not row.registered:
                raise _error("model_policy_unknown_model")
            if change.action == "allow" and not row.live_ready:
                raise _error("model_policy_offline_model")
        if await self.nonce_consumed(workspace_id, nonce):
            raise _error("model_policy_receipt_replayed")
        current = await self.snapshot(workspace_id)
        if current.revision != expected_revision:
            raise _error("model_policy_revision_conflict")
        next_rules = {r.key: r for r in current.rules}
        for change in changes:
            if change.action == "inherit":
                next_rules.pop(change.key, None)
            else:
                next_rules[change.key] = change
        ordered = tuple(next_rules[k] for k in sorted(next_rules))
        try:
            future = ModelPolicySnapshot(workspace_id, expected_revision + 1, ordered)
        except ControlPlaneContractError:
            raise
        stamp = _utc(now)
        new_revision = expected_revision + 1
        statements = [
            self._stmt(
                "INSERT OR IGNORE INTO central_model_policy_state(workspace_id,revision,updated_at) VALUES (?,0,?)",
                workspace_id, stamp,
            ),
            self._stmt(
                "UPDATE central_model_policy_state SET revision=?,updated_at=? "
                "WHERE workspace_id=? AND revision=?",
                new_revision, stamp, workspace_id, expected_revision,
            ),
            # MUST immediately follow the CAS UPDATE. If UPDATE changed no row,
            # NULL violates nonce.revision NOT NULL => atomic D1 rollback.
            self._stmt(
                "INSERT INTO central_model_policy_nonces(workspace_id,nonce,revision) "
                "VALUES (?,?,CASE WHEN (SELECT changes())=1 THEN ? ELSE NULL END)",
                workspace_id, nonce, new_revision,
            ),
        ]
        for change in changes:
            statements.append(self._stmt(
                "DELETE FROM central_model_policy_rules WHERE workspace_id=? "
                "AND product=? AND tier=? AND model_id=?",
                workspace_id, change.product, change.tier, change.model_id,
            ))
            if change.action != "inherit":
                statements.append(self._stmt(
                    "INSERT INTO central_model_policy_rules(workspace_id,product,tier,model_id,action) "
                    "VALUES (?,?,?,?,?)",
                    workspace_id, change.product, change.tier, change.model_id, change.action,
                ))
        statements.extend([
            self._stmt(
                "INSERT INTO central_model_policy_history(workspace_id,revision,rules_json) VALUES (?,?,?)",
                workspace_id, new_revision,
                json.dumps([r.public() for r in future.rules], separators=(",", ":"), sort_keys=True),
            ),
            self._stmt(
                "INSERT INTO central_model_policy_audit "
                "(workspace_id,revision,actor_user_id,operation,changed_at,diff_json) "
                "VALUES (?,?,?,?,?,?)",
                workspace_id, new_revision, grant.subject_id, operation, stamp,
                json.dumps([r.public() for r in changes], separators=(",", ":"), sort_keys=True),
            ),
        ])
        # Cloudflare D1 batch() is a single transaction; no statement may be
        # executed outside it or in partially committed individual calls.
        await self.db.batch(statements)
        result = await self.snapshot(workspace_id)
        if result != future or not await self.nonce_consumed(workspace_id, nonce):
            raise _error("model_policy_commit_unverified")
        return result
