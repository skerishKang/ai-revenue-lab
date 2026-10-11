"""#3580: durable, authenticated, bounded device→broker Office output bytes.

This is a staging store, NEVER a Drive uploader or an Office permission grant.
An existing canonical successful command and the authenticated device binding
are prerequisites for any write. Reads remain private Service Binding RPCs.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from padiem_control_plane.local_agent_broker import BrokerBindingState, BrokerCommandState
from local_agent_broker_sql_state import rows, row_value, rows_written, safe_ref

MAX_OFFICE_ARTIFACT_BYTES = 8 * 1024 * 1024
OFFICE_CHUNK_BYTES = 48 * 1024
_MAX_PARTS = math.ceil(MAX_OFFICE_ARTIFACT_BYTES / OFFICE_CHUNK_BYTES)
_SHA = re.compile(r"^[0-9a-f]{64}$")
_FILENAME = re.compile(r"^[^/\\\\\x00-\x1f\x7f]{1,160}$")
_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_agent_office_artifact (
 command_id TEXT NOT NULL, kind TEXT NOT NULL, artifact_id TEXT NOT NULL,
 binding_ref TEXT NOT NULL, account_ref TEXT NOT NULL, workspace_ref TEXT NOT NULL,
 run_id TEXT NOT NULL, filename TEXT NOT NULL, media_type TEXT NOT NULL,
 size_bytes INTEGER NOT NULL, integrity_ref TEXT NOT NULL, part_count INTEGER NOT NULL, verified INTEGER NOT NULL DEFAULT 0,
 expires_at TEXT NOT NULL,
 PRIMARY KEY(command_id, kind), UNIQUE(command_id, artifact_id)
);
CREATE TABLE IF NOT EXISTS local_agent_office_part (
 command_id TEXT NOT NULL, kind TEXT NOT NULL, part_index INTEGER NOT NULL,
 data_b64 TEXT NOT NULL, part_sha256 TEXT NOT NULL,
 PRIMARY KEY(command_id, kind, part_index)
);
"""
_WIRE = frozenset({
    "contract_version", "command_id", "run_id", "kind", "artifact_id",
    "filename", "media_type", "size_bytes", "integrity_ref",
    "part_index", "part_count", "part_sha256", "data_b64",
})


class OfficeChunkRefused(ValueError):
    """Caller-safe error; never render provider secrets or document data."""


def _digest(value: Any) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise OfficeChunkRefused("lowercase SHA-256 required")
    return value


def _bounded_int(value: Any, *, lo: int, hi: int) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise OfficeChunkRefused("bounded integer required")
    return value


