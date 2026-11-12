"""Self-service Chat account deletion — Chat DB and COM2 PC queue data (#6659 3).

SCOPE
    The signed-in account's own Chat DB rows and, on COM2, PC queue rows. D1
    keeps the same PC tables inside the Chat DB. Common-login accounts are
    resolved through the durable reverse sources (identity shadow projection
    and account-link cache) as well as the ``shared:`` marker, so an account
    created by direct social login still reaches its common-login withdrawal
    preparation and session revocation. Data outside this database — R2
    objects and prefixes, the workspace's Google connector grants and the
    COM2 file-lane directory — is inventoried BEFORE the batch and committed
    as ``account_deletion_cleanup_pending`` items IN the batch, then drained
    right after it (``account_cleanup_pending``, #7557). A failed item stays
    and is retried; the response says so instead of claiming completion.
    B14 ledgers, offsite backups and the user-PC ``.padiem-backup`` copies
    stay and are recorded as later steps in
    ``docs/operations/ACCOUNT_DELETION_20261103.md``.

WHY EVERY DELETE IS EXPLICIT
    Production D1 does not enforce ``PRAGMA foreign_keys`` and the local
    CPython host deliberately mirrors that (see ``local_cpython.py``), so a
    declared ``ON DELETE CASCADE`` is documentation, not enforcement here.
    Each database is cleaned with one atomic batch. D1 has one Chat batch;
    COM2 cleans its PC queue batch before the Chat batch. Replay-prevention
    rows in oracle_mesh_dispatch are retained without the account in them: the
    row stays, every column that names the person is overwritten.

THE ONE CONFIRMATION
    Deleting an account is irreversible destruction, so the route requires the
    signed-in user to retype their own account email exactly. The email is
    compared to the stored account email; anything else deletes nothing.
"""
from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from starlette.responses import JSONResponse

from .account_cleanup_pending import (
    CleanupPorts,
    collect_cleanup_targets,
    drain as drain_account_cleanup,
    item_id as cleanup_item_id,
    pending_insert_statements,
)
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
from .pc_device_pairing_store import (
    mesh_presence_account_cleanup_statements,
    oracle_mesh_dispatch_identity_cleanup_statements,
)

#: A shared-login Chat account stores its common-login subject as
#: ``provider_subject = 'shared:' + subject`` (``history.upsert_shared_user``).
#: That row is the durable mapping to BookAI's ``subject`` column, so BookAI
#: records can be deleted with the account instead of waiting for a later step.
#: The second mapping source, ``auth_account_link_cache``, is transient and is
#: itself deleted by this batch, so it is read before the batch runs.
_SHARED_SUBJECT_PREFIX = "shared:"
_SUBJECT_RE = re.compile(r"sub_[A-Za-z0-9_-]{1,128}")
_CHAT_PRODUCTS = frozenset({"b62", "b54-padiem-claw"})
_LOVETREE_PRODUCT = "lovetree-4-0"
_AUTH_ACCOUNT_DELETE_URL = "https://auth.padiem.net/internal/account-delete/prepare"
_SERVICE_AT = "x-padiem-service-at"
_SERVICE_ID = "x-padiem-service-id"
_SERVICE_PROOF = "x-padiem-service-proof"

#: #7605: the withdrawal request waits at most this many seconds for the whole
#: external-cleanup drain. Whatever the budget does not cover stays in the
#: ``account_deletion_cleanup_pending`` rows committed with the deletion batch
#: and the daily purge run (``app.expired_purge``) continues it. The deletion
#: batch and the session revocation run before the drain and are not bounded
#: by this: the account is deleted and the login blocked either way.
REQUEST_CLEANUP_BUDGET_SECONDS = 20.0
#: #7605: one external call inside the drain waits at most this many seconds.
#: The file-lane purge already binds itself to 10 s over httpx; this gives the
#: Google authority call and the object-store calls the same cap. A call cut
#: by it counts as a failed attempt, and every handler is idempotent.
REQUEST_CLEANUP_CALL_TIMEOUT_SECONDS = 10.0


class AccountDeleteRpcError(RuntimeError):
    """Closed transport failure. It never retains URL, body, signature or secret."""


async def prune_expired_account_deletion_audit(db, *, now: datetime | None = None) -> int:
    """Remove hash-only deletion audit rows after one year; scheduled worker owns cadence."""
    if db is None or not callable(getattr(db, "prepare", None)):
        return 0
    current = now or datetime.now(timezone.utc)
    cutoff = (current - timedelta(days=365)).isoformat()
    result = await db.prepare(
        "DELETE FROM account_deletion_audit WHERE datetime(deleted_at) <= datetime(?)"
    ).bind(cutoff).run()
    meta = getattr(result, "meta", None)
    changes = meta.get("changes") if isinstance(meta, dict) else None
    return changes if isinstance(changes, int) and changes >= 0 else 0


def _service_proof(secret: str, *, path: str, at: int, service_id: str, body: bytes) -> str:
    signed = b"\n".join(
        (
            b"v2",
            b"POST",
            path.encode("utf-8"),
            str(at).encode("ascii"),
            service_id.encode("utf-8"),
            body,
        )
    )
    return "v2=" + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


