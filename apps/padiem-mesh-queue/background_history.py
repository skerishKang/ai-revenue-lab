"""Queue-only background dispatch metadata; shared claim/lease rules stay in Chat."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re

from app.history import (
    D1HistoryStore, HistoryError, ORACLE_MESH_CLAIM_LEASE_SECONDS,
    _changed_rows, _iso, _now_iso,
)


def _operation_json(operation):
    if operation is None:
        return None
    if not isinstance(operation, dict):
        raise HistoryError("invalid background operation")
    op = operation.get("op")
    fields = {
        "read": {"op", "path"}, "list": {"op", "path"},
        "delete": {"op", "path"}, "move": {"op", "path", "destination"},
        "write": {"op", "path", "expected_bytes", "expected_sha256"},
    }
    if not isinstance(op, str) or op not in fields or set(operation) != fields[op]:
        raise HistoryError("invalid background operation")
    for key in ("path", "destination") if op == "move" else ("path",):
        value = operation[key]
        if not isinstance(value, str) or not value or any(ord(ch) < 32 for ch in value):
            raise HistoryError("invalid background operation path")
    if op == "write" and (
        type(operation["expected_bytes"]) is not int or operation["expected_bytes"] < 0
        or not isinstance(operation["expected_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", operation["expected_sha256"])
    ):
        raise HistoryError("invalid background write evidence")
    return json.dumps(operation, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


class QueueHistoryStore(D1HistoryStore):
    """Add a trusted execution-mode bit on the same SQLite transaction as staging."""

    async def create_oracle_mesh_dispatch(self, *, background=False, job_operation=None, **arguments):
        if type(background) is not bool:
            raise HistoryError("background must be a boolean")
        if background and arguments.get("kind", "read") not in {"read", "command"}:
            raise HistoryError("background requires a read or command dispatch")
        operation_json = _operation_json(job_operation)
        if operation_json is not None and not background:
            raise HistoryError("job operation requires a background dispatch")
        connection = self.db.connection
        # A savepoint joins a caller's transaction if there is one and otherwise
        # is the transaction. A separate claimer cannot see a dispatch before
        # its mode is recorded. The existing SQLite adapter never yields during
        # its statements, and run ownership is checked before staging.
        connection.execute("SAVEPOINT queue_background_dispatch_create")
        try:
            existing = {
                row["dispatch_id"] for row in await self.db.prepare(
                    "SELECT dispatch_id FROM oracle_mesh_dispatch WHERE user_id=? AND run_id=?"
                ).bind(arguments.get("user_id"), arguments.get("run_id")).all()
            }
            row = await super().create_oracle_mesh_dispatch(**arguments)
            metadata = await self.db.prepare(
                "SELECT background, job_operation_json FROM queue_background_dispatch WHERE dispatch_id=?"
            ).bind(row["dispatch_id"]).first()
            # Legacy rows have normal execution mode. Replaying a correlation
            # cannot silently switch an already staged job to another mode.
            if (metadata is not None and bool(metadata["background"]) != background
                    or metadata is None and row["dispatch_id"] in existing and background):
                raise HistoryError("oracle mesh dispatch execution mode changed")
            if metadata is not None and metadata["job_operation_json"] != operation_json:
                raise HistoryError("oracle mesh dispatch operation changed")
            await self.db.prepare(
                "INSERT OR IGNORE INTO queue_background_dispatch"
                "(dispatch_id, background, job_operation_json) VALUES (?,?,?)"
            ).bind(row["dispatch_id"], int(background), operation_json).run()
            connection.execute("RELEASE SAVEPOINT queue_background_dispatch_create")
        except BaseException:
            connection.execute("ROLLBACK TO SAVEPOINT queue_background_dispatch_create")
            connection.execute("RELEASE SAVEPOINT queue_background_dispatch_create")
            raise
        if background:
            return {**row, "background": True, "owner_ref": arguments["user_id"]}
        return row

    async def _background_projection(self, row, *, include_operation=False):
        if row is None:
            return None
        metadata = await self.db.prepare(
            "SELECT background, job_operation_json FROM queue_background_dispatch WHERE dispatch_id=?"
        ).bind(row["dispatch_id"]).first()
        if metadata is not None and metadata["background"] == 1:
            # Only the stored dispatch owner is authoritative. No caller can
            # supply owner_ref independently of the already checked user_id.
            result = {**row, "background": True, "owner_ref": row["user_id"]}
            if include_operation and metadata["job_operation_json"] is not None:
                result["job_operation"] = json.loads(metadata["job_operation_json"])
            return result
        return row

    async def oldest_pending_oracle_mesh_dispatch(self):
        # Do not let one PC's long-running job block polling another PC. All
        # work on the same physical node/device stays serialized, including
        # ordinary foreground dispatches submitted while a job is running.
        now = _now_iso()
        row = await self.db.prepare(
            "SELECT dispatch_id, user_id, run_id, kind, command_text, command_id, tool_request_ref, "
            "request_id, revision_ref, evidence_ref, request_fingerprint, account_ref, "
            "workspace_ref, device_id, binding_ref, node_ref, root_ref, path_relative, "
            "file_path, nonce_sha256, state, expires_at FROM oracle_mesh_dispatch AS candidate "
            "WHERE state='pending' AND expires_at>? "
            "AND (nonce_sha256 IS NULL OR (claimed_until IS NOT NULL AND claimed_until<=?)) "
            "AND NOT EXISTS (SELECT 1 FROM oracle_mesh_dispatch AS active "
            "WHERE active.dispatch_id<>candidate.dispatch_id AND active.state='pending' "
            "AND active.nonce_sha256 IS NOT NULL "
            "AND (active.claimed_until IS NULL OR active.claimed_until>?) "
            "AND (active.node_ref=candidate.node_ref OR active.device_id=candidate.device_id)) "
            "ORDER BY created_at ASC LIMIT 1"
        ).bind(now, now, now).first()
        return await self._background_projection(row)

    async def claim_oracle_mesh_dispatch(self, *, dispatch_id, nonce_sha256):
        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        if not isinstance(nonce_sha256, str) or not nonce_sha256:
            raise HistoryError("nonce_sha256 is required")
        moment = datetime.now(timezone.utc)
        now = _iso(moment)
        written = await self.db.prepare(
            "UPDATE oracle_mesh_dispatch AS candidate SET nonce_sha256=?, claimed_until=? "
            "WHERE dispatch_id=? AND state='pending' AND expires_at>? "
            "AND (nonce_sha256 IS NULL OR (claimed_until IS NOT NULL AND claimed_until<=?)) "
            "AND NOT EXISTS (SELECT 1 FROM oracle_mesh_dispatch AS active "
            "WHERE active.dispatch_id<>candidate.dispatch_id AND active.state='pending' "
            "AND active.nonce_sha256 IS NOT NULL "
            "AND (active.claimed_until IS NULL OR active.claimed_until>?) "
            "AND (active.node_ref=candidate.node_ref OR active.device_id=candidate.device_id))"
        ).bind(
            nonce_sha256, _iso(moment + timedelta(seconds=ORACLE_MESH_CLAIM_LEASE_SECONDS)),
            dispatch_id, now, now, now,
        ).run()
        return _changed_rows(written) == 1

    async def get_pc_output_dispatch_for_owner(self, *, user_id, dispatch_id):
        """Private local output authority; does not widen the public RPC row."""
        row = await super().get_oracle_mesh_dispatch_for_owner(
            user_id=user_id, dispatch_id=dispatch_id
        )
        if row is None:
            return None
        target = await self.db.prepare(
            "SELECT device_id FROM oracle_mesh_dispatch WHERE dispatch_id=? AND user_id=?"
        ).bind(dispatch_id, user_id).first()
        return {**row, **target} if target is not None else None

    async def get_oracle_mesh_dispatch_for_owner(self, *, user_id, dispatch_id):
        row = await self._background_projection(
            await super().get_oracle_mesh_dispatch_for_owner(
                user_id=user_id, dispatch_id=dispatch_id
            ), include_operation=True,
        )
        if row is None or row.get("background") is not True:
            return row
        details = await self.db.prepare(
            "SELECT device_id, node_ref, root_ref, "
            "CASE WHEN nonce_sha256 IS NULL THEN 0 ELSE 1 END AS claimed "
            "FROM oracle_mesh_dispatch WHERE dispatch_id=? AND user_id=?"
        ).bind(dispatch_id, user_id).first()
        if details is None:
            return None
        return {**row, **details, "claimed": bool(details["claimed"])}
