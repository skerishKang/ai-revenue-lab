"""#3580: owner-scoped one-shot decision handoff, not Core grant authority."""
from __future__ import annotations

import inspect
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .claw_web_xlsx_p01_request import _utc, WebXlsxP01RequestError
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
        await _await(self.db.prepare(
            "INSERT INTO claw_web_xlsx_p01_decision_receipts "
            "(request_ref,selection_ref,user_id,workspace_id,run_id,source_sha256,"
            "pause_id,outcome,state,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,'dispatching',?,?)"
        ).bind(waiting["request_ref"], waiting["selection_ref"],
               waiting["user_id"], waiting["workspace_id"], waiting["run_id"],
               waiting["source_sha256"], waiting["pause_id"], outcome, now, now).run())

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
    submission_factory: Any,
) -> str:
    """Reserve before sending. Unknown Engine result is never auto-retried."""
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
    result = await _await(client.resume_owner_decision(
        continuation_ref=waiting["continuation_ref"], submission=submission,
    ))
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
    committed = await _await(store.commit(
        waiting=waiting, outcome=outcome, verified=verified,
    ))
    if committed is not True:
        raise WebXlsxP01RequestError("durable owner decision receipt unavailable")
    return verified