async def _signed_rpc_post(request, *, url: str, path: str, payload: dict) -> dict:
    settings = request.app.state.settings
    secret = getattr(settings, "account_delete_rpc_secret", None)
    if not isinstance(secret, str) or len(secret) < 32:
        raise AccountDeleteRpcError("account_delete_rpc_unavailable")
    try:
        parsed = httpx.URL(url)
        if parsed.scheme != "https" or parsed.path != path or parsed.query or parsed.fragment:
            raise ValueError("rpc url mismatch")
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")
        at = int(time.time())
        service_id = str(uuid.uuid4())
        headers = {
            "content-type": "application/json",
            "accept": "application/json",
            _SERVICE_AT: str(at),
            _SERVICE_ID: service_id,
            _SERVICE_PROOF: _service_proof(secret, path=path, at=at, service_id=service_id, body=body),
        }
        transport = getattr(request.app.state, "account_delete_rpc_transport", None)
        if callable(transport):
            response = await transport(url=url, method="POST", path=path, body=body, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
                response = await client.post(url, content=body, headers=headers)
        status = getattr(response, "status_code", None)
        data = response.json() if status == 200 else None
        if status != 200 or not isinstance(data, dict) or data.get("ok") is not True:
            raise AccountDeleteRpcError("account_delete_rpc_failed")
        return data
    except AccountDeleteRpcError:
        raise
    except Exception as exc:
        raise AccountDeleteRpcError("account_delete_rpc_failed") from exc


def _shared_subject(provider_subject: object) -> str | None:
    if not isinstance(provider_subject, str) or not provider_subject.startswith(_SHARED_SUBJECT_PREFIX):
        return None
    subject = provider_subject[len(_SHARED_SUBJECT_PREFIX):]
    return subject if _SUBJECT_RE.fullmatch(subject) else None


async def _shadow_canonical_subject(db, user_id: str) -> str | None:
    """The canonical subject the identity shadow names for this product user.

    The shadow row (migration 007) is the durable projection of every shared
    Control Plane session this account ever had, so it is the reverse basis
    for accounts whose ``provider_subject`` never gained the ``shared:``
    marker. A host without the projection has no such row and therefore no
    subject from this source; any other read failure is raised, never
    reported as "no subject", because that would delete the account while its
    common-login account and sessions survive.
    """
    exists = await db.prepare(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name='control_plane_identity_shadow'"
    ).first()
    if exists is None:
        return None
    row = _row_to_dict(
        await db.prepare(
            "SELECT canonical_subject_id FROM control_plane_identity_shadow"
            " WHERE product_user_id = ?"
        ).bind(user_id).first()
    )
    value = row.get("canonical_subject_id") if row else None
    if not isinstance(value, str) or not _SUBJECT_RE.fullmatch(value):
        return None
    return value


class AccountCleanupUnavailable(RuntimeError):
    """The external-data inventory could not be read; nothing is deleted yet."""


async def _google_workspace_ref(request, user_id: str) -> str | None:
    """The canonical workspace whose Google grants this account holds (#7557).

    Read through the same canonical session every connector path resolves, and
    before any revocation ends that session. ``None`` means the account has no
    canonical session or no minted workspace, so it can hold no Google grant.
    An authority that cannot answer is raised: deleting now would orphan the
    grants, and a retry costs the user nothing because nothing was deleted.
    """
    from .calendar_session_authority import (
        CALENDAR_PATH_ACCOUNT_DELETE,
        CALENDAR_SESSION_UNAVAILABLE,
        resolve_calendar_session,
    )

    state = request.app.state
    identity = getattr(state, "control_plane_identity_authority", None)
    resolve = getattr(identity, "resolve_connector_workspace", None)
    if not callable(resolve) or getattr(state, "identity_shadow_store", None) is None:
        # This host composes no canonical connector session at all, so no
        # connector path on it can have minted a Google grant either.
        print("account_delete google_workspace=none reason=host_unbound", flush=True)
        return None
    session = await resolve_calendar_session(
        request, path=CALENDAR_PATH_ACCOUNT_DELETE, user_id=user_id,
    )
    if not session.resolved:
        if session.reason == CALENDAR_SESSION_UNAVAILABLE:
            raise AccountCleanupUnavailable("canonical session unavailable")
        print(f"account_delete google_workspace=none reason={session.reason}", flush=True)
        return None
    try:
        workspace = resolve(session_id=session.session_id)
        if inspect.isawaitable(workspace):
            workspace = await workspace
    except Exception as exc:
        raise AccountCleanupUnavailable("connector workspace unavailable") from exc
    if workspace is None:
        return None
    if not isinstance(workspace, str) or not workspace:
        raise AccountCleanupUnavailable("connector workspace invalid")
    return workspace


def _account_bucket(request):
    """The one private object store every account prefix lives in."""
    state = request.app.state
    bucket = getattr(getattr(state, "workspace_document_store", None), "r2_bucket", None)
    if bucket is None:
        bucket = getattr(getattr(state, "history_store", None), "full_context_bucket", None)
    return bucket


async def _drain_cleanup(request, db, targets: list[tuple[str, str]]) -> dict[str, int]:
    """Run this deletion's external items now; failures stay pending for retry.

    #7605: the request bounds the drain — ``REQUEST_CLEANUP_BUDGET_SECONDS``
    for the whole pass and ``REQUEST_CLEANUP_CALL_TIMEOUT_SECONDS`` for one
    external call — so a slow store cannot hold the withdrawal response. Items
    the budget does not cover stay pending (they were committed with the
    batch) and the caller still reports them as not finished.
    """
    ids = [cleanup_item_id(kind, target) for kind, target in targets]
    if not ids:
        return {"done": 0, "failed": 0, "waiting": 0, "pending": 0}
    ports = CleanupPorts(
        bucket=_account_bucket(request),
        google=getattr(request.app.state, "google_oauth_workspace_truth", None),
        file_lane=getattr(request.app.state, "file_lane_client", None),
        file_lane_absent_is_done=True,
    )
    try:
        return await drain_account_cleanup(
            db,
            ports,
            item_ids=ids,
            limit=len(ids),
            deadline=time.monotonic() + max(float(REQUEST_CLEANUP_BUDGET_SECONDS), 0.0),
            call_timeout=max(float(REQUEST_CLEANUP_CALL_TIMEOUT_SECONDS), 0.0),
        )
    except Exception:
        # The items are committed; the daily pass picks them up. The caller
        # still reports them as not finished.
        return {"done": 0, "failed": 0, "waiting": 0, "pending": len(ids)}


_CLEANUP_PENDING_MESSAGE = (
    "계정과 서비스 데이터는 삭제했습니다. 저장소에 남은 파일·연결 정리 일부가 아직 끝나지 않아 "
    "자동으로 다시 시도합니다."
)


async def _active_product_links(request, subject_id: str) -> list[dict[str, str]]:
    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    list_links = getattr(authority, "list_active_product_links_for_subject", None)
    if not callable(list_links):
        raise AccountDeleteRpcError("control_plane_identity_unavailable")
    return await list_links(canonical_subject_id=subject_id)


async def _remove_product_link(
    request,
    link: dict[str, str],
    subject_id: str,
    account_deletion_operation_id: str | None,
) -> dict:
    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    remove_link = getattr(authority, "remove_product_link", None)
    if not callable(remove_link):
        raise AccountDeleteRpcError("control_plane_identity_unavailable")
    return await remove_link(
        product_id=link["product_id"],
        product_user_id=link["product_user_id"],
        canonical_subject_id=subject_id,
        account_deletion_operation_id=account_deletion_operation_id,
    )


async def _prepare_auth_account_deletion(request, subject_id: str) -> str:
    operation_id = str(uuid.uuid4())
    result = await _signed_rpc_post(
        request,
        url=_AUTH_ACCOUNT_DELETE_URL,
        path="/internal/account-delete/prepare",
        payload={"account_id": subject_id, "operation_id": operation_id},
    )
    if set(result) != {"ok", "prepared", "revoked_sessions"} or result.get("prepared") is not True:
        raise AccountDeleteRpcError("auth_account_delete_unavailable")
    count = result.get("revoked_sessions")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise AccountDeleteRpcError("auth_account_delete_unavailable")
    return operation_id


async def _finish_auth_account_deletion(request, subject_id: str, operation_id: str) -> None:
    result = await _signed_rpc_post(
        request,
        url="https://auth.padiem.net/internal/account-delete/complete",
        path="/internal/account-delete/complete",
        payload={"account_id": subject_id, "operation_id": operation_id},
    )
    if result != {"ok": True, "deleted": True}:
        raise AccountDeleteRpcError("auth_account_delete_unavailable")


async def _abort_auth_account_deletion(request, subject_id: str, operation_id: str) -> None:
    result = await _signed_rpc_post(
        request,
        url="https://auth.padiem.net/internal/account-delete/abort",
        path="/internal/account-delete/abort",
        payload={"account_id": subject_id, "operation_id": operation_id},
    )
    if result != {"ok": True, "aborted": True}:
        raise AccountDeleteRpcError("auth_account_delete_unavailable")


def bookai_subjects(provider_subject: str | None, link_owner_ids=()) -> tuple[str, ...]:
    """BookAI subjects that belong to this account, in a stable order.

    Two sources are accepted: the durable ``provider_subject`` marker written by
    the shared-login profile upsert, and the account-link cache row (with the
    identity shadow projection passed in the same argument list). Nothing is
    guessed from the email. A subject is only taken when it matches the canonical
    grammar the records API itself enforces (``bookai_records._SUBJECT``).
    """
    found: list[str] = []
    if isinstance(provider_subject, str) and provider_subject.startswith(_SHARED_SUBJECT_PREFIX):
        candidate = provider_subject[len(_SHARED_SUBJECT_PREFIX):]
        if _SUBJECT_RE.fullmatch(candidate):
            found.append(candidate)
    for owner in link_owner_ids:
        if isinstance(owner, str) and _SUBJECT_RE.fullmatch(owner) and owner not in found:
            found.append(owner)
    return tuple(found)


async def _account_link_subjects(db, user_id: str) -> list[str]:
    """Common-login subjects the account-link cache names for this account.

    This binding exposes ``first()`` and ``run()`` only, so the rows are
    flattened into one value instead of read with ``all()``. A host that has not
    applied migration 088 simply has no link table and therefore no link
    subjects; any other read failure is raised, never reported as "no records",
    because that would delete the account while its BookAI records survive.
    """
    exists = await db.prepare(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='auth_account_link_cache'"
    ).first()
    if exists is None:
        return []
    row = await db.prepare(
        "SELECT group_concat(owner_id, '|') AS owners FROM auth_account_link_cache"
        " WHERE product_user_id = ?"
    ).bind(user_id).first()
    joined = (row or {}).get("owners") if isinstance(row, dict) else None
    if not isinstance(joined, str) or not joined:
        return []
    return [part for part in joined.split("|") if part]



#: Tables deleted with ``WHERE <key> = ?`` bound to the account id, in
#: child-before-parent order. Every entry was verified against the migration
#: survey in ``docs/operations/ACCOUNT_DELETION_20261103.md``, and the survey
#: guard test (``test_account_deletion_survey_guard_261111``) re-derives that
#: survey from the migrations so a new user-keyed table cannot ship without
#: joining this list or ``_DELETION_EXCEPTIONS`` below. ``bookai_records`` is
#: absent here because its key is not ``users.id``: it is keyed by the
#: common-login subject, and ``bookai_subjects`` below turns the account into
#: that subject so the records are deleted with the account.
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
    ("claw_approved_memory", "user_id = ?"),
    ("claw_document_metadata", "user_id = ?"),
    # member_id = '' rows are workspace-wide alerts and stay; the account's own
    # rows go (operations doc 2.2, migration 010).
    ("claw_task_alert", "member_id = ?"),
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
    ("padiem_mcp_tokens", "user_id = ?"),
    ("padiem_mcp_approvals", "user_id = ?"),
    ("padiem_mcp_audit", "user_id = ?"),
    ("padiem_mcp_oauth_codes", "user_id = ?"),
    ("claw_artifact_delivery_receipts", "user_id = ?"),
    # One-time LoveTree login evidence binds the pending account by id; the
    # rows expire on their own, but they must not outlive the account.
    ("lovetree_login_handoffs", "pending_user_id = ?"),
    # Identity-result caches name the product user; clear every session's row.
    ("auth_validation_cache", "product_user_id = ?"),
    ("auth_account_link_cache", "product_user_id = ?"),
    ("control_plane_identity_shadow", "product_user_id = ?"),
    # Pending shared-session revocation retry marker (#7078): meaningless once
    # the account is gone, and it would name a deleted user forever.
    ("shared_session_revoke_pending", "user_id = ?"),
    # Same shape and same fate for the external-token revocation retry marker:
    # with the account gone, the retry has nothing left to revoke.
    ("external_token_revoke_pending", "user_id = ?"),
    # Short-lived Claw execute receipt (#7543): it holds the account's last
    # execute reply for the replay window and must not outlive the account.
    ("claw_execute_receipts", "user_id = ?"),
    # #7557: per-account AI usage counters. The account id is deterministic,
    # so a re-signup of the same identity must not inherit the old usage.
    ("live_usage_buckets", "subject_key = ? AND subject_type = 'user'"),
    # #7557: one-time Android sign-in handoffs bound to the account.
    ("padiem_android_auth_handoffs", "pending_user_id = ?"),
)

