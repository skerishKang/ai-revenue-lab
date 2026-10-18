"""#4428: Cloudflare D1 adapter for central product/tier model routes.

Migration 050 MUST be applied in an independently approved operation. This
adapter never creates schema, elects an admin, reads provider keys, makes a
provider call, or changes the B14 registry. Runtime selection reads this store
through ``central_model_route_runtime``; an absent row keeps the historical
static product contract.

Atomic db.batch() is required. The CAS UPDATE -> changes()-guarded NOT NULL
nonce INSERT forces the entire D1 batch to roll back on stale revisions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.model_assignment_policy import (
    MAX_CHANGES,
    CatalogModel,
    VerifiedModelAdminGrant,
)
from padiem_control_plane.model_tier_routes import (
    MAX_ROUTES,
    TierRoute,
    TierRouteChange,
    TierRouteSnapshot,
    _check_route_changes,
    _updated_routes,
)

from .history import _row_to_dict, _rows_from_result

_WORKSPACE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_ACTOR = re.compile(r"usr_[0-9a-f]{32}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")


def _error(code: str) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, code)


def _utc(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _error("model_route_invalid_timestamp")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _validate_id(workspace_id: str) -> None:
    if not isinstance(workspace_id, str) or _WORKSPACE.fullmatch(workspace_id) is None:
        raise _error("invalid_model_route_scope")


def _decode_rows(raw: str, workspace_id: str, revision: int) -> TierRouteSnapshot:
    try:
        rows = json.loads(raw)
        if not isinstance(rows, list):
            raise ValueError()
        return TierRouteSnapshot(
            workspace_id, revision,
            tuple(TierRoute(
                product=v["product"], tier=v["tier"],
                primary_model_id=v["primary_model_id"],
                fallback_model_id=v.get("fallback_model_id"),
                enabled=v["enabled"],
            ) for v in rows),
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise _error("model_route_storage_corrupt") from exc


class D1CentralModelRouteStore:
    """Async adapter with atomic CAS/nonce/audit for per-grade routes."""

    def __init__(self, db: Any):
        if db is None or not callable(getattr(db, "prepare", None)) or not callable(getattr(db, "batch", None)):
            raise ValueError("canonical PADIEM_CHAT_DB D1 with batch() required")
        self.db = db

    def _stmt(self, sql: str, *values: Any) -> Any:
        stmt = self.db.prepare(sql)
        return stmt.bind(*values) if values else stmt

    async def snapshot(self, workspace_id: str) -> TierRouteSnapshot:
        _validate_id(workspace_id)
        header = _row_to_dict(await self._stmt(
            "SELECT revision FROM central_model_route_state WHERE workspace_id=?",
            workspace_id,
        ).first())
        if header is None:
            return TierRouteSnapshot(workspace_id, 0, ())
        revision = header.get("revision")
        if type(revision) is not int or revision < 0:
            raise _error("model_route_storage_corrupt")
        raw = await self._stmt(
            "SELECT product,tier,primary_model_id,fallback_model_id,enabled "
            "FROM central_model_tier_routes WHERE workspace_id=? ORDER BY product,tier",
            workspace_id,
        ).run()
        rows = _rows_from_result(raw)
        if not isinstance(rows, list) or len(rows) > MAX_ROUTES:
            raise _error("model_route_storage_corrupt")
        try:
            routes = tuple(TierRoute(
                product=r["product"], tier=r["tier"],
                primary_model_id=r["primary_model_id"],
                fallback_model_id=r["fallback_model_id"],
                enabled=r["enabled"] == 1,
            ) for r in rows)
            return TierRouteSnapshot(workspace_id, revision, routes)
        except (TypeError, KeyError, ValueError) as exc:
            raise _error("model_route_storage_corrupt") from exc

    async def previous_revision(self, workspace_id: str, revision: int) -> TierRouteSnapshot | None:
        _validate_id(workspace_id)
        if type(revision) is not int or revision < 0:
            raise _error("invalid_model_route_revision")
        if revision == 0:
            return TierRouteSnapshot(workspace_id, 0, ())
        item = _row_to_dict(await self._stmt(
            "SELECT routes_json FROM central_model_route_history "
            "WHERE workspace_id=? AND revision=?", workspace_id, revision,
        ).first())
        if item is None:
            return None
        return _decode_rows(item["routes_json"], workspace_id, revision)

    async def nonce_consumed(self, workspace_id: str, nonce: str) -> bool:
        _validate_id(workspace_id)
        if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
            raise _error("model_route_invalid_receipt")
        item = await self._stmt(
            "SELECT 1 AS found FROM central_model_route_nonces WHERE workspace_id=? AND nonce=?",
            workspace_id, nonce,
        ).first()
        return _row_to_dict(item) is not None

    async def audit(self, workspace_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        _validate_id(workspace_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise _error("invalid_model_route_audit_limit")
        raw = await self._stmt(
            "SELECT revision,actor_user_id,operation,changed_at,diff_json "
            "FROM central_model_route_audit WHERE workspace_id=? "
            "ORDER BY revision DESC LIMIT ?", workspace_id, limit,
        ).run()
        rows = _rows_from_result(raw)
        return [{"revision": r["revision"], "actor": r["actor_user_id"],
                 "operation": r["operation"], "at": r["changed_at"],
                 "changes": json.loads(r["diff_json"])} for r in rows]

    async def commit(
        self, *, grant: VerifiedModelAdminGrant, workspace_id: str, expected_revision: int,
        nonce: str, operation: str, changes: tuple[TierRouteChange, ...],
        catalog: dict[str, CatalogModel], now: datetime,
    ) -> TierRouteSnapshot:
        """Trusted server-only operation. Callers re-verify the signed receipt."""
        _validate_id(workspace_id)
        if type(expected_revision) is not int or expected_revision < 0:
            raise _error("invalid_model_route_revision")
        if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
            raise _error("model_route_invalid_receipt")
        if not isinstance(changes, tuple) or not 1 <= len(changes) <= MAX_CHANGES:
            raise _error("invalid_model_route_batch")
        if any(not isinstance(r, TierRouteChange) for r in changes):
            raise _error("invalid_model_route_change")
        if len({r.key for r in changes}) != len(changes):
            raise _error("duplicate_model_route_change")
        if operation not in ("apply", "rollback"):
            raise _error("model_route_invalid_operation")
        if not isinstance(grant, VerifiedModelAdminGrant):
            raise _error("model_admin_forbidden")
        grant.authorize(
            "rollback" if operation == "rollback" else "apply",
            workspace_id,
            {r.product for r in changes},
            now,
        )
        if _ACTOR.fullmatch(grant.subject_id) is None:
            raise _error("model_admin_forbidden")
        if not isinstance(catalog, dict):
            raise _error("model_route_catalog_unavailable")
        _check_route_changes(changes, catalog)
        if await self.nonce_consumed(workspace_id, nonce):
            raise _error("model_route_receipt_replayed")
        current = await self.snapshot(workspace_id)
        if current.revision != expected_revision:
            raise _error("model_route_revision_conflict")
        future = _updated_routes(current, changes)
        stamp = _utc(now)
        new_revision = expected_revision + 1
        statements = [
            self._stmt(
                "INSERT OR IGNORE INTO central_model_route_state(workspace_id,revision,updated_at) VALUES (?,0,?)",
                workspace_id, stamp,
            ),
            self._stmt(
                "UPDATE central_model_route_state SET revision=?,updated_at=? "
                "WHERE workspace_id=? AND revision=?",
                new_revision, stamp, workspace_id, expected_revision,
            ),
            # MUST immediately follow the CAS UPDATE. If UPDATE changed no row,
            # NULL violates nonce.revision NOT NULL => atomic D1 rollback.
            self._stmt(
                "INSERT INTO central_model_route_nonces(workspace_id,nonce,revision) "
                "VALUES (?,?,CASE WHEN (SELECT changes())=1 THEN ? ELSE NULL END)",
                workspace_id, nonce, new_revision,
            ),
        ]
        for change in changes:
            statements.append(self._stmt(
                "DELETE FROM central_model_tier_routes WHERE workspace_id=? "
                "AND product=? AND tier=?",
                workspace_id, change.product, change.tier,
            ))
            if change.action != "reset":
                statements.append(self._stmt(
                    "INSERT INTO central_model_tier_routes"
                    "(workspace_id,product,tier,primary_model_id,fallback_model_id,enabled) "
                    "VALUES (?,?,?,?,?,?)",
                    workspace_id, change.product, change.tier,
                    change.primary_model_id, change.fallback_model_id,
                    1 if change.enabled else 0,
                ))
        statements.extend([
            self._stmt(
                "INSERT INTO central_model_route_history(workspace_id,revision,routes_json) VALUES (?,?,?)",
                workspace_id, new_revision,
                json.dumps([r.public() for r in future.routes], separators=(",", ":"), sort_keys=True),
            ),
            self._stmt(
                "INSERT INTO central_model_route_audit "
                "(workspace_id,revision,actor_user_id,operation,changed_at,diff_json) "
                "VALUES (?,?,?,?,?,?)",
                workspace_id, new_revision, grant.subject_id, operation, stamp,
                json.dumps([r.public() for r in changes], separators=(",", ":"), sort_keys=True),
            ),
        ])
        await self.db.batch(statements)
        result = await self.snapshot(workspace_id)
        if result != future or not await self.nonce_consumed(workspace_id, nonce):
            raise _error("model_route_commit_unverified")
        return result
