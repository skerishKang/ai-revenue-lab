"""#3580: owner-scoped one-shot decision handoff, not Core grant authority."""
from __future__ import annotations

import inspect
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .claw_web_xlsx_p01_request import (
    _utc, WebXlsxP01RequestError, WebXlsxP01RetrySafeDecisionError,
    WebXlsxP01DecisionRetryableError,
)
from .workspace_storage import _row_to_dict

_SEL = re.compile(r"^sel_[0-9a-f]{32}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_PAUSE = re.compile(r"^pause:[0-9a-f]{24,64}$")
_CONT = re.compile(r"^cont_[A-Za-z0-9_-]{8,123}$")
_REQ = re.compile(r"^wpr_[0-9a-f]{32}$")
_OUTCOMES = frozenset({"approve", "deny"})


async def _await(value):
    return await value if inspect.isawaitable(value) else value


class D1WebXlsxP01OwnerDecisionStore:
    """Source+Engine pause scope from signed-in owner, no request-minted grant."""

    def __init__(self, db: Any):
        if not callable(getattr(db, "prepare", None)):
            raise ValueError("private B62 D1 required")
        self.db = db

    async def load_status(
        self, *, owner_id: str, workspace_id: str, selection_ref: str,
    ) -> dict[str, Any] | None:
        """Public-safe status from B62 owner-scoped private D1; no Engine refs."""
        if not isinstance(selection_ref, str) or not _SEL.fullmatch(selection_ref):
            return None
        row = _row_to_dict(await _await(self.db.prepare(
            "SELECT s.selection_ref,s.document_id,s.source_sha256,s.filename,"
            "s.size_bytes,s.status AS selection_status,s.expires_at AS selection_expiry,"
            "p.status AS request_status,p.run_id,p.pause_expires_at,"
            "p.source_sha256 AS request_sha,p.document_id AS request_doc,"
            "p.pause_id AS request_pause_id,d.pause_id AS decision_pause_id,"
            "d.user_id AS decision_owner,d.workspace_id AS decision_workspace,"
            "d.selection_ref AS decision_selection,d.source_sha256 AS decision_sha,"
            "d.state AS decision_state,d.outcome AS decision_outcome,"
            "d.released_at AS decision_released_at "
            "FROM claw_web_xlsx_selections s "
            "LEFT JOIN claw_web_xlsx_p01_requests p "
            "ON p.selection_ref=s.selection_ref AND p.user_id=s.user_id "
            "AND p.workspace_id=s.workspace_id AND p.document_id=s.document_id "
            "LEFT JOIN claw_web_xlsx_p01_decision_receipts d "
            "ON d.request_ref=p.request_ref "
            "WHERE s.selection_ref=? AND s.user_id=? AND s.workspace_id=? LIMIT 1"
        ).bind(selection_ref, owner_id, workspace_id).first()))
        if row is None:
            return None
        now = datetime.now(timezone.utc)
        if (row.get("selection_status") != "source_selected_p01_not_started"
                or not isinstance(row.get("source_sha256"), str)
                or not _SHA.fullmatch(row["source_sha256"])
                or row.get("request_sha") not in (None, row["source_sha256"])
                or row.get("request_doc") not in (None, row["document_id"])):
            raise WebXlsxP01RequestError("selected source or request changed")
        selection_alive = _utc(row["selection_expiry"]) > now
        stage = "not_requested"
        decision = row.get("decision_state")
        # A released reservation was proven NOT consumed by the Engine, so it
        # stops being decision authority: the owner may decide again. This is
        # deliberately narrow -- an armed 'dispatching' row (ambiguous or
        # deterministic failure) keeps its one-shot guard.
        released = row.get("decision_released_at") is not None
        bad_decision_scope = (
            row.get("decision_pause_id") is not None
            and (row.get("decision_pause_id") != row.get("request_pause_id")
                 or row.get("decision_owner") != owner_id
                 or row.get("decision_workspace") != workspace_id
                 or row.get("decision_selection") != selection_ref
                 or row.get("decision_sha") != row["source_sha256"])
        )
        if bad_decision_scope:
            stage = "manual_review"
        elif not selection_alive:
            stage = "expired"
        elif decision == "confirmed" and row.get("decision_outcome") == "approve":
            stage = "confirmed"
        elif decision == "denied" and row.get("decision_outcome") == "deny":
            stage = "denied"
        elif decision == "dispatching" and not released:
            stage = "decision_unknown"
        elif decision is not None and not released:
            stage = "manual_review"
        elif row.get("request_status") == "dispatching":
            stage = "request_unknown"
        elif row.get("request_status") == "waiting_p01":
            if not row.get("pause_expires_at") or _utc(row["pause_expires_at"]) <= now:
                stage = "expired"
            else:
                stage = "waiting_p01"
        elif row.get("request_status") is not None:
            stage = "manual_review"
        return {
            "selection_ref": row["selection_ref"],
            "document_id": row["document_id"],
            "source_sha256": row["source_sha256"],
            "filename": row["filename"],
            "size_bytes": row["size_bytes"],
            "status": stage,
            # Internal-only: the route never projects run_id to the
            # browser. Required for owner/run-scoped workcopy readback.
            "run_id": row.get("run_id") if stage in ("waiting_p01", "confirmed") else None,
        }

    async def load_waiting(self, *, owner_id: str, workspace_id: str,
                           selection_ref: str) -> dict[str, Any] | None:
        if not isinstance(selection_ref, str) or not _SEL.fullmatch(selection_ref):
            return None
        row = _row_to_dict(await _await(self.db.prepare(
            "SELECT p.request_ref,p.selection_ref,p.user_id,p.workspace_id,"
            "p.run_id,p.document_id,p.source_sha256,p.engine_run_id,"
            "p.continuation_ref,p.pause_id,p.pause_expires_at,"
            "s.expires_at AS selection_expiry,s.source_sha256 AS selection_sha "
            "FROM claw_web_xlsx_p01_requests p JOIN claw_web_xlsx_selections s "
            "ON s.selection_ref=p.selection_ref AND s.user_id=p.user_id "
            "AND s.workspace_id=p.workspace_id AND s.document_id=p.document_id "
            "WHERE p.selection_ref=? AND p.user_id=? AND p.workspace_id=? "
            "AND p.status='waiting_p01' AND s.status='source_selected_p01_not_started'"
        ).bind(selection_ref, owner_id, workspace_id).first()))
        if not row:
            return None
        now = datetime.now(timezone.utc)
        if (not isinstance(row.get("request_ref"), str)
                or not _REQ.fullmatch(row["request_ref"])
                or not isinstance(row.get("pause_id"), str)
                or not _PAUSE.fullmatch(row["pause_id"])
                or not isinstance(row.get("continuation_ref"), str)
                or not _CONT.fullmatch(row["continuation_ref"])
                or not isinstance(row.get("source_sha256"), str)
                or not _SHA.fullmatch(row["source_sha256"])
                or row.get("selection_sha") != row["source_sha256"]
                or not now < _utc(row["pause_expires_at"])
                or not now < _utc(row["selection_expiry"])):
            return None
        return row

    async def reserve(self, *, waiting: dict[str, Any], outcome: str) -> None:
        if outcome not in _OUTCOMES or not isinstance(waiting, dict):
            raise WebXlsxP01RequestError("invalid owner P01 decision")
        now = datetime.now(timezone.utc).isoformat()
        scope = (
            waiting["request_ref"], waiting["user_id"], waiting["workspace_id"],
            waiting["run_id"], waiting["selection_ref"], waiting["source_sha256"],
            waiting["pause_id"],
        )
        # Re-arm ONLY a reservation the Engine proved it never consumed. An
        # armed row (ambiguous or deterministic failure) is never re-armed: the
        # INSERT below then fails closed on its primary key.
        rearmed = _row_to_dict(await _await(self.db.prepare(
            "UPDATE claw_web_xlsx_p01_decision_receipts "
            "SET state='dispatching',outcome=?,updated_at=?,released_at=NULL "
            "WHERE request_ref=? AND user_id=? AND workspace_id=? AND run_id=? "
            "AND selection_ref=? AND source_sha256=? AND pause_id=? "
            "AND state='dispatching' AND released_at IS NOT NULL "
            "RETURNING request_ref"
        ).bind(outcome, now, *scope).first()))
        if rearmed:
            return
        await _await(self.db.prepare(
            "INSERT INTO claw_web_xlsx_p01_decision_receipts "
            "(request_ref,selection_ref,user_id,workspace_id,run_id,source_sha256,"
            "pause_id,outcome,state,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,'dispatching',?,?)"
        ).bind(waiting["request_ref"], waiting["selection_ref"],
               waiting["user_id"], waiting["workspace_id"], waiting["run_id"],
               waiting["source_sha256"], waiting["pause_id"], outcome, now, now).run())

    async def release_retry_safe(self, *, waiting: dict[str, Any]) -> bool:
        """Release a retry-safe rejection so the owner may decide again.

        Only the exact armed row for this owner/workspace/run/pause is released,
        and the release is verified before the caller may advertise a retry.
        """
        if not isinstance(waiting, dict):
            return False
        now = datetime.now(timezone.utc).isoformat()
        # Single atomic CAS: only THIS exact armed reservation can be released.
        # UPDATE...RETURNING is the durable proof; a later SELECT could otherwise
        # mistake an already released/stale receipt for this call's own success.
        row = _row_to_dict(await _await(self.db.prepare(
            "UPDATE claw_web_xlsx_p01_decision_receipts "
            "SET released_at=?,updated_at=? "
            "WHERE request_ref=? AND user_id=? AND workspace_id=? AND run_id=? "
            "AND selection_ref=? AND source_sha256=? AND pause_id=? "
            "AND state='dispatching' AND released_at IS NULL "
            "RETURNING request_ref"
        ).bind(now, now, waiting["request_ref"], waiting["user_id"],
               waiting["workspace_id"], waiting["run_id"], waiting["selection_ref"],
               waiting["source_sha256"], waiting["pause_id"]).first()))
        return bool(row and row.get("request_ref") == waiting["request_ref"])

    async def commit(self, *, waiting: dict[str, Any], outcome: str,
                     verified: str) -> bool:
        if (outcome not in _OUTCOMES
                or verified not in ("denied", "confirmed")
                or (outcome == "deny") != (verified == "denied")):
            return False
        now = datetime.now(timezone.utc).isoformat()
        await _await(self.db.prepare(
            "UPDATE claw_web_xlsx_p01_decision_receipts SET state=?,updated_at=? "
            "WHERE request_ref=? AND user_id=? AND workspace_id=? AND run_id=? "
            "AND selection_ref=? AND source_sha256=? AND pause_id=? "
            "AND state='dispatching' AND outcome=?"
        ).bind(verified, now, waiting["request_ref"], waiting["user_id"],
               waiting["workspace_id"], waiting["run_id"],
               waiting["selection_ref"], waiting["source_sha256"],
               waiting["pause_id"], outcome).run())
        row = _row_to_dict(await _await(self.db.prepare(
            "SELECT state FROM claw_web_xlsx_p01_decision_receipts "
            "WHERE request_ref=? AND user_id=? AND workspace_id=? AND pause_id=?"
        ).bind(waiting["request_ref"], waiting["user_id"],
               waiting["workspace_id"], waiting["pause_id"]).first()))
        return bool(row and row.get("state") == verified)


async def dispatch_owner_decision(
    *, waiting: dict[str, Any], outcome: str, store: Any, client: Any,
    submission_factory: Any, approved_workcopy_handler: Any = None,
) -> str | tuple[str, dict[str, Any]]:
    """Reserve before sending. Unknown Engine result is never auto-retried.

    A canonical retry-safe rejection (the Engine proved it did not consume the
    continuation) releases the one-shot reservation so the owner may decide
    again; every other failure keeps it armed.
    """
    if (outcome not in _OUTCOMES or not callable(getattr(store, "reserve", None))
            or not callable(getattr(store, "commit", None))
            or not callable(getattr(client, "resume_owner_decision", None))
            or not callable(submission_factory)):
        raise WebXlsxP01RequestError("owner P01 decision unavailable")
    submission = submission_factory(
        pause_id=waiting["pause_id"], decision=outcome, owner_id=waiting["user_id"],
    )
    # Prevent any B62 source row mutation / Engine call after a duplicate
    # or failed reservation. An unknown response intentionally stays pending.
    await _await(store.reserve(waiting=waiting, outcome=outcome))
    try:
        result = await _await(client.resume_owner_decision(
            continuation_ref=waiting["continuation_ref"], submission=submission,
        ))
    except WebXlsxP01RetrySafeDecisionError:
        # The Engine refused the submission without consuming the stored
        # continuation, so no Engine state was consumed and the owner may decide
        # again. Release the one-shot reservation -- never automatically, and
        # only when the release is durably verified. An unverified release
        # falls back to the armed one-shot guard.
        release = getattr(store, "release_retry_safe", None)
        try:
            released = (
                await _await(release(waiting=waiting)) if callable(release) else False
            )
        except Exception:
            # A missing release capability (or an unmigrated column) must never
            # weaken the one-shot guard: fall back to the armed reservation.
            released = False
        if released is not True:
            raise
        raise WebXlsxP01DecisionRetryableError(
            "retry-safe Engine rejection released the owner decision reservation"
        ) from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise WebXlsxP01RequestError("Engine did not provide a verified decision result")
    if outcome == "deny":
        if result.get("status") != "denied":
            raise WebXlsxP01RequestError("Engine denial not confirmed")
        verified = "denied"
    else:
        if result.get("status") != "confirmed":
            raise WebXlsxP01RequestError("Engine intent confirmation unavailable")
        verified = "confirmed"
    # Do not persist a completed approval when an opt-in processing consumer
    # cannot prove that the private Engine ToolRuntime output is for this
    # exact original. Unknown results remain a one-shot dispatch reservation.
    if verified == "confirmed" and approved_workcopy_handler is not None:
        if (result.get("verified_source_sha256") != waiting["source_sha256"]
                or not _SHA.fullmatch(waiting["source_sha256"])):
            raise WebXlsxP01RequestError("Engine original read grant scope mismatch")
    committed = await _await(store.commit(
        waiting=waiting, outcome=outcome, verified=verified,
    ))
    if committed is not True:
        raise WebXlsxP01RequestError("durable owner decision receipt unavailable")
    # A true Core/Engine confirmation is scope-bound to the immutable source
    # before any processing read. The separate one-shot workcopy lane may
    # consume it only AFTER the owner decision is durably confirmed.
    if verified == "confirmed" and approved_workcopy_handler is not None:
        if not callable(approved_workcopy_handler):
            raise WebXlsxP01RequestError("trusted workcopy handler unavailable")
        copy = await _await(approved_workcopy_handler(
            waiting=waiting, verified_source_sha256=result["verified_source_sha256"],
        ))
        if not isinstance(copy, dict) or copy.get("workcopy_created") is not True:
            raise WebXlsxP01RequestError("approved workcopy not durable")
        return verified, copy
    return verified