#: Tables whose rows name the account only through the common-login subject.
#: Every statement runs once per resolved subject (``bookai_subjects``), in the
#: same batch, BEFORE the claw_rules removal that the child chains read. The
#: rule chain is the ownership boundary: scheduled automation (018) is created
#: only by workspace owners, so runs, occurrences and proposals of the
#: account's rules all disappear with the rules.
_SUBJECT_KEYED_TABLES: tuple[tuple[str, str], ...] = (
    ("claw_occurrences",
     "run_id IN (SELECT run_id FROM claw_runs WHERE rule_id IN "
     "(SELECT rule_id FROM claw_rules WHERE canonical_subject_id = ?))"),
    ("claw_runs",
     "rule_id IN (SELECT rule_id FROM claw_rules WHERE canonical_subject_id = ?)"),
    ("claw_proposals",
     "rule_id IN (SELECT rule_id FROM claw_rules WHERE canonical_subject_id = ?)"),
    ("claw_proposals", "approved_by = ?"),
    ("claw_rules", "canonical_subject_id = ?"),
)

#: Live user-keyed tables the batch deliberately does not ``DELETE``, with the
#: reason the survey guard requires. A new user-keyed table ships only by
#: joining ``_USER_KEYED_TABLES`` (or ``_IDENTITY_SCRUBBED_USER_KEYED_TABLES``)
#: or by adding a reasoned entry here.
_DELETION_EXCEPTIONS: dict[str, str] = {
    "users": "계정 행 자체 — 배치의 마지막 문에서 삭제한다.",
    "bookai_records": (
        "user_id 키가 아닌 공통 로그인 subject 키 — "
        "_SUBJECT_KEYED_TABLES와 같은 방식으로 subjects마다 같은 배치에서 삭제한다."
    ),
    "auth_login_abuse_buckets": (
        "계정 키가 아니라 입력된 아이디·접속망의 HMAC 일별 실패 횟수 — 없는 아이디 시도도 같은 표에 "
        "쌓이는 남용 방지 카운터라 계정과 묶을 수 없고, 만료 정리 대상이다."
    ),
    "b66_model_policy_audit": (
        "관리자 행위 감사(actor_user_id) — 관리자 권한 계정은 이 경로로 탈퇴할 수 없다. "
        "권한을 내려놓은 뒤 탈퇴한 관리자의 행위 기록 보존 여부는 대표 결정 사항(#7557 PR)."
    ),
    "central_model_policy_audit": (
        "관리자 행위 감사(actor_user_id) — b66_model_policy_audit와 같은 이유."
    ),
    "central_model_route_audit": (
        "관리자 행위 감사(actor_user_id) — b66_model_policy_audit와 같은 이유."
    ),
    "platform_admin_role_audit": (
        "관리자 권한 부여·회수 감사(actor_user_id·target_user_id) — "
        "b66_model_policy_audit와 같은 이유."
    ),
}

