"""Self-service Chat account deletion — Chat DB and COM2 PC queue data (#6659 3).

SCOPE
    The signed-in account's own Chat DB rows and, on COM2, PC queue rows. D1
    keeps the same PC tables inside the Chat DB. This route never
    touches the shared Control Plane login account, B14 ledgers, R2 file
    objects, offsite backups or the user-PC ``.padiem-backup`` copies; those
    stay and are recorded as later steps in
    ``docs/operations/ACCOUNT_DELETION_20261103.md``.

WHY EVERY DELETE IS EXPLICIT
    Production D1 does not enforce ``PRAGMA foreign_keys`` and the local
    CPython host deliberately mirrors that (see ``local_cpython.py``), so a
    declared ``ON DELETE CASCADE`` is documentation, not enforcement here.
    Each database is cleaned with one atomic batch. D1 has one Chat batch;
    COM2 cleans its PC queue batch before the Chat batch. Replay-prevention
    rows in oracle_mesh_dispatch are intentionally retained.

THE ONE CONFIRMATION
    Deleting an account is irreversible destruction, so the route requires the
    signed-in user to retype their own account email exactly. The email is
    compared to the stored account email; anything else deletes nothing.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from starlette.responses import JSONResponse

from .auth import SESSION_COOKIE
from .auth_routes import (
    _auth_error,
    _json_body,
    _revoke_all_canonical_sessions,
    _revoke_canonical_session,
    _unavailable,
    auth_ready,
    current_user_id,
)
from .history import _row_to_dict
from .pc_device_pairing_store import mesh_presence_account_cleanup_statements

#: Tables deleted with ``WHERE <key> = ?`` bound to the account id, in
#: child-before-parent order. Every entry was verified against the migration
#: survey in ``docs/operations/ACCOUNT_DELETION_20261103.md``. ``bookai_records``
#: is deliberately absent: its ``subject`` key is a client-issued opaque value
#: with no mapping to ``users.id`` in this database, so a user-scoped delete is
#: impossible here and stays a recorded later step.
_USER_KEYED_TABLES: tuple[tuple[str, str], ...] = (
    # Children that only the parent row ties to the account.
    ("messages", "conversation_id IN (SELECT id FROM conversations WHERE user_id = ?)"),
    ("conversations", "user_id = ?"),
    ("projects", "user_id = ?"),
    ("project_files", "user_id = ?"),
    ("saved_outputs", "user_id = ?"),
    ("orchestration_continuations", "user_id = ?"),
    ("orchestration_decisions", "user_id = ?"),
    ("claw_run_history", "user_id = ?"),
    ("claw_task_alert", "member_id = ?"),
    ("claw_approved_memory", "user_id = ?"),
    ("padiem_calendar_work_log", "owner_id = ?"),
    ("padiem_calendar_appointment", "owner_id = ?"),
    ("claw_approval_handoff", "user_id = ?"),
    ("claw_local_task_correlation", "user_id = ?"),
    ("password_credentials", "user_id = ?"),
    ("b66_saved_quote_skill", "user_id = ?"),
    ("b66_quote_asset", "user_id = ?"),
    ("b66_company_profile", "user_id = ?"),
    ("b66_quote_history", "user_id = ?"),
    ("claw_conversation_artifact_index", "user_id = ?"),
    ("b66_template_source", "user_id = ?"),
    ("b66_guided_draft", "user_id = ?"),
    ("claw_web_xlsx_selections", "user_id = ?"),
    ("claw_web_xlsx_p01_requests", "user_id = ?"),
    ("claw_web_xlsx_p01_decision_receipts", "user_id = ?"),
    ("claw_web_xlsx_quote_edit_receipts", "user_id = ?"),
    ("claw_web_xlsx_quote_write_decisions", "user_id = ?"),
    ("claw_web_xlsx_quote_write_pauses", "user_id = ?"),
    ("b66_saved_skill_candidate", "user_id = ?"),
    ("b66_memberships", "user_id = ?"),
    ("b66_membership_audit", "user_id = ?"),
    ("b66_signup_alert_outbox", "user_id = ?"),
    ("b66_signup_alert_delivery", "user_id = ?"),
    ("b66_member_inquiries", "user_id = ?"),
    ("b66_ai_conversation", "user_id = ?"),
    ("b66_ai_turn_attempt", "user_id = ?"),
    ("b66_guided_transcript", "user_id = ?"),
    ("claw_github_oauth_states", "user_id = ?"),
    ("claw_github_connections", "user_id = ?"),
    ("claw_coding_conversation_grant", "user_id = ?"),
    ("platform_admin_roles", "user_id = ?"),
    ("chat_custom_provider_credentials", "user_id = ?"),
    ("claw_pc_device_selection", "user_id = ?"),
    ("claw_meetings", "user_id = ?"),
    ("claw_meeting_artifacts", "user_id = ?"),
    ("claw_meeting_actions", "user_id = ?"),
    ("padiem_account_model_selections", "user_id = ?"),
    ("password_reset_tokens", "user_id = ?"),
    ("password_reset_audit", "user_id = ?"),
    ("document_convert_jobs", "user_id = ?"),
    ("document_convert_items", "user_id = ?"),
    ("claw_push_subscription", "member_id = ?"),
    ("pc_pairing_codes", "user_id = ?"),
    ("pc_install_tokens", "user_id = ?"),
    ("pc_device_links", "user_id = ?"),
    ("padiem_pc_delegations", "user_id = ?"),
    ("padiem_mcp_shell_jobs", "user_id = ?"),
    ("padiem_mcp_tokens", "user_id = ?"),
    ("padiem_mcp_approvals", "user_id = ?"),
    ("padiem_mcp_audit", "user_id = ?"),
    ("claw_artifact_delivery_receipts", "user_id = ?"),
    # Identity-result caches name the product user; clear every session's row.
    ("auth_validation_cache", "product_user_id = ?"),
    ("auth_account_link_cache", "product_user_id = ?"),
)

# Replay-prevention history is intentionally retained even though its schema has user_id.
_INTENTIONALLY_PRESERVED_USER_KEYED_TABLES: tuple[tuple[str, str], ...] = (
    ("oracle_mesh_dispatch", "user_id = ?"),
)
_PC_QUEUE_USER_TABLES = frozenset({
    "pc_pairing_codes", "pc_install_tokens", "pc_device_links",
})


def _delete_batch(
    db, user_id: str, *, include_pc_queue_data: bool = True
) -> list:
    """Build the Chat DB batch; COM2 PC rows are deleted by the queue first."""
    statements = [
        db.prepare(f"DELETE FROM {table} WHERE {where}").bind(user_id)
        for table, where in _USER_KEYED_TABLES
        if include_pc_queue_data or table not in _PC_QUEUE_USER_TABLES
    ]
    # Presence lives with the PC queue on COM2 and stays in this batch on D1.
    if include_pc_queue_data:
        statements.extend(mesh_presence_account_cleanup_statements(db, user_id))
    deleted_at = datetime.now(timezone.utc).isoformat()
    user_id_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    statements.append(
        db.prepare(
            "INSERT INTO account_deletion_audit (id, user_id_hash, deleted_at) VALUES (?,?,?)"
        ).bind(str(uuid.uuid4()), user_id_hash, deleted_at)
    )
    # The account row itself goes last, after every row that references it.
    statements.append(db.prepare("DELETE FROM users WHERE id = ?").bind(user_id))
    return statements


async def account_delete(request) -> JSONResponse:
    """Delete the signed-in account's Chat data after the exact-email confirmation."""
    if not auth_ready(request):
        return _unavailable()
    user_id = current_user_id(request)
    if not user_id:
        return _auth_error(401, "authentication_required", "로그인이 필요합니다.")
    db = getattr(request.app.state, "account_data_db", None)
    if db is None or not callable(getattr(db, "prepare", None)) or not callable(getattr(db, "batch", None)):
        return _auth_error(
            503,
            "account_delete_unavailable",
            "지금 계정 탈퇴를 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        )

    row = _row_to_dict(
        await db.prepare("SELECT email FROM users WHERE id = ?").bind(user_id).first()
    )
    email = row.get("email") if row else None
    if not isinstance(email, str) or not email:
        return _auth_error(401, "authentication_required", "로그인이 필요합니다.")

    data = await _json_body(request)
    if data is None or set(data) != {"confirm"} or not isinstance(data.get("confirm"), str):
        return _auth_error(
            400, "invalid_request", "탈퇴 확인 문구를 확인해 주세요. 아무것도 지워지지 않았습니다."
        )
    # The exact-match retyped email IS the "confirm once before irreversible
    # destruction" gate. Everything else deletes nothing.
    if data["confirm"] != email:
        return _auth_error(
            400,
            "account_delete_confirm_mismatch",
            "입력한 이메일이 계정 이메일과 일치하지 않습니다. 아무것도 지워지지 않았습니다.",
        )

    admin_email = str(getattr(request.app.state, "central_admin_google_email", "") or "")
    if admin_email.strip().lower() and email.strip().lower() == admin_email.strip().lower():
        return _auth_error(
            403,
            "account_delete_admin_blocked",
            "중앙 관리자 계정은 이 화면에서 탈퇴할 수 없습니다.",
        )
    try:
        admin_role = await db.prepare(
            "SELECT user_id FROM platform_admin_roles WHERE user_id = ? LIMIT 1"
        ).bind(user_id).first()
    except Exception:
        return _auth_error(
            503,
            "account_delete_unavailable",
            "지금 계정 탈퇴를 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        )
    if admin_role is not None:
        return _auth_error(
            403,
            "account_delete_admin_blocked",
            "관리자 권한이 있는 계정은 이 화면에서 탈퇴할 수 없습니다.",
        )

    # End this session first: a session that cannot be ended leaves every row
    # untouched, so the user can simply retry (same order as password change).
    failure = await _revoke_canonical_session(request)
    if failure is not None:
        return _auth_error(503, failure, "세션을 종료하지 못했습니다. 다시 시도해 주세요.")

    # COM2 owns the PC tables in the queue DB. Clean those rows after the
    # session is revoked and before the Chat DB batch. On queue failure, leave
    # Chat data untouched; a later retry is safe because queue deletes are
    # idempotent. D1 keeps these tables in its own Chat DB batch.
    queue_client = getattr(request.app.state, "queue_client", None)
    include_pc_queue_data = queue_client is None
    if queue_client is not None:
        pairing_store = getattr(request.app.state, "pc_device_pairing_store", None)
        cleanup = getattr(pairing_store, "delete_account_pc_data", None)
        try:
            if not callable(cleanup) or await cleanup(user_id=user_id) is not True:
                raise RuntimeError("queue account cleanup unavailable")
        except Exception:
            return _auth_error(
                503,
                "account_delete_queue_unavailable",
                "PC account data cleanup failed; retry account deletion.",
            )

    try:
        await db.batch(
            _delete_batch(db, user_id, include_pc_queue_data=include_pc_queue_data)
        )
    except Exception:
        # The Chat batch is atomic, so its account and data remain if it fails.
        # A COM2 queue batch may already have committed; it is idempotent, so a
        # new session can retry and finish the Chat batch.
        return _auth_error(
            503,
            "account_delete_failed",
            "계정 탈퇴 처리에 실패했습니다. 데이터는 그대로 남습니다. 다시 로그인한 뒤 다시 시도해 주세요.",
        )

    # Best-effort account-wide canonical revocation (#5441 helper) plus the
    # in-memory derived caches. The deleted user row already refuses every
    # cookie this account ever minted; these clear the leftovers.
    await _revoke_all_canonical_sessions(request, user_id=user_id, strict=False)
    try:
        from .auth_validation_cache import invalidate_auth_cache

        await invalidate_auth_cache(request, user_id=user_id)
    except Exception:
        pass
    try:
        from .pc_scope_cache import invalidate_owner_scope

        invalidate_owner_scope(user_id)
    except Exception:
        pass

    response = JSONResponse({"ok": True})
    response.headers["cache-control"] = "private, no-store"
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response
