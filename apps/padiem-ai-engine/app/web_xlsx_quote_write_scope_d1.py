"""Engine-owned independent B62 D1 READ-ONLY scope verification for #3933.

A B62 'write_enabled' flag, client-provided SHA, or claimed Core response
never count as authority. This checks one exact durable reserved edit, source
READ receipt, original and private workcopy, and active owner run.
No R2 reads or customer document bytes.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from typing import Any

from .web_xlsx_p01_trusted_scope_d1 import _mapping, _timestamp
from .web_xlsx_quote_write_tool_binding import TrustedQuoteWriteScope, _SEL

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class D1WebQuoteWriteScopeResolver:
    def __init__(self, private_b62_d1: Any):
        if not callable(getattr(private_b62_d1, "prepare", None)):
            raise ValueError("read-only independent B62 D1 binding required")
        self._db = private_b62_d1

    async def __call__(self, selection_ref: str) -> TrustedQuoteWriteScope | None:
        if type(selection_ref) is not str or not _SEL.fullmatch(selection_ref):
            return None
        sql = (
            "SELECT e.selection_ref,e.user_id,e.workspace_id,e.run_id,"
            "e.source_document_id,e.source_sha256,e.workcopy_document_id,"
            "e.edit_sha256,e.school_name,e.supply_amount,e.state,"
            "e.created_at AS edit_created,"
            "s.document_id AS selected_doc,s.source_sha256 AS selected_sha,"
            "s.filename,s.size_bytes,s.expires_at AS selection_expires,"
            "r.status AS read_request_status,"
            "d.outcome AS read_outcome,d.state AS read_state,"
            "h.status AS run_status,h.conversation_id,h.updated_at AS run_updated,"
            "o.object_key AS original_key,o.byte_length AS original_size,"
            "o.media_type AS original_media,o.tenant_id AS original_tenant,"
            "o.expires_at AS original_expires,o.deleted_at AS original_deleted,"
            "c.object_key AS copy_key,c.media_type AS copy_media,"
            "c.tenant_id AS copy_tenant,c.expires_at AS copy_expires,"
            "c.deleted_at AS copy_deleted,c.byte_length AS copy_size "
            "FROM claw_web_xlsx_quote_edit_receipts e "
            "JOIN claw_web_xlsx_selections s ON "
            "s.selection_ref=e.selection_ref AND s.user_id=e.user_id "
            "AND s.workspace_id=e.workspace_id "
            "JOIN claw_web_xlsx_p01_requests r ON "
            "r.selection_ref=e.selection_ref AND r.user_id=e.user_id "
            "AND r.workspace_id=e.workspace_id AND r.run_id=e.run_id "
            "AND r.document_id=e.source_document_id "
            "AND r.source_sha256=e.source_sha256 "
            "JOIN claw_web_xlsx_p01_decision_receipts d ON "
            "d.request_ref=r.request_ref AND d.selection_ref=e.selection_ref "
            "AND d.user_id=e.user_id AND d.workspace_id=e.workspace_id "
            "AND d.run_id=e.run_id AND d.source_sha256=e.source_sha256 "
            "JOIN claw_run_history h ON h.run_id=e.run_id "
            "AND h.user_id=e.user_id AND h.workspace_id=e.workspace_id "
            "JOIN claw_document_metadata o ON o.document_id=e.source_document_id "
            "JOIN claw_document_metadata c ON c.document_id=e.workcopy_document_id "
            "WHERE e.selection_ref=? LIMIT 1"
        )
        got = self._db.prepare(sql).bind(selection_ref).first()
        got = await got if inspect.isawaitable(got) else got
        row = _mapping(got)
        if not row:
            return None
        owner, workspace, run = (row.get(k) for k in ("user_id", "workspace_id", "run_id"))
        original = row.get("source_document_id")
        workcopy = row.get("workcopy_document_id")
        sha = row.get("source_sha256")
        selected_name = row.get("filename")
        orig_key = f"workspaces/{workspace}/claw/web-office/{owner}/{workspace}/{original}/{sha}/{selected_name}"
        copy_key = (
            f"workspaces/{workspace}/claw/web-office-workcopies/"
            f"{owner}/{workspace}/{run}/{original}/{workcopy}/{sha}"
        )
        if (row.get("state") != "dispatching"
                or row.get("selected_doc") != original
                or row.get("selected_sha") != sha
                or row.get("read_request_status") != "waiting_p01"
                or row.get("read_outcome") != "approve"
                or row.get("read_state") != "confirmed"
                or row.get("run_status") != "running"
                or not row.get("conversation_id")
                or row.get("original_tenant") != workspace
                or row.get("copy_tenant") != workspace
                or row.get("original_media") != _XLSX or row.get("copy_media") != _XLSX
                or row.get("original_deleted") is not None
                or row.get("copy_deleted") is not None
                or row.get("original_key") != orig_key or row.get("copy_key") != copy_key
                or type(row.get("size_bytes")) is not int
                or not 0 < row["size_bytes"] <= 1_048_576
                or row.get("original_size") != row["size_bytes"]
                or row.get("copy_size") != row["size_bytes"]):
            return None
        now = datetime.now(timezone.utc)
        dates = [_timestamp(row.get(k)) for k in (
            "selection_expires", "original_expires", "copy_expires",
            "edit_created", "run_updated",
        )]
        if (any(t is None for t in dates)
                or not all(t > now for t in dates[:3])
                or not all(now - timedelta(minutes=30) <= t <= now
                           for t in dates[3:])):
            return None
        try:
            return TrustedQuoteWriteScope(
                owner_id=owner, workspace_id=workspace, run_id=run,
                selection_ref=selection_ref,
                source_document_id=original, source_sha256=sha,
                workcopy_document_id=workcopy, workcopy_sha256=sha,
                edit_sha256=row["edit_sha256"],
                school_name=row["school_name"],
                supply_amount=row["supply_amount"],
                write_reserved=True, source_immutable=True,
                workcopy_private=True, run_active=True,
            )
        except (TypeError, ValueError, KeyError):
            return None