#: Replay-prevention history keeps its rows and loses the person: the batch
#: overwrites every identifying column instead of deleting the dispatch, because
#: that row's presence is what refuses a replayed run or tool call (047·063).
#: ``user_id = ?`` here is the selector the cleanup statements use.
_IDENTITY_SCRUBBED_USER_KEYED_TABLES: tuple[tuple[str, str], ...] = (
    ("oracle_mesh_dispatch", "user_id = ?"),
)
_PC_QUEUE_USER_TABLES = frozenset({
    "pc_pairing_codes", "pc_install_tokens", "pc_device_links",
})


def _delete_batch(
    db,
    user_id: str,
    *,
    include_pc_queue_data: bool = True,
    bookai_subjects: tuple[str, ...] = (),
    cleanup_targets: tuple[tuple[str, str], ...] | list = (),
) -> list:
    """Build the Chat DB batch; COM2 PC rows are deleted by the queue first.

    ``bookai_subjects`` carries the subjects resolved before the batch (see
    ``bookai_subjects`` above). They drive both subject-keyed families deleted
    here, in the same transaction as the account: the BookAI records and the
    claw scheduled-automation chain reference the account only by subject.
    """
    statements: list = []
    # Subject-keyed statements must run before the account-keyed rows remove
    # the mapping tables, and the claw chain reads claw_rules, so it goes
    # before the rules themselves.
    for subject in bookai_subjects:
        statements.extend(
            db.prepare(f"DELETE FROM {table} WHERE {where}").bind(subject)
            for table, where in _SUBJECT_KEYED_TABLES
        )
    # BookAI records: one statement per subject.
    statements.extend(
        db.prepare("DELETE FROM bookai_records WHERE subject = ?").bind(subject)
        for subject in bookai_subjects
    )
    statements.extend(
        db.prepare(f"DELETE FROM {table} WHERE {where}").bind(user_id)
        for table, where in _USER_KEYED_TABLES
        if include_pc_queue_data or table not in _PC_QUEUE_USER_TABLES
    )
    # Presence and the dispatch rows live with the PC queue on COM2 and stay in
    # this batch on D1. Dispatch rows are not deleted: they are made anonymous,
    # because their presence is the replay protection itself.
    if include_pc_queue_data:
        statements.extend(
            oracle_mesh_dispatch_identity_cleanup_statements(db, user_id)
        )
        statements.extend(mesh_presence_account_cleanup_statements(db, user_id))
    deleted_at = datetime.now(timezone.utc).isoformat()
    # #7557: the external work is committed in the same transaction as the
    # rows that indexed it, so neither can exist without the other.
    statements.extend(pending_insert_statements(db, cleanup_targets, now=deleted_at))
    user_id_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    statements.append(
        db.prepare(
            "INSERT INTO account_deletion_audit (user_id_hash, deleted_at) VALUES (?,?) "
            "ON CONFLICT(user_id_hash) DO UPDATE SET deleted_at=excluded.deleted_at"
        ).bind(user_id_hash, deleted_at)
    )
    # The account row itself goes last, after every row that references it.
    statements.append(db.prepare("DELETE FROM users WHERE id = ?").bind(user_id))
    return statements


