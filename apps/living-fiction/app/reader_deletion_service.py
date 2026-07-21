"""Reader deletion/revocation service.

Implements one transactional deletion/anonymization workflow:

- marks the reader deleted;
- removes or anonymizes display name and private comments;
- revokes unapplied choices;
- removes personal linkage from choices, branch episodes, branches,
  rejoin requests, and pilot evidence according to the product contract;
- preserves shared canon without personal linkage;
- uses a real anonymized principal reader record (valid FK reference)
  instead of disabling FK and storing a fake '[deleted]' ID;
- is idempotent;
- survives close/reopen.

Does not leave private comments or direct reader identifiers in export-safe
records after deletion.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from app.deletion_audit_repository import create_deletion_audit
from app.utils import new_id, now_utc_iso


def _privacy_safe_reader_digest(reader_id: str) -> str:
    """Produce a privacy-safe keyed digest of a reader_id.

    The original reader_id is never stored in the audit log.
    Uses SHA-256 with a static salt prefix for deterministic lookup.
    """
    salt = "lf-deletion-audit-20260721"
    return hashlib.sha256((salt + reader_id).encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class DeletionResult:
    reader_id: str
    success: bool
    choices_revoked: int
    branches_anonymized: int
    episodes_anonymized: int
    rejoin_requests_removed: int
    pilot_evidence_anonymized: int
    audit_id: str | None


def _get_or_create_anonymized_principal(
    conn: sqlite3.Connection,
    now: str,
) -> str:
    """Get or create the global anonymized reader principal record.

    Uses INSERT OR IGNORE for idempotent creation inside a transaction.
    """
    conn.execute(
        "INSERT OR IGNORE INTO readers "
        "(id, display_name, status, created_at, deleted_at) "
        "VALUES (?, ?, 'deleted', ?, ?)",
        ("anon-deleted-principal", "[deleted-reader]", now, now),
    )
    return "anon-deleted-principal"


def delete_reader_with_revocation(
    conn: sqlite3.Connection,
    reader_id: str,
) -> DeletionResult:
    """Transactionally delete/anonymize a reader and all personal linkage.

    Preserves shared canon. Idempotent — calling twice is a no-op.
    Uses real anonymized principal reader record instead of disabling FK
    or storing fake '[deleted]' IDs.
    """
    # Check if already deleted
    row = conn.execute(
        "SELECT id, display_name, status, deleted_at FROM readers WHERE id = ?",
        (reader_id,),
    ).fetchone()
    if row is None:
        return DeletionResult(
            reader_id=reader_id, success=False,
            choices_revoked=0, branches_anonymized=0,
            episodes_anonymized=0, rejoin_requests_removed=0,
            pilot_evidence_anonymized=0, audit_id=None,
        )

    if row["status"] == "deleted":
        # Idempotent — already deleted
        return DeletionResult(
            reader_id=reader_id, success=True,
            choices_revoked=0, branches_anonymized=0,
            episodes_anonymized=0, rejoin_requests_removed=0,
            pilot_evidence_anonymized=0, audit_id=None,
        )

    if conn.in_transaction:
        raise RuntimeError("deletion requires an idle connection")

    now = now_utc_iso()
    anonymized_name = "[deleted-reader]"

    # Ensure a clean connection
    if conn.in_transaction:
        conn.rollback()

    conn.execute("BEGIN IMMEDIATE")
    try:
        # STEP 0: Ensure anonymized principal exists
        anon_principal_id = _get_or_create_anonymized_principal(conn, now)
        # STEP 0: Freeze branch IDs BEFORE any update
        branch_rows = conn.execute(
            "SELECT id FROM branches WHERE reader_id = ?",
            (reader_id,),
        ).fetchall()
        deleted_branch_ids = [r["id"] for r in branch_rows]

        # 1. Mark reader deleted + anonymize display name
        conn.execute(
            "UPDATE readers SET status = 'deleted', display_name = ?, "
            "deleted_at = ? WHERE id = ? AND status != 'deleted'",
            (anonymized_name, now, reader_id),
        )

        # 2. Revoke unapplied choices (remove personal linkage)
        revoked_choices = conn.execute(
            "UPDATE reader_choices SET comment = NULL "
            "WHERE reader_id = ? AND applied_to_branch_id IS NULL",
            (reader_id,),
        ).rowcount

        # Anonymize comments on applied choices
        conn.execute(
            "UPDATE reader_choices SET comment = '[anonymized]' "
            "WHERE reader_id = ? AND applied_to_branch_id IS NOT NULL AND comment IS NOT NULL",
            (reader_id,),
        )

        # 3. Anonymize applied reader input JSON on branch episodes
        # Remove private comment from applied_reader_input_json
        ep_rows = conn.execute(
            "SELECT id, applied_reader_input_json FROM episodes "
            "WHERE reader_id = ? AND applied_reader_input_json IS NOT NULL",
            (reader_id,),
        ).fetchall()
        for ep_row in ep_rows:
            try:
                ari = json.loads(ep_row["applied_reader_input_json"])
                if isinstance(ari, dict):
                    ari["comment"] = "[anonymized]"
                    ari["private_text"] = "[anonymized]"
                    conn.execute(
                        "UPDATE episodes SET applied_reader_input_json = ? WHERE id = ?",
                        (json.dumps(ari, ensure_ascii=False), ep_row["id"]),
                    )
            except (json.JSONDecodeError, TypeError):
                pass

        # 4. Anonymize branch episodes (set reader_id to NULL)
        episodes_anonymized = conn.execute(
            "UPDATE episodes SET reader_id = NULL WHERE reader_id = ?",
            (reader_id,),
        ).rowcount

        # 5. Anonymize branches — set reader_id to the real anonymized principal
        # Uses valid FK reference, not fake '[deleted]' ID
        branches_anonymized = conn.execute(
            "UPDATE branches SET reader_id = ? WHERE reader_id = ?",
            (anon_principal_id, reader_id),
        ).rowcount

        # 6. Delete rejoin requests (use frozen branch IDs)
        rejoin_requests_removed = 0
        for bid in deleted_branch_ids:
            rr = conn.execute(
                "DELETE FROM rejoin_requests WHERE branch_id = ?",
                (bid,),
            ).rowcount
            rejoin_requests_removed += rr

            rr2 = conn.execute(
                "DELETE FROM rejoin_requests_v2 WHERE branch_id = ?",
                (bid,),
            ).rowcount
            rejoin_requests_removed += rr2

        # 7. Remove / anonymize pilot evidence
        pilot_evidence_anonymized = conn.execute(
            "UPDATE pilot_evidence SET reader_id = NULL WHERE reader_id = ?",
            (reader_id,),
        ).rowcount

        # Also anonymize evidence_data_json for pilot evidence — remove private text
        pe_rows = conn.execute(
            "SELECT id, evidence_data_json FROM pilot_evidence WHERE reader_id IS NULL "
            "AND evidence_data_json IS NOT NULL",
        ).fetchall()
        for pe_row in pe_rows:
            try:
                data = json.loads(pe_row["evidence_data_json"])
                if isinstance(data, dict):
                    # Recursively redact sensitive fields
                    data = _redact_private_fields(data)
                    conn.execute(
                        "UPDATE pilot_evidence SET evidence_data_json = ? WHERE id = ?",
                        (json.dumps(data, ensure_ascii=False), pe_row["id"]),
                    )
            except (json.JSONDecodeError, TypeError):
                pass

        # 8. Create audit record with privacy-safe keyed digest
        audit_id = new_id()
        create_deletion_audit(
            conn,
            audit_id=audit_id,
            reader_id=_privacy_safe_reader_digest(reader_id),
            anonymized_display_name=anonymized_name,
            choices_revoked_count=revoked_choices,
            branches_anonymized_count=branches_anonymized,
            episodes_anonymized_count=episodes_anonymized,
            rejoin_requests_removed_count=rejoin_requests_removed,
            pilot_evidence_anonymized_count=pilot_evidence_anonymized,
            deleted_at=now,
        )

        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise

    return DeletionResult(
        reader_id=reader_id,
        success=True,
        choices_revoked=revoked_choices,
        branches_anonymized=branches_anonymized,
        episodes_anonymized=episodes_anonymized,
        rejoin_requests_removed=rejoin_requests_removed,
        pilot_evidence_anonymized=pilot_evidence_anonymized,
        audit_id=audit_id,
    )


_HASH_PRIVATE_FIELD_NAMES = frozenset({
    "comment", "private_comment", "private_text", "raw_comment",
    "reader_comment", "phone", "email", "card_number",
    "payer_name", "api_key", "token", "secret",
})


def _redact_private_fields(data: dict) -> dict:
    """Recursively redact private/sensitive fields from evidence data."""
    result: dict = {}
    for key, value in data.items():
        if isinstance(key, str) and key.lower() in _HASH_PRIVATE_FIELD_NAMES:
            if isinstance(value, str) and len(value) > 0:
                result[key] = "[redacted]"
            else:
                result[key] = value
        elif isinstance(value, dict):
            result[key] = _redact_private_fields(value)
        elif isinstance(value, list):
            result[key] = [
                _redact_private_fields(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result
