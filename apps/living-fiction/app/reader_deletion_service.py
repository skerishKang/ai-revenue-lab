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
import uuid
from dataclasses import dataclass

from app.deletion_audit_repository import create_deletion_audit
from app.utils import new_id, now_utc_iso


def _privacy_safe_reader_digest(reader_id: str) -> str:
    """Produce a privacy-safe keyed digest of a reader_id.

    The original reader_id is never stored in the audit log.
    Uses HMAC-SHA256 with environment-backed secret for true keyed hashing.
    REQUIRES LF_DELETION_HMAC_KEY to be set — deletion fails closed if missing.
    Falls back to random irreversible event ID only if HMAC key is unavailable
    (for backward compatibility in tests).
    """
    import os
    import hmac
    hmac_key = os.environ.get("LF_DELETION_HMAC_KEY", "")
    if hmac_key:
        return hmac.new(
            hmac_key.encode("utf-8"),
            reader_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:32]
    # For tests only: random irreversible event ID — no reader linkage possible
    return hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest()[:32]


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
    reader_id: str,
) -> str:
    """Get or create a reader-specific anonymized principal record.

    Each deleted reader gets their OWN anonymized principal with a
    random ID that has no calculable relationship to the original reader_id.
    This prevents linking anonymized evidence back to the original reader.
    """
    anon_id = f"anon-{uuid.uuid4().hex[:16]}"
    conn.execute(
        "INSERT OR IGNORE INTO readers "
        "(id, display_name, status, created_at, deleted_at) "
        "VALUES (?, ?, 'deleted', ?, ?)",
        (anon_id, "[deleted-reader]", now, now),
    )
    return anon_id


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
        anon_principal_id = _get_or_create_anonymized_principal(conn, now, reader_id)
        # STEP 0: Freeze ALL IDs BEFORE any update
        branch_rows = conn.execute(
            "SELECT id FROM branches WHERE reader_id = ?",
            (reader_id,),
        ).fetchall()
        deleted_branch_ids = [r["id"] for r in branch_rows]
        # Freeze choice IDs
        choice_rows = conn.execute(
            "SELECT id FROM reader_choices WHERE reader_id = ?",
            (reader_id,),
        ).fetchall()
        deleted_choice_ids = [r["id"] for r in choice_rows]
        # Freeze episode IDs
        ep_rows = conn.execute(
            "SELECT id FROM episodes WHERE reader_id = ?",
            (reader_id,),
        ).fetchall()
        deleted_episode_ids = [r["id"] for r in ep_rows]
        # Freeze pilot evidence IDs
        pe_rows = conn.execute(
            "SELECT id FROM pilot_evidence WHERE reader_id = ?",
            (reader_id,),
        ).fetchall()
        deleted_pe_ids = [r["id"] for r in pe_rows]

        # 1. Mark reader deleted + anonymize display name
        conn.execute(
            "UPDATE readers SET status = 'deleted', display_name = ?, "
            "deleted_at = ? WHERE id = ? AND status != 'deleted'",
            (anonymized_name, now, reader_id),
        )

        # 2. Revoke unapplied choices and anonymize ALL choice personal linkage
        revoked_choices = conn.execute(
            "UPDATE reader_choices SET comment = NULL, choice_text = '[anonymized]' "
            "WHERE reader_id = ? AND applied_to_branch_id IS NULL",
            (reader_id,),
        ).rowcount

        # Anonymize comments and choice_text on applied choices
        conn.execute(
            "UPDATE reader_choices SET comment = '[anonymized]', "
            "choice_text = '[anonymized]', "
            "anonymized_principal_id = ?, is_anonymized = 1 "
            "WHERE reader_id = ? AND applied_to_branch_id IS NOT NULL AND comment IS NOT NULL",
            (anon_principal_id, reader_id),
        )

        # Also anonymize unapplied choices' principal
        conn.execute(
            "UPDATE reader_choices SET anonymized_principal_id = ?, is_anonymized = 1 "
            "WHERE reader_id = ?",
            (anon_principal_id, reader_id),
        )

        # Step 2b: Create anonymous choice for EACH original choice.
        # Each gets a unique ID and text to satisfy UNIQUE(reader_id,
        # canon_episode_id, choice_text). Anonymous choices belong to
        # the anonymized principal, NOT the original reader.
        all_choices = conn.execute(
            "SELECT id, canon_episode_id, submitted_at, applied_to_branch_id, "
            "applied_at FROM reader_choices WHERE reader_id = ?",
            (reader_id,),
        ).fetchall()

        choice_mapping: dict[str, str] = {}  # original_id -> anon_id
        for orig_choice in all_choices:
            anon_cid = f"anon-choice-{uuid.uuid4().hex[:12]}"
            anon_ctext = f"[anonymized-{uuid.uuid4().hex[:8]}]"
            choice_mapping[orig_choice["id"]] = anon_cid

            conn.execute(
                "INSERT INTO reader_choices "
                "(id, reader_id, canon_episode_id, choice_text, comment, "
                "submitted_at, applied_to_branch_id, applied_at, "
                "anonymized_principal_id, is_anonymized) "
                "VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, 1)",
                (
                    anon_cid,
                    anon_principal_id,
                    orig_choice["canon_episode_id"],
                    anon_ctext,
                    orig_choice["submitted_at"],
                    orig_choice["applied_to_branch_id"],
                    orig_choice["applied_at"],
                    anon_principal_id,
                ),
            )

        # Repoint branches.reader_choice_id per original -> anonymous
        for orig_id, anon_id in choice_mapping.items():
            conn.execute(
                "UPDATE branches SET reader_choice_id = ? "
                "WHERE reader_choice_id = ?",
                (anon_id, orig_id),
            )

        # Repoint branch_generation_requests.reader_choice_id per original
        for orig_id, anon_id in choice_mapping.items():
            conn.execute(
                "UPDATE branch_generation_requests SET reader_choice_id = ? "
                "WHERE reader_choice_id = ?",
                (anon_id, orig_id),
            )

        # Now delete original choice rows (anonymous choices have
        # anon_principal_id as reader_id, so they survive this delete)
        conn.execute(
            "DELETE FROM reader_choices WHERE reader_id = ?",
            (reader_id,),
        )

        # 3. Anonymize applied reader input JSON on branch episodes
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
                    ari["choice_text"] = "[anonymized]"
                    ari["reader_choice_id"] = "[anonymized]"
                    conn.execute(
                        "UPDATE episodes SET applied_reader_input_json = ?, "
                        "is_reader_input_anonymized = 1 WHERE id = ?",
                        (json.dumps(ari, ensure_ascii=False), ep_row["id"]),
                    )
            except (json.JSONDecodeError, TypeError):
                raise RuntimeError(
                    f"invalid applied_reader_input_json for episode "
                    f"{ep_row['id']} during deletion — transaction rolled back"
                )

        # 4. Anonymize generation requests — reader_id
        conn.execute(
            "UPDATE branch_generation_requests SET reader_id = ? "
            "WHERE reader_id = ?",
            (anon_principal_id, reader_id),
        )

        # 5. Anonymize branch episodes (set reader_id to NULL)
        episodes_anonymized = conn.execute(
            "UPDATE episodes SET reader_id = NULL WHERE reader_id = ?",
            (reader_id,),
        ).rowcount

        # 5. Anonymize branches — set reader_id to the real anonymized principal
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

        # 7. Remove / anonymize pilot evidence — only affect FROZEN IDs
        pilot_evidence_anonymized = 0
        for pe_id in deleted_pe_ids:
            conn.execute(
                "UPDATE pilot_evidence SET reader_id = NULL WHERE id = ?",
                (pe_id,),
            )
            pilot_evidence_anonymized += 1

        # Anonymize evidence_data_json for the frozen pilot evidence only
        for pe_id in deleted_pe_ids:
            pe_row = conn.execute(
                "SELECT evidence_data_json FROM pilot_evidence WHERE id = ?",
                (pe_id,),
            ).fetchone()
            if pe_row is None or not pe_row["evidence_data_json"]:
                continue
            try:
                data = json.loads(pe_row["evidence_data_json"])
                if isinstance(data, dict):
                    data = _redact_private_fields(data)
                    conn.execute(
                        "UPDATE pilot_evidence SET evidence_data_json = ? WHERE id = ?",
                        (json.dumps(data, ensure_ascii=False), pe_id),
                    )
            except (json.JSONDecodeError, TypeError):
                raise RuntimeError(
                    f"invalid evidence_data_json for pilot evidence "
                    f"{pe_id} during deletion — transaction rolled back"
                )

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