async def _account_delete(request, *, delete_all_services: bool) -> JSONResponse:
    """Delete Chat data, then unlink the completed product deletion from the authority."""
    if not auth_ready(request):
        return _unavailable()
    user_id = current_user_id(request)
    if not user_id:
        return _auth_error(401, "authentication_required", "로그인이 필요합니다.")
    db = getattr(request.app.state, "account_data_db", None)
    if db is None or not callable(getattr(db, "prepare", None)) or not callable(getattr(db, "batch", None)):
        return _auth_error(503, "account_delete_unavailable", "지금 계정 탈퇴를 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.")

    row = _row_to_dict(
        await db.prepare("SELECT email, provider_subject FROM users WHERE id = ?").bind(user_id).first()
    )
    email = row.get("email") if row else None
    if not isinstance(email, str) or not email:
        return _auth_error(401, "authentication_required", "로그인이 필요합니다.")
    data = await _json_body(request)
    if data is None or set(data) != {"confirm"} or not isinstance(data.get("confirm"), str):
        return _auth_error(400, "invalid_request", "탈퇴 확인 문구를 확인해 주세요. 아무것도 지워지지 않았습니다.")
    if data["confirm"] != email:
        return _auth_error(
            400,
            "account_delete_confirm_mismatch",
            "입력한 이메일이 계정 이메일과 일치하지 않습니다. 아무것도 지워지지 않았습니다.",
        )

    admin_email = str(getattr(request.app.state, "central_admin_google_email", "") or "")
    if admin_email.strip().lower() and email.strip().lower() == admin_email.strip().lower():
        return _auth_error(403, "account_delete_admin_blocked", "중앙 관리자 계정은 이 화면에서 탈퇴할 수 없습니다.")
    try:
        admin_role = await db.prepare(
            "SELECT user_id FROM platform_admin_roles WHERE user_id = ? LIMIT 1"
        ).bind(user_id).first()
    except Exception:
        return _auth_error(503, "account_delete_unavailable", "지금 계정 탈퇴를 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.")
    if admin_role is not None:
        return _auth_error(403, "account_delete_admin_blocked", "관리자 권한이 있는 계정은 이 화면에서 탈퇴할 수 없습니다.")

    # Subject resolution (2026-11-11 audit): an account created by direct
    # social login carries a raw ``provider_subject`` (``history.upsert_google_user``),
    # yet its common-login account exists and its sessions survived deletion
    # because only the ``shared:`` marker drove this flow. The durable reverse
    # sources are the identity shadow projection and the account-link cache,
    # both keyed by product user id; either one selects the same canonical
    # subject the authority already links to this account. The reads happen
    # before any revocation removes the transient link cache rows.
    try:
        link_subjects = await _account_link_subjects(db, user_id)
        shadow_subject = await _shadow_canonical_subject(db, user_id)
    except Exception:
        return _auth_error(503, "account_delete_unavailable", "지금 계정 탈퇴를 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.")
    subjects = bookai_subjects(
        (row or {}).get("provider_subject"),
        [*((shadow_subject,) if shadow_subject else ()), *link_subjects],
    )
    marker_subject = _shared_subject((row or {}).get("provider_subject"))
    subject_id = marker_subject or (subjects[0] if subjects else None)
    # #7557: inventory everything outside this database while the rows that
    # index it (and the canonical session that names the Google workspace)
    # still exist. Nothing has been deleted yet, so a failed read is a plain
    # retry for the user.
    try:
        workspace_ref = await _google_workspace_ref(request, user_id)
        cleanup_targets = await collect_cleanup_targets(
            db, user_id, google_workspace_ref=workspace_ref,
        )
    except Exception:
        return _auth_error(
            503, "account_delete_unavailable",
            "지금 계정 탈퇴를 처리할 수 없습니다. 아무것도 지워지지 않았습니다. 잠시 후 다시 시도해 주세요.",
        )

    links: list[dict[str, str]] = []
    links_to_remove: list[dict[str, str]] = []
    if delete_all_services and subject_id is None:
        return _auth_error(400, "shared_account_required", "공통 로그인 계정으로 로그인한 뒤 요청해 주세요.")
    if subject_id is not None:
        try:
            links = await _active_product_links(request, subject_id)
        except Exception:
            return _auth_error(503, "shared_account_unavailable", "공통 계정 연결을 확인할 수 없습니다. 다시 시도해 주세요.")
        if not links or not any(item["product_id"] in _CHAT_PRODUCTS for item in links):
            if delete_all_services or marker_subject is not None:
                return _auth_error(503, "shared_account_unavailable", "공통 계정 연결을 확인할 수 없습니다. 다시 시도해 주세요.")
            # Reverse-resolved subject with no live authority link: the common
            # account holds nothing of this product to unlink, and its sessions
            # are revoked below by product user id. Data deletion proceeds.
            subject_id = None
    if subject_id is not None:
        known = _CHAT_PRODUCTS | {_LOVETREE_PRODUCT}
        if delete_all_services and any(item["product_id"] not in known for item in links):
            return _auth_error(503, "shared_account_service_unavailable", "연결된 서비스 삭제를 완료할 수 없습니다. 데이터는 유지됩니다.")
        links_to_remove = (
            sorted(links, key=lambda item: 1 if item["product_id"] in _CHAT_PRODUCTS else 0)
            if delete_all_services
            else [item for item in links if item["product_id"] in _CHAT_PRODUCTS]
        )
        if delete_all_services and any(item["product_id"] == _LOVETREE_PRODUCT for item in links):
            settings = request.app.state.settings
            endpoint = getattr(settings, "lovetree_account_delete_url", None)
            if not isinstance(endpoint, str) or not endpoint:
                return _auth_error(503, "shared_account_service_unavailable", "러브트리 삭제 연결이 준비되지 않았습니다. 데이터는 유지됩니다.")
            try:
                result = await _signed_rpc_post(
                    request,
                    url=endpoint,
                    path="/internal/account/delete",
                    payload={"canonical_subject_id": subject_id, "product_id": _LOVETREE_PRODUCT},
                )
                if set(result) != {"ok", "deleted"} or result.get("deleted") is not True:
                    raise AccountDeleteRpcError("lovetree_account_delete_unavailable")
            except Exception:
                return _auth_error(503, "shared_account_service_unavailable", "러브트리 데이터 삭제를 완료하지 못했습니다. 다시 시도해 주세요.")

    failure = await _revoke_canonical_session(request)
    if failure is not None:
        return _auth_error(503, failure, "세션을 종료하지 못했습니다. 다시 시도해 주세요.")

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
                "PC account data 정리를 완료하지 못했습니다. 다시 로그인해 요청해 주세요.",
            )

    try:
        await db.batch(
            _delete_batch(
                db,
                user_id,
                include_pc_queue_data=include_pc_queue_data,
                bookai_subjects=subjects,
                cleanup_targets=cleanup_targets,
            )
        )
    except Exception:
        return _auth_error(
            503,
            "account_delete_failed",
            "계정 데이터 삭제를 완료하지 못했습니다. 저장된 데이터는 유지됩니다. 다시 로그인해 요청해 주세요.",
        )

    # Keep the existing cache cleanup and best-effort account-wide revocation.
    await _revoke_all_canonical_sessions(request, user_id=user_id, strict=False)
    try:
        from .config import session_local_verify_enabled
        from .auth_validation_cache import record_auth_revocation
        if session_local_verify_enabled(getattr(request.app.state, "settings", None)):
            await record_auth_revocation(
                request,
                account_ids=(subject_id,) if isinstance(subject_id, str) and subject_id else (),
                user_ids=(user_id,),
                permanent=True,
            )
    except Exception:
        pass
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

    # #7557: Google grants, R2 objects and the file lane, now. Whatever fails
    # stays committed as a pending item and is retried; the answer says so.
    cleanup = await _drain_cleanup(request, db, cleanup_targets)

    common_account_deleted = False
    if subject_id is not None:
        auth_prepared = False
        auth_operation_id: str | None = None
        for link in links_to_remove:
            try:
                active = await _active_product_links(request, subject_id)
                is_last = (
                    len(active) == 1
                    and active[0]["product_id"] == link["product_id"]
                    and active[0]["product_user_id"] == link["product_user_id"]
                )
                if is_last and not auth_prepared:
                    auth_operation_id = await _prepare_auth_account_deletion(request, subject_id)
                    auth_prepared = True
                result = await _remove_product_link(
                    request, link, subject_id, auth_operation_id
                )
                common_account_deleted = bool(result.get("common_account_deleted"))
                if common_account_deleted:
                    if auth_operation_id is None:
                        raise AccountDeleteRpcError("auth_account_delete_unprepared")
                    await _finish_auth_account_deletion(request, subject_id, auth_operation_id)
                    auth_operation_id = None
            except Exception:
                if auth_operation_id is not None:
                    try:
                        await _abort_auth_account_deletion(request, subject_id, auth_operation_id)
                    except Exception:
                        # Auth's five-minute lease expires even if this compensating RPC is unavailable.
                        pass
                return _auth_error(
                    503,
                    "shared_account_unlink_failed",
                    "서비스 데이터 삭제 뒤 공통 계정 정리를 끝내지 못했습니다. 다시 로그인해 요청해 주세요.",
                )
        if auth_operation_id is not None:
            try:
                await _abort_auth_account_deletion(request, subject_id, auth_operation_id)
            except Exception:
                pass
        if delete_all_services and not common_account_deleted:
            return _auth_error(
                503,
                "shared_account_delete_incomplete",
                "모든 서비스 연결을 정리하지 못했습니다. 다시 로그인해 요청해 주세요.",
            )

    body = {
        "ok": True,
        "common_account_deleted": common_account_deleted,
        "cleanup": {"complete": cleanup["pending"] == 0, "pending": cleanup["pending"]},
    }
    if cleanup["pending"]:
        body["message"] = _CLEANUP_PENDING_MESSAGE
    response = JSONResponse(body)
    response.headers["cache-control"] = "private, no-store"
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


