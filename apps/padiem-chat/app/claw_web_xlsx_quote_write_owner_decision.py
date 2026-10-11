"""B62 private owner-specific, one-shot WRITE P01 decision receipt (#3933).

This module is a store primitive; an authenticated web route still must
verify the live Core pause before invoking reserve. The Engine independently
reads D1 from a separate trusted binding. A reserved edit is never consent.
"""
from __future__ import annotations

import inspect
import re
from datetime import datetime, timezone
from typing import Any

from .claw_web_xlsx_quote_write_store import D1WebQuoteWriteReceiptStore
from .workspace_storage import _row_to_dict

_PAUSE = re.compile(r"pause:[0-9a-f]{24,64}")
_CONT = re.compile(r"cont_[A-Za-z0-9_-]{8,123}")
_OUTCOME = frozenset(("approve", "deny"))


async def _wait(value):
    return await value if inspect.isawaitable(value) else value


class D1WebQuoteWriteOwnerDecisionStore:
    def __init__(self, db: Any):
        if not callable(getattr(db, "prepare", None)):
            raise ValueError("B62 private D1 binding is required")
        self.db = db
        self.edits = D1WebQuoteWriteReceiptStore(db)

    async def load_waiting(self, *, owner_id: str, workspace_id: str,
                           selection_ref: str):
        row = await self.edits.load_owner(
            owner_id=owner_id, workspace_id=workspace_id,
            selection_ref=selection_ref,
        )
        return row if row is not None and row.get("state") == "dispatching" else None

    async def reserve(self, *, row: dict[str, Any], pause_id: str,
                      continuation_ref: str, outcome: str) -> None:
        self.edits.validate(row)
        if (outcome not in _OUTCOME
                or type(pause_id) is not str or not _PAUSE.fullmatch(pause_id)
                or type(continuation_ref) is not str
                or not _CONT.fullmatch(continuation_ref)):
            raise ValueError("invalid exact paused WRITE owner decision")
        original = await self.load_waiting(
            owner_id=row["user_id"], workspace_id=row["workspace_id"],
            selection_ref=row["selection_ref"])
        fields = (
            "selection_ref", "user_id", "workspace_id", "run_id",
            "source_document_id", "source_sha256", "workcopy_document_id",
            "edit_sha256", "school_name", "supply_amount",
        )
        if original is None or any(original.get(k) != row.get(k) for k in fields):
            raise ValueError("source or immutable edit changed before WRITE decision")
        now = datetime.now(timezone.utc).isoformat()
        # Unique selection and pause/continuation; no update, upsert or replay.
        await _wait(self.db.prepare(
            "INSERT INTO claw_web_xlsx_quote_write_decisions "
            "(selection_ref,user_id,workspace_id,run_id,source_document_id,"
            "source_sha256,workcopy_document_id,edit_sha256,pause_id,"
            "continuation_ref,outcome,state,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,'dispatching',?,?)"
        ).bind(
            *(row[k] for k in fields[:8]),
            pause_id, continuation_ref, outcome, now, now,
        ).run())

    async def finish(self, *, row: dict[str, Any], pause_id: str,
                     continuation_ref: str, outcome: str,
                     engine_status: str) -> bool:
        self.edits.validate(row)
        if (outcome not in _OUTCOME or
                (outcome == "approve" and engine_status != "confirmed") or
                (outcome == "deny" and engine_status != "denied")):
            return False
        state = "confirmed" if outcome == "approve" else "denied"
        now = datetime.now(timezone.utc).isoformat()
        await _wait(self.db.prepare(
            "UPDATE claw_web_xlsx_quote_write_decisions SET state=?,updated_at=? "
            "WHERE selection_ref=? AND user_id=? AND workspace_id=? "
            "AND run_id=? AND source_document_id=? AND source_sha256=? "
            "AND workcopy_document_id=? AND edit_sha256=? AND pause_id=? "
            "AND continuation_ref=? AND outcome=? AND state='dispatching'"
        ).bind(
            state, now, row["selection_ref"], row["user_id"],
            row["workspace_id"], row["run_id"], row["source_document_id"],
            row["source_sha256"], row["workcopy_document_id"],
            row["edit_sha256"], pause_id, continuation_ref, outcome,
        ).run())
        result = _row_to_dict(await _wait(self.db.prepare(
            "SELECT state FROM claw_web_xlsx_quote_write_decisions "
            "WHERE selection_ref=? AND user_id=? AND workspace_id=? "
            "AND pause_id=? AND continuation_ref=?"
        ).bind(
            row["selection_ref"], row["user_id"], row["workspace_id"],
            pause_id, continuation_ref,
        ).first()))
        return bool(result and result["state"] == state)
