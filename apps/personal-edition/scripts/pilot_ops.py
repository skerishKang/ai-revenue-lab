#!/usr/bin/env python3
"""Pilot operations recording for Personal Edition.

Provides typed per-record validation, sensitive-value detection,
payment-evidence restrictions, export pseudonymization, and a
deletion workflow.

Usage:
    python -m scripts.pilot_ops record --type benchmark_run --db PATH --data JSON
    python -m scripts.pilot_ops delete --participant-id ID [--db PATH]
    python -m scripts.pilot_ops export-evidence --db PATH [--export-safe]
    python -m scripts.pilot_ops update-correction --run-id ID --minutes N [--db PATH]
    python -m scripts.pilot_ops list-records [--type TYPE] [--db PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DIR))

from app import participant_repository as pt_repo
from app.db_runtime import SqliteRuntimeConnection
from app.config import Settings
from app.db import apply_migrations, get_connection

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PILOT_OPS_TABLE = "pilot_ops_records"
_MAX_DESCRIPTION_LENGTH = 2000
_MAX_NOTES_LENGTH = 5000
_MAX_EVIDENCE_DESCRIPTION_LENGTH = 3000

_PRIVATE_FIELDS = frozenset({
    "notes",
    "feedback_text",
    "evidence_description",
    "reviewer_notes",
    "private_notes",
})


# ---------------------------------------------------------------------------
# Sensitive value detection
# ---------------------------------------------------------------------------

_SSN_PATTERN = re.compile(
    r"\b\d{6}[-\s]?\d{7}\b"
)
_CARD_NUMBER_PATTERN = re.compile(
    r"\b(?:\d[ -]*?){13,19}\b"
)
_ACCOUNT_NUMBER_PATTERN = re.compile(
    r"\b(?:account|acct)[\s:#-]*\d{6,18}\b", re.IGNORECASE
)
_API_KEY_PATTERN = re.compile(
    r"\b(?:api[_-]?key|secret[_-]?key|token|password|passwd|pwd)"
    r"[\s:=]+\S{8,}", re.IGNORECASE
)
_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
_PHONE_PATTERN = re.compile(
    r"\b(?:\+?[\d]{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b"
)
_KOREAN_NAME_PATTERN = re.compile(
    r"\b[가-힣]{2,4}\s[가-힣]{2,4}\b"
)
_FILE_PATH_PATTERN = re.compile(
    r"(?:/[\w.-]+){2,}|(?:[A-Za-z]:\\[\w\\.-]+)", re.IGNORECASE
)


class SensitiveMatch(BaseModel):
    category: str
    start: int
    end: int
    redacted: str


def detect_sensitive_values(text: str) -> list[SensitiveMatch]:
    if not isinstance(text, str) or not text:
        return []

    matches: list[SensitiveMatch] = []

    patterns: list[tuple[str, re.Pattern[str], str]] = [
        ("resident_registration", _SSN_PATTERN, "[REDACTED-SSN]"),
        ("card_number", _CARD_NUMBER_PATTERN, "[REDACTED-CARD]"),
        ("account_number", _ACCOUNT_NUMBER_PATTERN, "[REDACTED-ACCOUNT]"),
        ("api_key_or_token", _API_KEY_PATTERN, "[REDACTED-SECRET]"),
        ("email", _EMAIL_PATTERN, "[REDACTED-EMAIL]"),
        ("phone_number", _PHONE_PATTERN, "[REDACTED-PHONE]"),
        ("file_path", _FILE_PATH_PATTERN, "[REDACTED-PATH]"),
    ]

    for category, pattern, replacement in patterns:
        for m in pattern.finditer(text):
            matches.append(
                SensitiveMatch(
                    category=category,
                    start=m.start(),
                    end=m.end(),
                    redacted=replacement,
                )
            )

    return matches


def reject_or_redact_sensitive(
    text: str,
    *,
    reject: bool = True,
    field_name: str = "value",
) -> str:
    if not isinstance(text, str) or not text:
        return text

    matches = detect_sensitive_values(text)
    if not matches:
        return text

    reject_categories = {
        "resident_registration",
        "card_number",
        "account_number",
        "api_key_or_token",
    }

    if reject:
        rejected = [m for m in matches if m.category in reject_categories]
        if rejected:
            cats = sorted({m.category for m in rejected})
            raise ValueError(
                f"Sensitive value detected in '{field_name}': {', '.join(cats)}"
            )

    redacted = text
    for m in sorted(matches, key=lambda x: x.start, reverse=True):
        redacted = redacted[: m.start] + m.redacted + redacted[m.end :]
    return redacted


def check_forbidden_keys(data: dict[str, Any], depth: int = 0) -> list[str]:
    if depth > 10:
        return []

    forbidden_keys = {
        "access_token",
        "access_token_hash",
        "one_time_token",
        "raw_token",
        "password",
        "secret",
        "api_key",
        "secret_key",
        "admin_secret",
    }

    violations: list[str] = []
    for key, value in data.items():
        if key in forbidden_keys:
            violations.append(f"forbidden key '{key}' at depth {depth}")
        if isinstance(value, dict):
            violations.extend(check_forbidden_keys(value, depth + 1))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    violations.extend(check_forbidden_keys(item, depth + 1))
    return violations


# ---------------------------------------------------------------------------
# Record type enum
# ---------------------------------------------------------------------------


class PilotRecordType(StrEnum):
    BENCHMARK_RUN = "benchmark_run"
    PILOT_RUN = "pilot_run"
    PILOT_EVIDENCE = "pilot_evidence"
    PAYMENT_EVIDENCE = "payment_evidence"
    CORRECTION = "correction"
    DELETION_REQUEST = "deletion_request"
    DELETION_COMPLETION = "deletion_completion"


# ---------------------------------------------------------------------------
# Base record model
# ---------------------------------------------------------------------------

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SafeStr = Annotated[str, StringConstraints(max_length=_MAX_DESCRIPTION_LENGTH)]


class PilotRecord(BaseModel):
    record_type: PilotRecordType
    participant_id: str = Field(min_length=1)
    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=lambda: _now_utc_iso())
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("participant_id")
    @classmethod
    def validate_participant_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("participant_id must not be blank")
        if v != v.strip():
            raise ValueError(
                "participant_id must not contain leading or trailing whitespace"
            )
        return v

    @model_validator(mode="after")
    def check_forbidden_keys_recursive(self) -> "PilotRecord":
        violations = check_forbidden_keys(self.data)
        if violations:
            raise ValueError(
                "Forbidden keys detected: " + "; ".join(violations)
            )
        return self


# ---------------------------------------------------------------------------
# Specific record models
# ---------------------------------------------------------------------------


class BenchmarkRunRecord(PilotRecord):
    record_type: PilotRecordType = PilotRecordType.BENCHMARK_RUN

    benchmark_name: NonEmptyStr
    fixture_name: NonEmptyStr
    run_group: NonEmptyStr = "default"
    run_index: int = Field(ge=0)
    provider: NonEmptyStr
    advertised_model: NonEmptyStr
    task_type: NonEmptyStr
    prompt_version: str | None = None
    started_at: NonEmptyStr
    completed_at: str | None = None
    latency_seconds: float = Field(default=0.0, ge=0.0)
    success: bool = False
    failure_category: str | None = None
    error_category: str | None = None
    error_message: str | None = None
    retry_count: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    validation_result: str = "pending"
    synthetic_result_ref: str | None = None
    human_correction_minutes: float | None = Field(
        default=None, ge=0.0
    )

    @model_validator(mode="after")
    def check_sensitive_fields(self) -> "BenchmarkRunRecord":
        for field_name in ("error_message", "synthetic_result_ref"):
            val = getattr(self, field_name, None)
            if isinstance(val, str) and val:
                object.__setattr__(
                    self,
                    field_name,
                    reject_or_redact_sensitive(
                        val, reject=False, field_name=field_name
                    ),
                )
        return self


class PilotRunRecord(PilotRecord):
    record_type: PilotRecordType = PilotRecordType.PILOT_RUN

    task_type: NonEmptyStr
    provider: NonEmptyStr
    advertised_model: NonEmptyStr
    started_at: NonEmptyStr
    completed_at: str | None = None
    latency_seconds: float = Field(default=0.0, ge=0.0)
    success: bool = False
    failure_category: str | None = None
    error_category: str | None = None
    error_message: str | None = None
    retry_count: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    validation_result: str = "pending"
    notes: str | None = None

    @model_validator(mode="after")
    def check_sensitive_fields(self) -> "PilotRunRecord":
        for field_name in ("error_message", "notes"):
            val = getattr(self, field_name, None)
            if isinstance(val, str) and val:
                if field_name == "notes":
                    object.__setattr__(
                        self,
                        field_name,
                        reject_or_redact_sensitive(
                            val, reject=False, field_name=field_name
                        ),
                    )
                else:
                    object.__setattr__(
                        self,
                        field_name,
                        reject_or_redact_sensitive(
                            val, reject=False, field_name=field_name
                        ),
                    )
        return self


class PilotEvidenceRecord(PilotRecord):
    record_type: PilotRecordType = PilotRecordType.PILOT_EVIDENCE

    evidence_type: NonEmptyStr
    evidence_description: str | None = None
    source_ref: str | None = None
    private_notes: str | None = None
    exported: bool = False

    @model_validator(mode="after")
    def check_sensitive_fields(self) -> "PilotEvidenceRecord":
        for field_name in ("evidence_description", "private_notes"):
            val = getattr(self, field_name, None)
            if isinstance(val, str) and val:
                object.__setattr__(
                    self,
                    field_name,
                    reject_or_redact_sensitive(
                        val, reject=False, field_name=field_name
                    ),
                )
        return self


class PaymentEvidenceRecord(PilotRecord):
    record_type: PilotRecordType = PilotRecordType.PAYMENT_EVIDENCE

    amount: float = Field(ge=0.0)
    currency: str = Field(default="KRW", min_length=3, max_length=3)
    payment_method: str | None = None
    payment_date: NonEmptyStr
    description: str | None = None
    internal_reference: NonEmptyStr

    @model_validator(mode="after")
    def reject_payer_identity(self) -> "PaymentEvidenceRecord":
        forbidden_data_keys = {
            "payer_name",
            "payer_email",
            "payer_phone",
            "payer_id",
            "account_number",
            "card_number",
            "card_last_four",
            "reference_number",
            "transaction_id",
            "screenshot_path",
            "screenshot",
            "receipt_path",
        }
        violations = [k for k in self.data if k in forbidden_data_keys]
        if violations:
            raise ValueError(
                "Payment evidence must not contain payer identity or "
                "account/card/reference data. Forbidden keys: "
                + ", ".join(sorted(violations))
            )
        return self

    @model_validator(mode="after")
    def check_no_sensitive_paths(self) -> "PaymentEvidenceRecord":
        desc = self.description or ""
        if desc:
            matches = detect_sensitive_values(desc)
            if any(m.category == "file_path" for m in matches):
                object.__setattr__(
                    self,
                    "description",
                    reject_or_redact_sensitive(
                        desc, reject=False, field_name="description"
                    ),
                )
        return self


class CorrectionRecord(PilotRecord):
    record_type: PilotRecordType = PilotRecordType.CORRECTION

    benchmark_run_id: NonEmptyStr
    human_correction_minutes: float = Field(ge=0.0)
    correction_reason: str | None = None

    @model_validator(mode="after")
    def check_sensitive_fields(self) -> "CorrectionRecord":
        val = self.correction_reason
        if isinstance(val, str) and val:
            object.__setattr__(
                self,
                "correction_reason",
                reject_or_redact_sensitive(
                    val, reject=False, field_name="correction_reason"
                ),
            )
        return self


class DeletionRequestRecord(PilotRecord):
    record_type: PilotRecordType = PilotRecordType.DELETION_REQUEST

    reason: str = Field(default="participant_requested")
    requested_by: str = Field(default="system")
    notes: str | None = None

    @model_validator(mode="after")
    def check_sensitive_fields(self) -> "DeletionRequestRecord":
        val = self.notes
        if isinstance(val, str) and val:
            object.__setattr__(
                self,
                "notes",
                reject_or_redact_sensitive(
                    val, reject=False, field_name="notes"
                ),
            )
        return self


class DeletionCompletionRecord(PilotRecord):
    record_type: PilotRecordType = PilotRecordType.DELETION_COMPLETION

    deletion_request_id: NonEmptyStr
    deletion_result: NonEmptyStr
    participant_deleted: bool = False
    completed_at: str = Field(default_factory=lambda: _now_utc_iso())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _record_model_for_type(
    record_type: PilotRecordType,
) -> type[PilotRecord]:
    mapping: dict[PilotRecordType, type[PilotRecord]] = {
        PilotRecordType.BENCHMARK_RUN: BenchmarkRunRecord,
        PilotRecordType.PILOT_RUN: PilotRunRecord,
        PilotRecordType.PILOT_EVIDENCE: PilotEvidenceRecord,
        PilotRecordType.PAYMENT_EVIDENCE: PaymentEvidenceRecord,
        PilotRecordType.CORRECTION: CorrectionRecord,
        PilotRecordType.DELETION_REQUEST: DeletionRequestRecord,
        PilotRecordType.DELETION_COMPLETION: DeletionCompletionRecord,
    }
    return mapping[record_type]


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------


def _create_pilot_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_PILOT_OPS_TABLE} (
            record_id TEXT PRIMARY KEY,
            record_type TEXT NOT NULL
                CHECK(record_type IN (
                    'benchmark_run',
                    'pilot_run',
                    'pilot_evidence',
                    'payment_evidence',
                    'correction',
                    'deletion_request',
                    'deletion_completion'
                )),
            participant_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{_PILOT_OPS_TABLE}_participant_id
        ON {_PILOT_OPS_TABLE}(participant_id)
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{_PILOT_OPS_TABLE}_record_type
        ON {_PILOT_OPS_TABLE}(record_type)
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def record_operation(
    conn: sqlite3.Connection,
    record: PilotRecord,
) -> PilotRecord:
    _create_pilot_table(conn)

    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")

    conn.execute("BEGIN IMMEDIATE")
    try:
        payload = record.model_dump_json()
        conn.execute(
            f"""
            INSERT INTO {_PILOT_OPS_TABLE}
            (record_id, record_type, participant_id, created_at, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                record.record_id,
                record.record_type.value,
                record.participant_id,
                record.created_at,
                payload,
            ),
        )
        conn.commit()
        return record
    except Exception:
        conn.rollback()
        raise


