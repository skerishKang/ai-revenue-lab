"""#4139 — the canonical broker's durable, verified Windows TXT result store.

The first PC file read (#4139) has to return *real* contents into the Claw
conversation that started the run. The consumer contract already exists in
``apps/padiem-chat/app/claw_local_task_result_{projection,composition}.py``
(#4687 / #4690 / #4693): the Claw asks the canonical broker, over the private
Service Binding, for one *verified* file-read receipt and accepts only a full,
correlated, hash-checked payload. An ordinary acknowledgement cannot carry the
body, arbitrary device stdout is never trusted, and no fixture may stand in for
a real read.

This module is the missing broker half. It adds exactly one durable table and
two operations on it:

* ``submit`` — the device-facing *receipt* write behind the new canonical
  ``/file-result`` route. The device states what its execution produced
  (``file_read_text`` with the real content, or ``other`` for a command that is
  not a text-file read) together with the exact command correlation it already
  holds. Every correlation value is checked against the **canonical persisted
  command record**, never taken from the caller, and the command's own lifecycle
  gates the write: only a command that was admitted (and, once acknowledged,
  only one whose bounded outcome is ``exited`` with exit code ``0``) can carry
  file text.
* ``read_verified_file_text`` — the read-only private RPC the Claw consumes. It
  answers exactly one of the three contract shapes: a full verified receipt, a
  *pending* text-file result, or ``other``. It is owner/workspace scoped from
  the canonical binding state, refuses any command whose canonical outcome is
  not a successful execution, and fails closed on any correlation or integrity
  disagreement.

No new authority is created: the device credential, the session, the lifecycle
state, the sequence and the fingerprint all stay with the canonical broker.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from padiem_control_plane.local_agent_broker import BrokerCommandState
from padiem_control_plane.local_agent_broker_state_wire import SerializedLocalAgentBrokerStatePort

from local_agent_broker_sql_state import iso, parse_iso, positive_int, row_value, rows, rows_written, safe_ref

#: The consumer's own bound: the first synthetic TXT only (768 bytes). The
#: broker refuses anything larger rather than letting a payload that the Claw
#: will reject reach durable storage.
MAX_VERIFIED_FILE_RESULT_BYTES = 768

#: Bounded retention: receipts are small, but the table is pruned oldest-first
#: so an unbounded command history can never grow the Durable Object without
#: limit. Pruning is explicit and never silent about a *live* row: it removes
#: the least recently stored receipts for commands that are already terminal.
MAX_VERIFIED_FILE_RESULT_ROWS = 512

FILE_RESULT_KIND_TEXT = "file_read_text"
FILE_RESULT_KIND_OTHER = "other"
_FILE_RESULT_KINDS = (FILE_RESULT_KIND_TEXT, FILE_RESULT_KIND_OTHER)

_SUBMISSION_KEYS = frozenset(
    {
        "command_id",
        "revision_ref",
        "request_id",
        "evidence_ref",
        "kind",
        "content_utf8",
        "content_sha256",
    }
)
#: #4687 — the exact Claw-facing receipt key set. `verify_broker_file_text`
#: accepts this and nothing else, so the projection below is closed.
_READ_REQUEST_KEYS = frozenset({"account_ref", "workspace_ref", "run_id", "command_id"})
RECEIPT_FIELDS = (
    "ok",
    "available",
    "kind",
    "account_ref",
    "workspace_ref",
    "run_id",
    "command_id",
    "tool_request_ref",
    "request_id",
    "revision_ref",
    "evidence_ref",
    "request_fingerprint",
    "content_utf8",
    "content_sha256",
)

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

_VERIFIED_FILE_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_agent_verified_file_results (
    command_id TEXT PRIMARY KEY,
    binding_ref TEXT NOT NULL,
    account_ref TEXT NOT NULL,
    workspace_ref TEXT NOT NULL,
    run_id TEXT NOT NULL,
    tool_request_ref TEXT NOT NULL,
    request_id TEXT NOT NULL,
    revision_ref TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    kind TEXT NOT NULL CHECK (kind IN ('file_read_text', 'other')),
    content_utf8 TEXT,
    content_sha256 TEXT,
    content_bytes INTEGER,
    stored_at TEXT NOT NULL
)
"""

