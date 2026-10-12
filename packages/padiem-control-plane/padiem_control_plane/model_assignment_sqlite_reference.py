"""#4453 local SQLite reference adapter for atomic CAS + replay + audit.

NOT a Cloudflare D1 migration or runtime binding. D1/DO host must independently
implement the DurableModelPolicyStore port with the same transaction semantics
before any production APPLY can be enabled. Python sqlite is a test/operator
reference only, never a second production authority.
"""
from __future__ import annotations

from datetime import datetime
import json
import sqlite3

from .contracts import ControlPlaneContractError
from .model_assignment_policy import (
    ModelChange, ModelPolicySnapshot, _err, _scope, _updated, _now,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS model_policy_workspaces (
    workspace_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
    rules_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_policy_history (
    workspace_id TEXT NOT NULL, revision INTEGER NOT NULL, rules_json TEXT NOT NULL,
    PRIMARY KEY(workspace_id, revision)
);
CREATE TABLE IF NOT EXISTS model_policy_nonces (
    workspace_id TEXT NOT NULL, nonce TEXT NOT NULL,
    PRIMARY KEY(workspace_id, nonce)
);
CREATE TABLE IF NOT EXISTS model_policy_audit (
    workspace_id TEXT NOT NULL, revision INTEGER NOT NULL,
    actor_id TEXT NOT NULL, operation TEXT NOT NULL,
    recorded_at TEXT NOT NULL, diff_json TEXT NOT NULL,
    PRIMARY KEY(workspace_id, revision)
);
"""


def _encode(rows: tuple[ModelChange, ...]) -> str:
    return json.dumps([r.public() for r in rows], sort_keys=True, separators=(",", ":"))


def _decode(workspace_id: str, revision: int, raw: str) -> ModelPolicySnapshot:
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError()
        rows = tuple(ModelChange(**v) for v in data)
        return ModelPolicySnapshot(workspace_id, revision, rows)
    except (TypeError, ValueError) as exc:
        raise _err("model_policy_storage_corrupt") from exc


class SQLiteModelPolicyStore:
    """Deterministic stdlib integration adapter. No HTTP, cloud bindings or production tables."""

    def __init__(self, path: str = ":memory:") -> None:
        self._db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def snapshot(self, workspace_id: str) -> ModelPolicySnapshot:
        _scope("workspace_id", workspace_id)
        row = self._db.execute(
            "SELECT revision, rules_json FROM model_policy_workspaces WHERE workspace_id=?",
            (workspace_id,),
        ).fetchone()
        if row is None:
            return ModelPolicySnapshot(workspace_id, 0, ())
        return _decode(workspace_id, row[0], row[1])

    def nonce_consumed(self, workspace_id: str, nonce: str) -> bool:
        _scope("workspace_id", workspace_id)
        row = self._db.execute(
            "SELECT 1 FROM model_policy_nonces WHERE workspace_id=? AND nonce=?",
            (workspace_id, nonce),
        ).fetchone()
        return bool(row)

    def previous_revision(self, workspace_id: str, revision: int) -> ModelPolicySnapshot | None:
        _scope("workspace_id", workspace_id)
        if type(revision) is not int or revision < 0:
            raise _err("invalid_model_policy_revision")
        if revision == 0:
            return ModelPolicySnapshot(workspace_id, 0, ())
        row = self._db.execute(
            "SELECT rules_json FROM model_policy_history WHERE workspace_id=? AND revision=?",
            (workspace_id, revision),
        ).fetchone()
        return _decode(workspace_id, revision, row[0]) if row else None

    def commit(self, *, workspace_id: str, expected_revision: int, nonce: str,
               actor_id: str, operation: str, changes: tuple[ModelChange, ...],
               now: datetime) -> ModelPolicySnapshot:
        _scope("workspace_id", workspace_id)
        _scope("actor_id", actor_id)
        if operation not in {"apply", "rollback"}:
            raise _err("model_policy_invalid_operation")
        when = _now(now)
        try:
            self._db.execute("BEGIN IMMEDIATE")
            consumed = self._db.execute(
                "SELECT 1 FROM model_policy_nonces WHERE workspace_id=? AND nonce=?",
                (workspace_id, nonce),
            ).fetchone()
            if consumed:
                raise _err("model_policy_receipt_replayed")
            row = self._db.execute(
                "SELECT revision, rules_json FROM model_policy_workspaces WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()
            current = (_decode(workspace_id, row[0], row[1]) if row
                       else ModelPolicySnapshot(workspace_id, 0, ()))
            if current.revision != expected_revision:
                raise _err("model_policy_revision_conflict")
            updated = _updated(current, changes)
            self._db.execute(
                "INSERT INTO model_policy_nonces(workspace_id,nonce) VALUES (?,?)",
                (workspace_id, nonce),
            )
            self._db.execute(
                "INSERT INTO model_policy_workspaces(workspace_id,revision,rules_json) "
                "VALUES (?,?,?) ON CONFLICT(workspace_id) DO UPDATE "
                "SET revision=excluded.revision,rules_json=excluded.rules_json",
                (workspace_id, updated.revision, _encode(updated.rules)),
            )
            self._db.execute(
                "INSERT INTO model_policy_history(workspace_id,revision,rules_json) VALUES (?,?,?)",
                (workspace_id, updated.revision, _encode(updated.rules)),
            )
            self._db.execute(
                "INSERT INTO model_policy_audit"
                "(workspace_id,revision,actor_id,operation,recorded_at,diff_json) "
                "VALUES (?,?,?,?,?,?)",
                (workspace_id, updated.revision, actor_id, operation,
                 when.isoformat(), _encode(changes)),
            )
            self._db.execute("COMMIT")
            return updated
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    def safe_audit(self, workspace_id: str) -> list[dict[str, object]]:
        _scope("workspace_id", workspace_id)
        rows = self._db.execute(
            "SELECT revision,actor_id,operation,recorded_at,diff_json FROM model_policy_audit "
            "WHERE workspace_id=? ORDER BY revision", (workspace_id,),
        ).fetchall()
        return [
            {"revision": rev, "actor": actor, "operation": op, "recorded_at": ts,
             "changes": json.loads(diff)}
            for rev, actor, op, ts, diff in rows
        ]