def list_records(
    conn: sqlite3.Connection,
    *,
    record_type: str | None = None,
    participant_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return pilot operation records ordered newest-first.

    Deterministic ordering contract (documented for code, tests, docs, and CLI
    consistency): records are ordered by ``created_at DESC`` with a stable
    secondary key of ``rowid DESC``. The secondary key guarantees that, even
    when two records share an identical ``created_at`` (for example a deletion
    request followed immediately by its completion), the later-inserted record
    is returned first. Callers must not rely on millisecond timestamp ties.
    """
    _create_pilot_table(conn)

    conditions: list[str] = []
    params: list[Any] = []

    if record_type:
        conditions.append("record_type = ?")
        params.append(record_type)
    if participant_id:
        conditions.append("participant_id = ?")
        params.append(participant_id)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    rows = conn.execute(
        f"SELECT record_id, record_type, participant_id, created_at, payload "
        f"FROM {_PILOT_OPS_TABLE} {where} "
        f"ORDER BY created_at DESC, rowid DESC",
        params,
    ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row["payload"])
        results.append(
            {
                "record_id": row["record_id"],
                "record_type": row["record_type"],
                "participant_id": row["participant_id"],
                "created_at": row["created_at"],
                **payload,
            }
        )
    return results


def get_record_by_id(
    conn: sqlite3.Connection, record_id: str
) -> dict[str, Any] | None:
    _create_pilot_table(conn)

    row = conn.execute(
        f"SELECT payload FROM {_PILOT_OPS_TABLE} WHERE record_id = ?",
        (record_id,),
    ).fetchone()
    if row is None:
        return None
    payload = json.loads(row["payload"])
    return payload


def update_record(
    conn: sqlite3.Connection,
    record_id: str,
    updates: dict[str, Any],
) -> bool:
    _create_pilot_table(conn)

    existing = get_record_by_id(conn, record_id)
    if existing is None:
        return False

    updated_data = {**existing, **updates}
    violations = check_forbidden_keys(updated_data)
    if violations:
        raise ValueError(
            "Forbidden keys detected: " + "; ".join(violations)
        )

    model_cls = _record_model_for_type(
        PilotRecordType(existing["record_type"])
    )
    updated_record = model_cls.model_validate(updated_data)

    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")

    conn.execute("BEGIN IMMEDIATE")
    try:
        payload = updated_record.model_dump_json()
        conn.execute(
            f"UPDATE {_PILOT_OPS_TABLE} SET payload = ? WHERE record_id = ?",
            (payload, record_id),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


# ---------------------------------------------------------------------------
# Evidence export with pseudonymization
# ---------------------------------------------------------------------------

_HASH_SALT = b"personal-edition.pilot-ops.export.v1\x00"


def pseudonymize_id(participant_id: str) -> str:
    h = hashlib.sha256(_HASH_SALT + participant_id.encode("utf-8")).hexdigest()
    return f"P-{h[:12]}"


def _redact_private_text(data: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in data.items():
        if key in _PRIVATE_FIELDS:
            if isinstance(value, str) and value:
                redacted[key] = "[REDACTED-PRIVATE]"
            else:
                redacted[key] = value
        elif isinstance(value, dict):
            redacted[key] = _redact_private_text(value)
        elif isinstance(value, list):
            redacted[key] = [
                _redact_private_text(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            redacted[key] = value
    return redacted


def export_evidence(
    conn: sqlite3.Connection,
    *,
    participant_id: str | None = None,
    export_safe: bool = False,
) -> list[dict[str, Any]]:
    records = list_records(conn, participant_id=participant_id)

    exported: list[dict[str, Any]] = []
    for record in records:
        pseudo_id = pseudonymize_id(record["participant_id"])
        entry = {**record, "participant_id": pseudo_id}

        if export_safe:
            entry = _redact_private_text(entry)

        exported.append(entry)

    return exported


# ---------------------------------------------------------------------------
# Deletion workflow
# ---------------------------------------------------------------------------


def execute_deletion(
    conn: sqlite3.Connection,
    participant_id: str,
    *,
    reason: str = "participant_requested",
    notes: str | None = None,
) -> dict[str, Any]:
    request_record = DeletionRequestRecord(
        participant_id=participant_id,
        reason=reason,
        notes=notes,
    )
    record_operation(conn, request_record)

    deleted = pt_repo.delete_participant(SqliteRuntimeConnection(conn), participant_id)

    completion_record = DeletionCompletionRecord(
        participant_id=participant_id,
        deletion_request_id=request_record.record_id,
        deletion_result="success" if deleted else "not_found",
        participant_deleted=deleted,
    )
    record_operation(conn, completion_record)

    return {
        "request_id": request_record.record_id,
        "completion_id": completion_record.record_id,
        "deleted": deleted,
    }


# ---------------------------------------------------------------------------
# Correction update
# ---------------------------------------------------------------------------


def update_correction(
    *,
    db_path: str,
    run_id: str,
    minutes: float,
) -> None:
    conn = get_connection(db_path)
    try:
        _create_pilot_table(conn)

        existing = get_record_by_id(conn, run_id)
        if existing is None:
            print(f"Error: no record found with id {run_id}", file=sys.stderr)
            sys.exit(1)

        record_type = existing.get("record_type")
        if record_type not in (
            PilotRecordType.BENCHMARK_RUN.value,
            PilotRecordType.PILOT_RUN.value,
        ):
            print(
                f"Error: record {run_id} is type '{record_type}', "
                "not a benchmark or pilot run",
                file=sys.stderr,
            )
            sys.exit(1)

        update_record(conn, run_id, {"human_correction_minutes": minutes})
        record = CorrectionRecord(
            participant_id=existing["participant_id"],
            benchmark_run_id=run_id,
            human_correction_minutes=minutes,
            correction_reason="manual update via CLI",
        )
        record_operation(conn, record)
        print(
            f"Updated run {run_id} with human_correction_minutes={minutes}"
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pilot operations recording CLI"
    )
    subparsers = parser.add_subparsers(dest="command")

    record_parser = subparsers.add_parser(
        "record", help="Record a pilot operation"
    )
    record_parser.add_argument(
        "--type",
        required=True,
        choices=[t.value for t in PilotRecordType],
        dest="record_type",
        help="Record type.",
    )
    record_parser.add_argument(
        "--participant-id",
        required=True,
        help="Participant identifier.",
    )
    record_parser.add_argument(
        "--data",
        required=True,
        help="JSON string with record-specific data.",
    )
    record_parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite database.",
    )

    delete_parser = subparsers.add_parser(
        "delete", help="Delete a participant with full workflow"
    )
    delete_parser.add_argument(
        "--participant-id",
        required=True,
        help="Participant identifier to delete.",
    )
    delete_parser.add_argument(
        "--reason",
        default="participant_requested",
        help="Deletion reason.",
    )
    delete_parser.add_argument(
        "--notes",
        default=None,
        help="Optional deletion notes.",
    )
    delete_parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite database.",
    )

    export_parser = subparsers.add_parser(
        "export-evidence", help="Export pilot evidence records"
    )
    export_parser.add_argument(
        "--participant-id",
        default=None,
        help="Filter by participant ID.",
    )
    export_parser.add_argument(
        "--export-safe",
        action="store_true",
        help="Redact private text and pseudonymize participant IDs.",
    )
    export_parser.add_argument(
        "--output",
        default=None,
        help="Path to write JSON output.",
    )
    export_parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite database.",
    )

    uc_parser = subparsers.add_parser(
        "update-correction",
        help="Update human_correction_minutes on a benchmark or pilot run",
    )
    uc_parser.add_argument(
        "--run-id",
        required=True,
        help="Record ID to update.",
    )
    uc_parser.add_argument(
        "--minutes",
        type=float,
        required=True,
        help="Correction minutes value.",
    )
    uc_parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite database.",
    )

    list_parser = subparsers.add_parser(
        "list-records", help="List pilot operation records"
    )
    list_parser.add_argument(
        "--type",
        default=None,
        dest="record_type",
        choices=[t.value for t in PilotRecordType],
        help="Filter by record type.",
    )
    list_parser.add_argument(
        "--participant-id",
        default=None,
        help="Filter by participant ID.",
    )
    list_parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite database.",
    )

    args = parser.parse_args()
    settings = Settings()

    resolved_db = getattr(args, "db", None) or settings.database_path

    if args.command == "record":
        _handle_record(args, resolved_db)
    elif args.command == "delete":
        _handle_delete(args, resolved_db)
    elif args.command == "export-evidence":
        _handle_export(args, resolved_db)
    elif args.command == "update-correction":
        update_correction(
            db_path=resolved_db,
            run_id=args.run_id,
            minutes=args.minutes,
        )
    elif args.command == "list-records":
        _handle_list(args, resolved_db)
    else:
        parser.print_help()
        sys.exit(1)


def _handle_record(args: argparse.Namespace, db_path: str) -> None:
    data = json.loads(args.data)

    record_type = PilotRecordType(args.record_type)
    model_cls = _record_model_for_type(record_type)

    init_data = {
        "participant_id": args.participant_id,
        "data": data,
    }

    if record_type in (
        PilotRecordType.BENCHMARK_RUN,
        PilotRecordType.PILOT_RUN,
    ):
        init_data.update(data)

    record = model_cls.model_validate(init_data)

    conn = get_connection(db_path)
    try:
        apply_migrations(conn, "migrations")
        record_operation(conn, record)
        print(f"Recorded {record_type.value}: {record.record_id}")
    finally:
        conn.close()


def _handle_delete(args: argparse.Namespace, db_path: str) -> None:
    conn = get_connection(db_path)
    try:
        apply_migrations(conn, "migrations")
        result = execute_deletion(
            conn,
            args.participant_id,
            reason=args.reason,
            notes=args.notes,
        )
        if result["deleted"]:
            print(
                f"Participant '{args.participant_id}' deleted successfully."
            )
            print(f"  Deletion request: {result['request_id']}")
            print(f"  Deletion completion: {result['completion_id']}")
        else:
            print(
                f"Participant '{args.participant_id}' not found "
                "or already deleted.",
                file=sys.stderr,
            )
            sys.exit(1)
    finally:
        conn.close()


def _handle_export(args: argparse.Namespace, db_path: str) -> None:
    conn = get_connection(db_path)
    try:
        apply_migrations(conn, "migrations")
        records = export_evidence(
            conn,
            participant_id=args.participant_id,
            export_safe=args.export_safe,
        )

        output_json = json.dumps(records, indent=2, ensure_ascii=False)

        if args.output:
            Path(args.output).write_text(output_json, encoding="utf-8")
            print(f"Exported {len(records)} records to {args.output}")
        else:
            print(output_json)
    finally:
        conn.close()


def _handle_list(args: argparse.Namespace, db_path: str) -> None:
    conn = get_connection(db_path)
    try:
        apply_migrations(conn, "migrations")
        records = list_records(
            conn,
            record_type=args.record_type,
            participant_id=args.participant_id,
        )

        if not records:
            print("No records found.")
            return

        print(f"Found {len(records)} record(s):")
        for rec in records:
            rt = rec.get("record_type", "?")
            pid = rec.get("participant_id", "?")
            rid = rec.get("record_id", "?")
            ts = rec.get("created_at", "?")
            print(f"  [{rt}] {rid}  participant={pid}  {ts}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