async def account_delete(request) -> JSONResponse:
    return await _account_delete(request, delete_all_services=False)


async def shared_account_delete(request) -> JSONResponse:
    return await _account_delete(request, delete_all_services=True)


_PASSWORD_RPC_DELETE_PATH = "/internal/account-delete"
_PRODUCT_USER_RE = re.compile(r"usr_[A-Za-z0-9_-]{1,79}")


async def chat_account_delete_rpc(request) -> JSONResponse:
    """Signed server-to-server deletion of one Chat account.

    padiem-auth calls this after its account-delete finalize step commits the
    identity tombstone. Deleting the Chat user (and its ``password_credentials``
    row, conversations, projects, files metadata, MCP tokens, PC links and caches)
    matches self-service account deletion and is idempotent: an unknown product
    user id is already deleted.
    """
    from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
    from .password_rpc import _RPC_BODY_LIMIT, _consume_service_id, _verify_service_proof

    settings = getattr(request.app.state, "settings", None)
    secret = getattr(settings, "password_rpc_secret", None)
    store = getattr(request.app.state, "history_store", None)
    db = getattr(request.app.state, "account_data_db", None)
    if (
        not isinstance(secret, str)
        or len(secret) < 32
        or store is None
        or db is None
        or not callable(getattr(db, "prepare", None))
        or not callable(getattr(db, "batch", None))
    ):
        return JSONResponse({"error": {"code": "not_found"}}, status_code=404)
    if request.url.path != _PASSWORD_RPC_DELETE_PATH:
        return JSONResponse({"error": {"code": "not_found"}}, status_code=404)
    try:
        body = await read_bounded_request_body(request, max_bytes=_RPC_BODY_LIMIT)
    except RequestBodyTooLarge:
        return JSONResponse({"error": {"code": "unauthorized"}}, status_code=401)
    verified = _verify_service_proof(
        headers=request.headers,
        path=_PASSWORD_RPC_DELETE_PATH,
        body=body,
        secret=secret,
        now_epoch=int(time.time()),
    )
    if verified is None:
        return JSONResponse({"error": {"code": "unauthorized"}}, status_code=401)
    try:
        if not await _consume_service_id(store, verified["service_id"], verified["at"]):
            return JSONResponse({"error": {"code": "rpc_replay_detected"}}, status_code=409)
    except Exception:
        return JSONResponse({"error": {"code": "account_delete_unavailable"}}, status_code=503)
    payload = verified["payload"]
    if (
        not isinstance(payload, dict)
        or set(payload) != {"product_user_id"}
        or not _PRODUCT_USER_RE.fullmatch(payload.get("product_user_id") or "")
    ):
        return JSONResponse({"error": {"code": "invalid_request"}}, status_code=400)
    user_id = payload["product_user_id"]
    try:
        row = _row_to_dict(
            await db.prepare("SELECT id, provider_subject FROM users WHERE id = ?").bind(user_id).first()
        )
    except Exception:
        return JSONResponse({"error": {"code": "account_delete_unavailable"}}, status_code=503)

    queue_client = getattr(request.app.state, "queue_client", None)
    include_pc_queue_data = queue_client is None
    if queue_client is not None:
        pairing_store = getattr(request.app.state, "pc_device_pairing_store", None)
        cleanup = getattr(pairing_store, "delete_account_pc_data", None)
        try:
            if not callable(cleanup) or await cleanup(user_id=user_id) is not True:
                raise RuntimeError("queue account cleanup unavailable")
        except Exception:
            return JSONResponse({"error": {"code": "account_delete_queue_unavailable"}}, status_code=503)

    if row is None:
        return JSONResponse({"ok": True, "deleted": False, "already_deleted": True})

    try:
        link_subjects = await _account_link_subjects(db, user_id)
        shadow_subject = await _shadow_canonical_subject(db, user_id)
        workspace_ref = await _google_workspace_ref(request, user_id)
        cleanup_targets = await collect_cleanup_targets(
            db, user_id, google_workspace_ref=workspace_ref,
        )
        subjects = bookai_subjects(
            row.get("provider_subject"),
            [*((shadow_subject,) if shadow_subject else ()), *link_subjects],
        )
        await db.batch(
            _delete_batch(
                db,
                user_id,
                include_pc_queue_data=include_pc_queue_data,
                bookai_subjects=subjects,
                cleanup_targets=cleanup_targets,
            )
        )
    except Exception:
        return JSONResponse({"error": {"code": "account_delete_failed"}}, status_code=503)

    await _revoke_all_canonical_sessions(request, user_id=user_id, strict=False)
    try:
        from .config import session_local_verify_enabled
        from .auth_validation_cache import record_auth_revocation
        if session_local_verify_enabled(getattr(request.app.state, "settings", None)):
            await record_auth_revocation(
                request,
                user_ids=(user_id,),
                permanent=True,
            )
    except Exception:
        pass
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
    # Same external cleanup as the self-service route (#7557). The signed
    # caller's answer shape is unchanged; unfinished items stay pending and
    # are retried by the daily pass.
    await _drain_cleanup(request, db, cleanup_targets)
    return JSONResponse({"ok": True, "deleted": True, "already_deleted": False})
