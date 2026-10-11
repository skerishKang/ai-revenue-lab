"""Durable #3933 web quote write receipts.

Immutable one-shot owner/selection/edit claim BEFORE external Engine call. Never
retry unknown results. A receipt in 'dispatching' does not authorize a write.
"""
from __future__ import annotations

import inspect
import re
from datetime import datetime, timezone
from typing import Any

from .workspace_storage import _row_to_dict

_SEL = re.compile(r"sel_[0-9a-f]{32}")
_DOC = re.compile(r"doc_[0-9a-f]{32}")
_SHA = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:@+-]{0,127}")


async def _wait(value: Any):
    return await value if inspect.isawaitable(value) else value


class WebQuoteWriteReceiptError(ValueError):
    pass


class D1WebQuoteWriteReceiptStore:
    def __init__(self, db: Any):
        if not callable(getattr(db, "prepare", None)):
            raise ValueError("real B62 private D1 required")
        self.db = db

    @staticmethod
    def validate(row: dict[str, Any]):
        if (type(row) is not dict or
                any(type(row.get(k)) is not str or not p.fullmatch(row[k])
                    for k, p in (
                        ("selection_ref", _SEL), ("user_id", _ID),
                        ("workspace_id", _ID), ("run_id", _ID),
                        ("source_document_id", _DOC), ("source_sha256", _SHA),
                        ("workcopy_document_id", _DOC), ("edit_sha256", _SHA),
                    ))
                or type(row.get("school_name")) is not str
                or not 1 <= len(row["school_name"]) <= 120
                or type(row.get("supply_amount")) is not int
                or not 1 <= row["supply_amount"] <= 999999999999):
            raise WebQuoteWriteReceiptError("invalid exact quote write scope")

    async def reserve(self, row: dict[str, Any]):
        self.validate(row)
        now = datetime.now(timezone.utc).isoformat()
        # A competing request may not alter any column or cause a second
        # Engine continuation. Even when the first request outcome is unknown.
        await _wait(self.db.prepare(
            "INSERT INTO claw_web_xlsx_quote_edit_receipts "
            "(selection_ref,user_id,workspace_id,run_id,source_document_id,"
            "source_sha256,workcopy_document_id,edit_sha256,school_name,"
            "supply_amount,state,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,'dispatching',?,?)"
        ).bind(row["selection_ref"], row["user_id"], row["workspace_id"],
               row["run_id"], row["source_document_id"], row["source_sha256"],
               row["workcopy_document_id"], row["edit_sha256"],
               row["school_name"], row["supply_amount"], now, now).run())

    async def load_owner(self, *, owner_id: str, workspace_id: str, selection_ref: str):
        if (type(selection_ref) is not str or not _SEL.fullmatch(selection_ref)
                or type(owner_id) is not str or not _ID.fullmatch(owner_id)
                or type(workspace_id) is not str or not _ID.fullmatch(workspace_id)):
            return None
        row = _row_to_dict(await _wait(self.db.prepare(
            "SELECT selection_ref,user_id,workspace_id,run_id,"
            "source_document_id,source_sha256,workcopy_document_id,"
            "edit_sha256,school_name,supply_amount,state,"
            "revision_document_id,revision_sha256 "
            "FROM claw_web_xlsx_quote_edit_receipts WHERE selection_ref=? "
            "AND user_id=? AND workspace_id=? LIMIT 1"
        ).bind(selection_ref, owner_id, workspace_id).first()))
        return row

    async def commit(self, row: dict[str, Any], revision: dict[str, Any]) -> bool:
        self.validate(row)
        revision_id = revision.get("revision_document_id")
        digest = revision.get("revision_sha256")
        if (type(revision_id) is not str or not _DOC.fullmatch(revision_id)
                or type(digest) is not str or not _SHA.fullmatch(digest)
                or revision.get("edit_sha256") != row["edit_sha256"]
                or revision.get("source_sha256") != row["source_sha256"]
                or revision.get("workcopy_document_id") != row["workcopy_document_id"]
                or revision.get("revised_xlsx_created") is not True
                or revision.get("pdf_exported") is not False):
            return False
        now = datetime.now(timezone.utc).isoformat()
        await _wait(self.db.prepare(
            "UPDATE claw_web_xlsx_quote_edit_receipts SET "
            "state='confirmed',revision_document_id=?,revision_sha256=?,"
            "updated_at=? WHERE selection_ref=? AND user_id=? "
            "AND workspace_id=? AND run_id=? AND source_document_id=? "
            "AND source_sha256=? AND workcopy_document_id=? AND edit_sha256=? "
            "AND school_name=? AND supply_amount=? AND state='dispatching'"
        ).bind(revision_id, digest, now, row["selection_ref"], row["user_id"],
               row["workspace_id"], row["run_id"], row["source_document_id"],
               row["source_sha256"], row["workcopy_document_id"], row["edit_sha256"],
               row["school_name"], row["supply_amount"]).run())
        receipt = await self.load_owner(
            owner_id=row["user_id"], workspace_id=row["workspace_id"],
            selection_ref=row["selection_ref"])
        return bool(receipt and receipt["state"] == "confirmed"
                    and receipt["revision_document_id"] == revision_id
                    and receipt["revision_sha256"] == digest)