class BrokerOfficeChunkStore:
    """SQLite Durable Object store. Exact replay is inert; conflicting replay fails."""

    def __init__(self, *, storage: Any, state_port: Any, authority_ref: str,
                 clock: Callable[[], datetime] | None = None):
        sql = getattr(storage, "sql", None)
        if sql is None or not callable(getattr(sql, "exec", None)):
            raise OfficeChunkRefused("durable SQLite storage required")
        self._sql = sql
        self._state = state_port
        self._authority = safe_ref(authority_ref, "authority_ref")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # Durable Object SQL.exec is statement-scoped, not executescript.
        for statement in _SCHEMA.split(";"):
            if statement.strip():
                self._sql.exec(statement)

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise OfficeChunkRefused("trusted timezone-aware clock required")
        return now.astimezone(timezone.utc)

    def _expire(self, now: datetime) -> None:
        cutoff = now.isoformat()
        self._sql.exec(
            "DELETE FROM local_agent_office_part WHERE command_id IN "
            "(SELECT command_id FROM local_agent_office_artifact WHERE expires_at<=?)",
            cutoff,
        )
        self._sql.exec(
            "DELETE FROM local_agent_office_artifact WHERE expires_at<=?", cutoff,
        )

    def _command(self, *, command_id: str, run_id: str, binding_ref: str,
                 owner: str, workspace: str) -> None:
        snapshot = self._state.load(authority_ref=self._authority).snapshot
        bindings = [b for b in snapshot.bindings
                    if b.binding_ref == binding_ref and b.account_ref == owner
                    and b.workspace_ref == workspace]
        commands = [c for c in snapshot.commands
                    if c.command_id == command_id and c.run_id == run_id
                    and c.binding_ref == binding_ref]
        if len(bindings) != 1 or len(commands) != 1:
            raise OfficeChunkRefused("canonical command/binding unavailable")
        command = commands[0]
        now = self._now()
        ack = command.acknowledged_at
        if (ack is None or ack < now - timedelta(days=1)
                or ack > now + timedelta(minutes=5)
                or bindings[0].credential_expires_at <= now
                or bindings[0].state is not BrokerBindingState.ACTIVE
                or command.credential_generation != bindings[0].credential_generation
                or command.state is not BrokerCommandState.ACKNOWLEDGED
                or command.termination != "exited" or command.exit_code != 0
                or not command.admission_ref or not command.evidence_ref):
            raise OfficeChunkRefused("successful admitted local execution required")

    def put(self, payload: dict, *, binding_ref: str, owner: str, workspace: str) -> dict:
        if type(payload) is not dict or frozenset(payload) != _WIRE:
            raise OfficeChunkRefused("Office chunk wire schema mismatch")
        if payload["contract_version"] != "claw-office-artifact-chunk.v1":
            raise OfficeChunkRefused("Office chunk wire version mismatch")
        command_id = safe_ref(payload["command_id"], "command_id")
        run_id = safe_ref(payload["run_id"], "run_id")
        artifact_id = safe_ref(payload["artifact_id"], "artifact_id")
        binding_ref = safe_ref(binding_ref, "binding_ref")
        owner = safe_ref(owner, "owner")
        workspace = safe_ref(workspace, "workspace")
        kind = payload["kind"]
        filename = payload["filename"]
        if (type(kind) is not str or kind not in _TYPES
                or type(filename) is not str or not _FILENAME.fullmatch(filename)
                or filename in (".", "..") or not filename.lower().endswith("."+kind)
                or payload["media_type"] != _TYPES[kind]):
            raise OfficeChunkRefused("Office output filename/media type invalid")
        total = _bounded_int(payload["size_bytes"], lo=1, hi=MAX_OFFICE_ARTIFACT_BYTES)
        count = _bounded_int(payload["part_count"], lo=1, hi=_MAX_PARTS)
        index = _bounded_int(payload["part_index"], lo=0, hi=count-1)
        if count != math.ceil(total / OFFICE_CHUNK_BYTES):
            raise OfficeChunkRefused("Office part count/size mismatch")
        whole_hash = _digest(payload["integrity_ref"])
        part_hash = _digest(payload["part_sha256"])
        value = payload["data_b64"]
        if type(value) is not str or len(value) > 4*math.ceil(OFFICE_CHUNK_BYTES/3):
            raise OfficeChunkRefused("Office part exceeds transfer bound")
        try:
            data = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            raise OfficeChunkRefused("Office part not valid base64") from None
        expected_length = min(OFFICE_CHUNK_BYTES, total - index*OFFICE_CHUNK_BYTES)
        if len(data) != expected_length or hashlib.sha256(data).hexdigest() != part_hash:
            raise OfficeChunkRefused("Office part integrity mismatch")
        canonical_b64 = base64.b64encode(data).decode("ascii")
        if value != canonical_b64:
            raise OfficeChunkRefused("noncanonical Office part encoding")

        # Bound lifetime prevents indefinite document retention in broker SQL.
        now = self._now()
        self._expire(now)
        # No user-controlled owner/workspace in wire; derived from authenticated
        # canonical device binding and revalidated from current broker state.
        self._command(command_id=command_id, run_id=run_id, binding_ref=binding_ref,
                      owner=owner, workspace=workspace)
        fields = (command_id, kind, artifact_id, binding_ref, owner, workspace,
                  run_id, filename, _TYPES[kind], total, whole_hash, count)
        inserted = self._sql.exec(
            "INSERT OR IGNORE INTO local_agent_office_artifact "
            "(command_id,kind,artifact_id,binding_ref,account_ref,workspace_ref,"
            "run_id,filename,media_type,size_bytes,integrity_ref,part_count,expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", *fields,
            (now + timedelta(days=1)).isoformat(),
        )
        rows_written(inserted)
        existing = rows(self._sql.exec(
            "SELECT command_id,kind,artifact_id,binding_ref,account_ref,workspace_ref,"
            "run_id,filename,media_type,size_bytes,integrity_ref,part_count "
            "FROM local_agent_office_artifact WHERE command_id=? AND kind=?",
            command_id, kind,
        ))
        if len(existing) != 1 or tuple(row_value(existing[0], k) for k in (
            "command_id","kind","artifact_id","binding_ref","account_ref",
            "workspace_ref","run_id","filename","media_type","size_bytes",
            "integrity_ref","part_count"
        )) != fields:
            raise OfficeChunkRefused("Office artifact manifest conflict")
        part = self._sql.exec(
            "INSERT OR IGNORE INTO local_agent_office_part "
            "(command_id,kind,part_index,data_b64,part_sha256) VALUES (?,?,?,?,?)",
            command_id, kind, index, canonical_b64, part_hash,
        )
        inserted_part = rows_written(part)
        existing_part = rows(self._sql.exec(
            "SELECT data_b64,part_sha256 FROM local_agent_office_part "
            "WHERE command_id=? AND kind=? AND part_index=?",
            command_id, kind, index,
        ))
        if (len(existing_part) != 1
                or row_value(existing_part[0], "data_b64") != canonical_b64
                or row_value(existing_part[0], "part_sha256") != part_hash):
            raise OfficeChunkRefused("Office artifact part replay conflict")
        return {"stored": True, "reused": inserted_part == 0,
                "kind": kind, "part_index": index, "raw_bytes_present": False}

    def read_part(self, *, owner: str, workspace: str, run_id: str,
                  command_id: str, kind: str, part_index: int) -> dict:
        """PRIVATE RPC only. Never return content through a public device route."""
        owner, workspace, run_id, command_id = (
            safe_ref(owner, "owner"), safe_ref(workspace, "workspace"),
            safe_ref(run_id, "run_id"), safe_ref(command_id, "command_id"),
        )
        if type(kind) is not str or kind not in _TYPES:
            raise OfficeChunkRefused("unsupported Office output kind")
        index = _bounded_int(part_index, lo=0, hi=_MAX_PARTS-1)
        self._expire(self._now())
        result = rows(self._sql.exec(
            "SELECT artifact_id,binding_ref,filename,media_type,size_bytes,"
            "integrity_ref,part_count,verified FROM local_agent_office_artifact "
            "WHERE command_id=? AND kind=? AND account_ref=? "
            "AND workspace_ref=? AND run_id=?",
            command_id, kind, owner, workspace, run_id,
        ))
        if len(result) != 1:
            raise OfficeChunkRefused("authorized Office manifest unavailable")
        item = result[0]
        count = row_value(item, "part_count")
        if index >= count:
            raise OfficeChunkRefused("Office part index out of range")
        # This checks current binding and successful command even for private
        # read, so revoked/compacted authority fails closed, never serves bytes.
        self._command(command_id=command_id, run_id=run_id,
                      binding_ref=row_value(item, "binding_ref"),
                      owner=owner, workspace=workspace)
        # Validate the full stream ONCE before any read. Parts are immutable:
        # exact replay is a no-op and conflicts never overwrite stored rows.
        # Caching verification in SQLite avoids 171 x 8MiB re-hashing.
        if row_value(item, "verified") != 1:
            parts = rows(self._sql.exec(
                "SELECT part_index,data_b64,part_sha256 FROM local_agent_office_part "
                "WHERE command_id=? AND kind=? ORDER BY part_index",
                command_id, kind,
            ))
            if len(parts) != count or any(
                row_value(part, "part_index") != i
                for i, part in enumerate(parts)
            ):
                raise OfficeChunkRefused("incomplete Office artifact, no partial reads")
            digest = hashlib.sha256()
            size = 0
            first = b""
            tail = b""
            for i, part in enumerate(parts):
                try:
                    data = base64.b64decode(row_value(part, "data_b64"), validate=True)
                except (ValueError, binascii.Error):
                    raise OfficeChunkRefused("corrupted Office part encoding") from None
                expected = min(OFFICE_CHUNK_BYTES, row_value(item, "size_bytes") - i*OFFICE_CHUNK_BYTES)
                if len(data) != expected or hashlib.sha256(data).hexdigest() != row_value(part, "part_sha256"):
                    raise OfficeChunkRefused("stored Office part changed")
                if i == 0:
                    first = data[:8]
                tail = (tail + data)[-1024:]
                digest.update(data)
                size += len(data)
            if (size != row_value(item, "size_bytes")
                    or digest.hexdigest() != row_value(item, "integrity_ref")):
                raise OfficeChunkRefused("Office output total digest mismatch")
            if ((kind == "pdf" and (not first.startswith(b"%PDF-") or b"%%EOF" not in tail))
                    or (kind == "xlsx" and not first.startswith(b"PK\x03\x04"))):
                raise OfficeChunkRefused("Office binary signature not supported")
            self._sql.exec(
                "UPDATE local_agent_office_artifact SET verified=1 "
                "WHERE command_id=? AND kind=? AND verified=0",
                command_id, kind,
            )
        selected_rows = rows(self._sql.exec(
            "SELECT data_b64,part_sha256 FROM local_agent_office_part "
            "WHERE command_id=? AND kind=? AND part_index=?",
            command_id, kind, index,
        ))
        if len(selected_rows) != 1:
            raise OfficeChunkRefused("Office part unavailable")
        selected = selected_rows[0]
        try:
            selected_bytes = base64.b64decode(row_value(selected, "data_b64"), validate=True)
        except (ValueError, binascii.Error):
            raise OfficeChunkRefused("Office part encoding changed") from None
        if hashlib.sha256(selected_bytes).hexdigest() != row_value(selected, "part_sha256"):
            raise OfficeChunkRefused("Office part digest changed")
        size = row_value(item, "size_bytes")
        digest_ref = row_value(item, "integrity_ref")
        return {
            "contract_version": "claw-office-artifact-read.v1",
            "artifact_id": row_value(item, "artifact_id"),
            "filename": row_value(item, "filename"),
            "media_type": row_value(item, "media_type"),
            "size_bytes": size,
            "integrity_ref": digest_ref,
            "part_index": index, "part_count": count,
            "data_b64": row_value(selected, "data_b64"),
        }

    def purge_binding(self, binding_ref: str) -> None:
        binding_ref = safe_ref(binding_ref, "binding_ref")
        self._sql.exec(
            "DELETE FROM local_agent_office_part WHERE command_id IN "
            "(SELECT command_id FROM local_agent_office_artifact WHERE binding_ref=?)",
            binding_ref,
        )
        self._sql.exec(
            "DELETE FROM local_agent_office_artifact WHERE binding_ref=?", binding_ref,
        )


PRODUCTION_OFFICE_TRANSFER_ENABLED = False


def compose_broker_office_chunks(*, storage: Any, state_port: Any,
                                 authority_ref: str, env: Any):
    """Feature-off by default; never infer WRITE grant from broker pairing."""
    if str(getattr(env, "LOCAL_AGENT_OFFICE_CHUNK_TRANSFER_ENABLED", "")).lower() != "true":
        return None
    return BrokerOfficeChunkStore(
        storage=storage, state_port=state_port, authority_ref=authority_ref,
    )


def read_broker_office_part_rpc(store: BrokerOfficeChunkStore | None,
                                 payload: dict) -> dict:
    """PRIVATE Service Binding only, never a public device HTTP route."""
    if store is None or type(payload) is not dict:
        return {"ok": False, "error": {"code": "office_transfer_not_configured"}}
    try:
        fields = frozenset({
            "owner", "workspace", "run_id", "command_id", "kind", "part_index",
        })
        if frozenset(payload) != fields:
            raise OfficeChunkRefused("closed private Office reader contract required")
        return {"ok": True, "artifact_part": store.read_part(**payload)}
    except Exception:
        return {"ok": False, "error": {"code": "office_artifact_unavailable"}}
