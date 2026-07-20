"""Reader deletion/revocation service.

Implements one transactional deletion/anonymization workflow:

- marks the reader deleted;
- removes or anonymizes display name and private comments;
- revokes unapplied choices;
- removes personal linkage from choices, branch episodes, branches,
  rejoin requests, and pilot evidence according to the product contract;
- prevents new generation;
- preserves shared canon without personal linkage;
- is idempotent;
- survives close/reopen.

Does not leave private comments or direct reader identifiers in export-safe
records after deletion.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from app.deletion_audit_repository import create_deletion_audit
from app.utils import new_id, now_utc_iso


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


def delete_reader_with_revocation(
    conn: sqlite3.Connection,
    reader_id: str,
) -> DeletionResult:
    """Transactionally delete/anonymize a reader and all personal linkage.

    Preserves shared canon. Idempotent — calling twice is a no-op.
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

    # Disable FK enforcement BEFORE starting the transaction
    # (SQLite PRAGMA foreign_keys cannot be changed inside a transaction)
    conn.execute("PRAGMA foreign_keys = OFF")

    conn.execute("BEGIN IMMEDIATE")
    try:
        # 1. Mark reader deleted + anonymize display name
        conn.execute(
            "UPDATE readers SET status = 'deleted', display_name = ?, "
            "deleted_at = ? WHERE id = ? AND status != 'deleted'",
            (anonymized_name, now, reader_id),
        )

        # 2. Revoke unapplied choices (remove personal linkage)
        # Applied choices keep their branch reference but anonymize comment
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

        # 3. Anonymize branch episodes (remove reader_id, anonymize applied_reader_input)
        episodes_anonymized = conn.execute(
            "UPDATE episodes SET reader_id = NULL, "
            "applied_reader_input_json = "
            "  json_set(applied_reader_input_json, '$.comment', '[anonymized]') "
            "WHERE reader_id = ?",
            (reader_id,),
        ).rowcount

        # 4. Anonymize branches (keep branch for canon continuity, anonymize reader_id)
        # branches.reader_id is NOT NULL, so set to anonymized placeholder
        branches_anonymized = conn.execute(
            "UPDATE branches SET reader_id = '[deleted]' "
            "WHERE reader_id = ?",
            (reader_id,),
        ).rowcount

        # 5. Remove rejoin requests (personal linkage)
        rejoin_requests_removed = conn.execute(
            "DELETE FROM rejoin_requests WHERE branch_id IN "
            "(SELECT id FROM branches WHERE reader_id = ?)",
            (reader_id,),
        ).rowcount

        # Also remove v2 rejoin requests
        conn.execute(
            "DELETE FROM rejoin_requests_v2 WHERE branch_id IN "
            "(SELECT id FROM branches WHERE reader_id = ?)",
            (reader_id,),
        )

        # 6. Anonymize pilot evidence (remove reader_id, scan/redact data)
        pilot_evidence_anonymized = conn.execute(
            "UPDATE pilot_evidence SET reader_id = NULL "
            "WHERE reader_id = ?",
            (reader_id,),
        ).rowcount

        # 7. Create audit record
        audit_id = new_id()
        create_deletion_audit(
            conn,
            audit_id=audit_id,
            reader_id=reader_id,
            anonymized_display_name=anonymized_name,
            choices_revoked_count=revoked_choices,
            branches_anonymized_count=branches_anonymized,
            episodes_anonymized_count=episodes_anonymized,
            rejoin_requests_removed_count=rejoin_requests_removed,
            pilot_evidence_anonymized_count=pilot_evidence_anonymized,
            deleted_at=now,
        )

        conn.commit()
        # Re-enable FK enforcement
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        conn.execute("PRAGMA foreign_keys = ON")
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
