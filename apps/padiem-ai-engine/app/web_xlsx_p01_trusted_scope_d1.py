"""#3580: Engine-independent validation of browser XLSX source ownership.

This adapter requires a privileged read-only binding to the ACTUAL B62 D1
metadata database; it does not trust the B62 request payload and never reads
R2 objects, customer workbook bytes or local files. Not composed by default.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .web_xlsx_p01_tool_binding import TrustedWebXlsxSelectionScope

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_SEL = re.compile(r"^sel_[a-f0-9]{32}$")
_DOC = re.compile(r"^doc_[a-f0-9]{32}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo is not None and result.utcoffset() is not None else None


def _mapping(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    to_py = getattr(row, "to_py", None)
    if callable(to_py):
        row = to_py()
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


class D1WebXlsxTrustedScopeResolver:
    """Read-only verification of exact owner, run, selection and immutable D1 key."""

    def __init__(self, private_b62_metadata_d1: Any, *, required_status: str = "dispatching"):
        if not callable(getattr(private_b62_metadata_d1, "prepare", None)):
            raise ValueError("independent private B62 D1 reader required")
        if required_status not in ("dispatching", "waiting_p01"):
            raise ValueError("unsupported private P01 status")
        self._required_status = required_status
        self._db = private_b62_metadata_d1

    async def __call__(self, selection_ref: str) -> TrustedWebXlsxSelectionScope | None:
        if not isinstance(selection_ref, str) or not _SEL.fullmatch(selection_ref):
            return None
        # All predicates are server-issued table relationships. No client-
        # supplied "owner_id" or "SHA" is used in the SQL.
        sql = (
            "SELECT s.user_id AS owner_id, s.workspace_id AS workspace_id, "
            "s.selection_ref AS selection_ref, s.document_id AS document_id, "
            "s.source_sha256 AS source_sha256, s.filename AS filename, "
            "s.size_bytes AS size_bytes, s.expires_at AS selection_expiry, "
            "s.status AS selection_status, "
            "r.run_id AS run_id, r.status AS request_status, "
            "r.created_at AS dispatch_created, r.source_sha256 AS request_sha, "
            "r.document_id AS request_doc, "
            "h.status AS run_status, h.conversation_id AS conversation_id, "
            "h.updated_at AS run_updated, "
            "m.tenant_id AS tenant_id, m.object_key AS object_key, "
            "m.media_type AS media_type, m.filename AS stored_filename, "
            "m.byte_length AS stored_size, m.expires_at AS original_expiry, "
            "m.deleted_at AS deleted_at "
            "FROM claw_web_xlsx_selections s "
            "JOIN claw_web_xlsx_p01_requests r "
            "ON r.selection_ref=s.selection_ref "
            "AND r.user_id=s.user_id AND r.workspace_id=s.workspace_id "
            "JOIN claw_document_metadata m ON m.document_id=s.document_id "
            "JOIN claw_run_history h ON h.run_id=r.run_id "
            "AND h.user_id=s.user_id AND h.workspace_id=s.workspace_id "
            "WHERE s.selection_ref=? LIMIT 1"
        )
        row = _mapping(await self._db.prepare(sql).bind(selection_ref).first())
        if not row:
            return None
        owner, workspace, run = (row.get(k) for k in ("owner_id", "workspace_id", "run_id"))
        doc, sha = row.get("document_id"), row.get("source_sha256")
        if (not all(isinstance(v, str) and _ID.fullmatch(v)
                    for v in (owner, workspace, run))
                or not isinstance(doc, str) or not _DOC.fullmatch(doc)
                or not isinstance(sha, str) or not _SHA.fullmatch(sha)
                or row.get("selection_ref") != selection_ref
                or row.get("selection_status") != "source_selected_p01_not_started"
                or row.get("request_status") != self._required_status
                or row.get("run_status") != "running"
                or not row.get("conversation_id")
                or row.get("request_sha") != sha or row.get("request_doc") != doc
                or row.get("tenant_id") != workspace
                or row.get("deleted_at") is not None
                or row.get("media_type") != _XLSX
                or row.get("stored_filename") != row.get("filename")
                or type(row.get("size_bytes")) is not int
                or type(row.get("stored_size")) is not int
                or row["size_bytes"] != row["stored_size"]
                or not 0 < row["size_bytes"] <= 1_048_576):
            return None
        key = (
            f"workspaces/{workspace}/claw/web-office/{owner}/{workspace}/"
            f"{doc}/{sha}/{row['filename']}"
        )
        if row.get("object_key") != key:
            return None
        now = datetime.now(timezone.utc)
        dates = [_timestamp(row.get(k)) for k in (
            "selection_expiry", "original_expiry", "dispatch_created", "run_updated"
        )]
        if (any(x is None for x in dates)
                or not all(dates[k] > now for k in (0, 1))
                or not all(now - timedelta(minutes=30) <= dates[k] <= now
                           for k in (2, 3))):
            return None
        return TrustedWebXlsxSelectionScope(
            owner_id=owner, workspace_id=workspace, run_id=run,
            selection_ref=selection_ref, document_id=doc,
            source_sha256=sha, original_immutable=True, source_active=True,
        )