_ROW_COLUMNS = (
    "command_id, binding_ref, account_ref, workspace_ref, run_id, tool_request_ref, "
    "request_id, revision_ref, evidence_ref, request_fingerprint, sequence, kind, "
    "content_utf8, content_sha256, content_bytes, stored_at"
)


def _closed_mapping(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != keys:
        raise ValueError(f"{label} schema mismatch")
    return value


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a bounded safe reference")
    return value


def _digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _content_byte_length(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > MAX_VERIFIED_FILE_RESULT_BYTES:
        raise ValueError("file result content byte length is invalid")
    return value


def _content_digest(content_utf8: str, *, label: str = "file result content") -> tuple[str, int]:
    """Validate one text-file body exactly as the Claw consumer will."""

    try:
        raw = content_utf8.encode("utf-8")
    except UnicodeEncodeError as exc:  # pragma: no cover - defensive
        raise ValueError(f"{label} must be valid UTF-8") from exc
    if len(raw) > MAX_VERIFIED_FILE_RESULT_BYTES:
        raise ValueError(f"{label} exceeds the bounded text size")
    if any(ord(character) < 32 and character not in "\n\r\t" for character in content_utf8):
        raise ValueError(f"{label} must not contain control characters")
    return hashlib.sha256(raw).hexdigest(), len(raw)


class CloudflareDurableObjectVerifiedFileResultStore:
    """Durable, bounded, correlation-checked store for verified Windows TXT results."""

    durable = True

    def __init__(self, storage: Any, *, state_port: SerializedLocalAgentBrokerStatePort, authority_ref: str) -> None:
        sql = getattr(storage, "sql", None)
        if sql is None or not callable(getattr(sql, "exec", None)):
            raise ValueError("SQLite-backed Durable Object storage is required")
        if not isinstance(state_port, SerializedLocalAgentBrokerStatePort):
            raise ValueError("state_port must be SerializedLocalAgentBrokerStatePort")
        self._sql = sql
        self._state_port = state_port
        self._authority_ref = safe_ref(authority_ref, "authority_ref")
        self._sql.exec(_VERIFIED_FILE_SCHEMA)

    # -- canonical reads -------------------------------------------------

    def _commands(self) -> tuple[Any, ...]:
        return tuple(self._state_port.load(authority_ref=self._authority_ref).snapshot.commands)

    def _command(self, command_id: str) -> Any | None:
        matches = [item for item in self._commands() if item.command_id == command_id]
        if len(matches) > 1:
            raise RuntimeError("verified file result command lookup was ambiguous")
        return matches[0] if matches else None

    def _scoped_binding_refs(self, account_ref: str, workspace_ref: str | None) -> frozenset[str]:
        snapshot = self._state_port.load(authority_ref=self._authority_ref).snapshot
        return frozenset(
            binding.binding_ref
            for binding in snapshot.bindings
            if binding.account_ref == account_ref
            and (workspace_ref is None or binding.workspace_ref == workspace_ref)
        )

    def _row(self, command_id: str) -> Any | None:
        found = rows(
            self._sql.exec(
                f"SELECT {_ROW_COLUMNS} FROM local_agent_verified_file_results WHERE command_id = ?",
                safe_ref(command_id, "command_id"),
            )
        )
        if len(found) > 1:
            raise RuntimeError("verified file result lookup was ambiguous")
        return found[0] if found else None

    def _prune(self) -> int:
        excess = rows(
            self._sql.exec(
                "SELECT command_id FROM local_agent_verified_file_results ORDER BY stored_at ASC, command_id ASC"
            )
        )[MAX_VERIFIED_FILE_RESULT_ROWS :]
        if not excess:
            return 0
        return rows_written(
            self._sql.exec(
                "DELETE FROM local_agent_verified_file_results WHERE command_id = ?",
                *[row_value(row, "command_id") for row in excess],
            )
        )

    def _projection(self, row: Any, *, reused: bool = False) -> dict[str, Any]:
        content_bytes = row_value(row, "content_bytes")
        return {
            "stored": True,
            "reused": reused,
            "command_id": safe_ref(row_value(row, "command_id"), "command_id"),
            "binding_ref": safe_ref(row_value(row, "binding_ref"), "binding_ref"),
            "kind": row_value(row, "kind"),
            "content_bytes": None if content_bytes is None else _content_byte_length(int(content_bytes)),
            "content_sha256": row_value(row, "content_sha256"),
            "stored_at": row_value(row, "stored_at"),
            "raw_device_credential": False,
        }

    # -- device-facing write ---------------------------------------------

    def submit(
        self,
        submission: Any,
        *,
        binding_ref: str,
        account_ref: str,
        workspace_ref: str,
        now: datetime,
    ) -> dict[str, Any]:
        """Record one device's bounded execution result for one exact command.

        `binding_ref` / `account_ref` / `workspace_ref` are the *verified*
        device identity the device HTTP boundary already derived from the
        device credential and its durable session. Nothing in `submission`
        can widen them.
        """

        binding_ref = safe_ref(binding_ref, "binding_ref")
        account_ref = safe_ref(account_ref, "account_ref")
        workspace_ref = safe_ref(workspace_ref, "workspace_ref")
        stored_at = iso(now)
        submission = _closed_mapping(submission, _SUBMISSION_KEYS, "verified file result submission")
        command_id = safe_ref(submission["command_id"], "command_id")
        revision_ref = _ref(submission["revision_ref"], "revision_ref")
        request_id = _ref(submission["request_id"], "request_id")
        evidence_ref = _ref(submission["evidence_ref"], "evidence_ref")
        kind = submission["kind"]
        if kind not in _FILE_RESULT_KINDS:
            raise ValueError("verified file result kind must be file_read_text or other")

        content_utf8 = submission["content_utf8"]
        content_sha256 = submission["content_sha256"]
        if content_utf8 is None:
            if content_sha256 is not None:
                raise ValueError("a pending file result declaration must not carry a content digest")
            digest: str | None = None
            content_bytes: int | None = None
        else:
            if kind != FILE_RESULT_KIND_TEXT:
                raise ValueError("only a text-file read result may carry content")
            if type(content_utf8) is not str:
                raise ValueError("file result content must be text")
            digest, content_bytes = _content_digest(content_utf8)
            if _digest(content_sha256, "content_sha256") != digest:
                raise ValueError("file result content digest mismatch")

        command = self._command(command_id)
        if command is None:
            raise ValueError("verified file result requires an exact canonical command")
        if command.binding_ref != binding_ref:
            raise PermissionError("verified file result command belongs to another device binding")
        if command.state not in {BrokerCommandState.ADMITTED, BrokerCommandState.ACKNOWLEDGED}:
            raise ValueError("verified file result requires an admitted or acknowledged command")
        if command.revision_ref != revision_ref:
            raise ValueError("verified file result revision_ref mismatch")
        if command.request_id != request_id:
            raise ValueError("verified file result request_id mismatch")
        if command.evidence_ref != evidence_ref:
            raise ValueError("verified file result evidence_ref mismatch")
        if command.state is BrokerCommandState.ACKNOWLEDGED and content_utf8 is not None:
            # The canonical record is the only authority on whether the
            # execution succeeded. File text can never be attached to a failed,
            # cancelled or timed-out command.
            if command.termination != "exited" or command.exit_code != 0:
                raise ValueError("verified file result requires a successful acknowledged execution")

        existing = self._row(command_id)
        if existing is not None:
            return self._reuse_existing(
                existing,
                kind=kind,
                content_utf8=content_utf8,
                digest=digest,
                binding_ref=binding_ref,
                revision_ref=revision_ref,
                request_id=request_id,
                evidence_ref=evidence_ref,
                account_ref=account_ref,
                workspace_ref=workspace_ref,
                stored_at=stored_at,
            )

        self._sql.exec(
            "INSERT INTO local_agent_verified_file_results "
            f"({_ROW_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            command_id,
            binding_ref,
            account_ref,
            workspace_ref,
            command.run_id,
            command.tool_request_ref,
            request_id,
            revision_ref,
            evidence_ref,
            command.request_fingerprint,
            command.sequence,
            kind,
            content_utf8,
            digest,
            content_bytes,
            stored_at,
        )
        self._prune()
        row = self._row(command_id)
        if row is None:
            raise RuntimeError("verified file result write did not persist")
        return self._projection(row)

    def _reuse_existing(
        self,
        existing: Any,
        *,
        kind: str,
        content_utf8: str | None,
        digest: str | None,
        binding_ref: str,
        revision_ref: str,
        request_id: str,
        evidence_ref: str,
        account_ref: str,
        workspace_ref: str,
        stored_at: str,
    ) -> dict[str, Any]:
        """Idempotent exact retry, or the one allowed transition: pending -> text."""

        same_correlation = all(
            row_value(existing, field) == expected
            for field, expected in (
                ("binding_ref", binding_ref),
                ("account_ref", account_ref),
                ("workspace_ref", workspace_ref),
                ("revision_ref", revision_ref),
                ("request_id", request_id),
                ("evidence_ref", evidence_ref),
            )
        )
        if not same_correlation:
            raise ValueError("verified file result correlation changed for this command")
        existing_kind = row_value(existing, "kind")
        if existing_kind != kind:
            raise ValueError("verified file result kind changed for this command")
        existing_content = row_value(existing, "content_utf8")
        if existing_content is not None:
            if existing_content != content_utf8 or row_value(existing, "content_sha256") != digest:
                raise ValueError("verified file result content changed for this command")
            return self._projection(existing, reused=True)
        if content_utf8 is None:
            return self._projection(existing, reused=True)
        # pending -> text: the only permitted upgrade, and only for the same
        # exact command, binding and correlation.
        written = rows_written(
            self._sql.exec(
                "UPDATE local_agent_verified_file_results SET content_utf8 = ?, content_sha256 = ?, "
                "content_bytes = ?, stored_at = ? WHERE command_id = ? AND content_utf8 IS NULL",
                content_utf8,
                digest,
                len(content_utf8.encode("utf-8")),
                stored_at,
                row_value(existing, "command_id"),
            )
        )
        row = self._row(row_value(existing, "command_id"))
        if row is None or written != 1:
            raise RuntimeError("verified file result upgrade did not persist")
        return self._projection(row)

    # -- private read-only RPC -------------------------------------------

    def read_verified_file_text(self, payload: Any) -> dict[str, Any]:
        """The canonical broker's answer to the Claw file-text read (#4687)."""

        try:
            payload = _closed_mapping(payload, _READ_REQUEST_KEYS, "verified file text request")
            account_ref = safe_ref(payload["account_ref"], "account_ref")
            workspace_ref = safe_ref(payload["workspace_ref"], "workspace_ref")
            run_id = safe_ref(payload["run_id"], "run_id")
            command_id = safe_ref(payload["command_id"], "command_id")
        except (KeyError, TypeError, ValueError):
            return {
                "ok": False,
                "error": {
                    "code": "invalid_verified_file_result_request",
                    "message": "verified file result request was rejected",
                },
            }

        try:
            command = self._command(command_id)
        except RuntimeError:
            command = None
        if command is None or command.run_id != run_id:
            return {
                "ok": False,
                "error": {
                    "code": "verified_file_result_not_found",
                    "message": "verified file result command was not found",
                },
            }
        if command.binding_ref not in self._scoped_binding_refs(account_ref, workspace_ref):
            # Never distinguishes "another owner's command" from "unknown":
            # the same bounded refusal covers both.
            return {
                "ok": False,
                "error": {
                    "code": "verified_file_result_not_found",
                    "message": "verified file result command was not found",
                },
            }
        if command.state is not BrokerCommandState.ACKNOWLEDGED or command.termination != "exited" or command.exit_code != 0:
            # The Claw only asks for a successful execution. Anything else here
            # means the canonical fact moved; refuse instead of inventing a
            # result for a command that did not succeed.
            return {
                "ok": False,
                "error": {
                    "code": "verified_file_result_not_successful",
                    "message": "verified file result requires a successful acknowledged execution",
                },
            }

        row = self._row(command_id)
        if row is None or row_value(row, "kind") == FILE_RESULT_KIND_OTHER:
            # No verified text was submitted for this command. That is the
            # legacy terminal-only answer: the Claw appends its normal result
            # message and no message slot is held open.
            return {"ok": True, "available": False, "kind": FILE_RESULT_KIND_OTHER}
        if row_value(row, "content_utf8") is None:
            return {"ok": True, "available": False, "kind": FILE_RESULT_KIND_TEXT}

        canonical = (
            command.command_id,
            command.run_id,
            command.tool_request_ref,
            command.request_id,
            command.revision_ref,
            command.evidence_ref,
            command.request_fingerprint,
        )
        stored = (
            row_value(row, "command_id"),
            row_value(row, "run_id"),
            row_value(row, "tool_request_ref"),
            row_value(row, "request_id"),
            row_value(row, "revision_ref"),
            row_value(row, "evidence_ref"),
            row_value(row, "request_fingerprint"),
        )
        if stored != canonical or row_value(row, "binding_ref") != command.binding_ref:
            return {
                "ok": False,
                "error": {
                    "code": "verified_file_result_correlation_mismatch",
                    "message": "verified file result correlation was refused",
                },
            }
        content_utf8 = row_value(row, "content_utf8")
        if type(content_utf8) is not str:
            return {
                "ok": False,
                "error": {
                    "code": "verified_file_result_integrity_invalid",
                    "message": "verified file result integrity was refused",
                },
            }
        try:
            digest, content_bytes = _content_digest(content_utf8)
        except ValueError:
            return {
                "ok": False,
                "error": {
                    "code": "verified_file_result_integrity_invalid",
                    "message": "verified file result integrity was refused",
                },
            }
        if (
            _digest(row_value(row, "content_sha256"), "content_sha256") != digest
            or _content_byte_length(int(row_value(row, "content_bytes"))) != content_bytes
        ):
            return {
                "ok": False,
                "error": {
                    "code": "verified_file_result_integrity_invalid",
                    "message": "verified file result integrity was refused",
                },
            }
        receipt = {
            "ok": True,
            "available": True,
            "kind": FILE_RESULT_KIND_TEXT,
            "account_ref": account_ref,
            "workspace_ref": workspace_ref,
            "run_id": canonical[1],
            "command_id": canonical[0],
            "tool_request_ref": canonical[2],
            "request_id": canonical[3],
            "revision_ref": canonical[4],
            "evidence_ref": canonical[5],
            "request_fingerprint": canonical[6],
            "content_utf8": content_utf8,
            "content_sha256": digest,
        }
        if frozenset(receipt) != frozenset(RECEIPT_FIELDS):
            raise RuntimeError("verified file result receipt schema drifted")
        return receipt

    # -- lifecycle purges -------------------------------------------------

    def purge_command(self, command_id: str) -> int:
        return rows_written(
            self._sql.exec(
                "DELETE FROM local_agent_verified_file_results WHERE command_id = ?",
                safe_ref(command_id, "command_id"),
            )
        )

    def purge_binding(self, binding_ref: str) -> int:
        return rows_written(
            self._sql.exec(
                "DELETE FROM local_agent_verified_file_results WHERE binding_ref = ?",
                safe_ref(binding_ref, "binding_ref"),
            )
        )

    def has_stored_result(self, command_id: str) -> bool:
        return self._row(safe_ref(command_id, "command_id")) is not None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "durable": True,
            "separate_verified_file_result_table": True,
            "canonical_command_correlation_reused": True,
            "caller_supplied_correlation_authority": False,
            "receipt_schema": FILE_RESULT_RECEIPT_CONTRACT,
            "max_content_bytes": MAX_VERIFIED_FILE_RESULT_BYTES,
            "max_rows": MAX_VERIFIED_FILE_RESULT_ROWS,
            "raw_device_credential_persisted": False,
            "raw_stdout_persisted": False,
            "production_deployment": False,
        }


FILE_RESULT_RECEIPT_CONTRACT = "canonical_broker_file_text_v1"
FILE_RESULT_ROUTE = "/file-result"
VERIFIED_FILE_RESULT_STORE_SEPARATED = True
VERIFIED_FILE_RESULT_FROM_CANONICAL_COMMAND = True
VERIFIED_FILE_RESULT_REQUIRES_SUCCESSFUL_EXECUTION = True
SECOND_COMMAND_AUTHORITY = False
SECOND_BROKER_STATE_AUTHORITY = False
RAW_STDOUT_TRUSTED = False
ACK_BODY_CARRIES_FILE_TEXT = False
FIXTURE_STANDIN_ALLOWED = False
