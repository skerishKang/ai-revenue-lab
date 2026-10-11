"""#3580 web-first owner/workspace XLSX selection ledger (NOT file consent).

Persistent D1 projection of exact original metadata for a future, separately
verified first-party P01 Engine run. This store cannot grant access, consume
an Engine approval, read original bytes, or generate a working copy.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .workspace_storage import WorkspaceStorageError, _row_to_dict

_SELECTION = re.compile(r"^sel_[a-f0-9]{32}$")
_DOC = re.compile(r"^doc_[a-f0-9]{32}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")
_STATUS = "source_selected_p01_not_started"
_TTL = timedelta(minutes=30)
_MAX_PENDING = 20


class WebXlsxSelectionError(WorkspaceStorageError):
    pass


class D1WebXlsxSelectionStore:
    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 selection binding is required")
        self._db = db

    async def _one(self, sql: str, *values: Any) -> dict[str, Any] | None:
        stmt = self._db.prepare(sql).bind(*values)
        row = await stmt.first()
        return _row_to_dict(row)

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        stmt = self._db.prepare(sql).bind(*values)
        result = await stmt.all()
        rows = (result.get("results") if isinstance(result, dict)
                else getattr(result, "results", None))
        if rows is None:
            rows = result
        if not isinstance(rows, (list, tuple)):
            try:
                rows = list(rows)
            except (ValueError, TypeError) as exc:
                raise WebXlsxSelectionError("selection list unavailable") from exc
        result_rows = [_row_to_dict(row) for row in rows]
        if any(row is None for row in result_rows):
            raise WebXlsxSelectionError("selection metadata corrupt")
        return result_rows

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, object]:
        if (not _SELECTION.fullmatch(str(row.get("selection_ref", "")))
                or not _DOC.fullmatch(str(row.get("document_id", "")))
                or not _HASH.fullmatch(str(row.get("source_sha256", "")))
                or row.get("status") != _STATUS):
            raise WebXlsxSelectionError("selection metadata corrupt")
        try:
            size = int(row["size_bytes"])
        except (ValueError, TypeError, KeyError) as exc:
            raise WebXlsxSelectionError("selection metadata corrupt") from exc
        if not 0 < size <= 1_048_576:
            raise WebXlsxSelectionError("selection size corrupt")
        return {
            "selection_ref": row["selection_ref"],
            "document_id": row["document_id"],
            "filename": row["filename"],
            "source_sha256": row["source_sha256"],
            "size_bytes": size,
            "status": _STATUS,
            "expires_at": row["expires_at"],
            "p01_approval_started": False,
            "processing_started": False,
        }

    async def select(self, *, owner_id: str, workspace_id: str,
                     source: dict[str, Any], now: datetime | None = None) -> dict[str, object]:
        # Only source metadata from the owner's trusted private D1 storage
        # is accepted here. The browser can never send a hash or approval.
        if (not isinstance(owner_id, str) or not owner_id
                or not isinstance(workspace_id, str) or not workspace_id
                or not isinstance(source, dict)
                or not _DOC.fullmatch(str(source.get("document_id", "")))
                or not _HASH.fullmatch(str(source.get("source_sha256", "")))
                or source.get("original_immutable") is not True
                or source.get("processing_authorized") is not False):
            raise WebXlsxSelectionError("invalid server-bound source metadata")
        timestamp = now or datetime.now(timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise WebXlsxSelectionError("timezone-aware selection required")
        try:
            source_expiry = datetime.fromisoformat(str(source["expires_at"]).replace("Z", "+00:00"))
            filename = source["filename"]
            size = source["size_bytes"]
        except (KeyError, TypeError, ValueError) as exc:
            raise WebXlsxSelectionError("invalid source metadata") from exc
        if (source_expiry.tzinfo is None or source_expiry.utcoffset() is None
                or source_expiry <= timestamp or type(filename) is not str
                or not filename.lower().endswith(".xlsx")
                or type(size) is not int or not 0 < size <= 1_048_576):
            raise WebXlsxSelectionError("expired or invalid source")
        expires_at = min(source_expiry, timestamp + _TTL)
        stamp = timestamp.isoformat()
        count_row = await self._one(
            "SELECT COUNT(*) AS n FROM claw_web_xlsx_selections "
            "WHERE user_id=? AND workspace_id=? AND expires_at>?",
            owner_id, workspace_id, stamp,
        )
        if count_row is None or int(count_row["n"]) >= _MAX_PENDING:
            raise WebXlsxSelectionError("too many active selections")
        row = {
            "selection_ref": "sel_" + uuid.uuid4().hex,
            "user_id": owner_id, "workspace_id": workspace_id,
            "document_id": source["document_id"],
            "source_sha256": source["source_sha256"],
            "filename": filename, "size_bytes": size,
            "status": _STATUS, "created_at": stamp,
            "expires_at": expires_at.isoformat(),
        }
        stmt = self._db.prepare(
            "INSERT INTO claw_web_xlsx_selections "
            "(selection_ref,user_id,workspace_id,document_id,source_sha256,"
            "filename,size_bytes,status,created_at,expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)"
        ).bind(*(row[k] for k in (
            "selection_ref", "user_id", "workspace_id", "document_id",
            "source_sha256", "filename", "size_bytes", "status",
            "created_at", "expires_at",
        )))
        await stmt.run()
        return self._public(row)

    async def list_owner(self, *, owner_id: str, workspace_id: str,
                         now: datetime | None = None) -> list[dict[str, object]]:
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        rows = await self._all(
            "SELECT selection_ref, document_id, source_sha256, filename,"
            "size_bytes,status,expires_at FROM claw_web_xlsx_selections "
            "WHERE user_id=? AND workspace_id=? AND expires_at>? "
            "ORDER BY created_at DESC,selection_ref DESC LIMIT 20",
            owner_id, workspace_id, timestamp,
        )
        return [self._public(row) for row in rows]

    async def load_owner(self, *, owner_id: str, workspace_id: str,
                         selection_ref: str, now: datetime | None = None) -> dict[str, object] | None:
        if not isinstance(selection_ref, str) or not _SELECTION.fullmatch(selection_ref):
            return None
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        row = await self._one(
            "SELECT selection_ref,document_id,source_sha256,filename,"
            "size_bytes,status,expires_at FROM claw_web_xlsx_selections "
            "WHERE selection_ref=? AND user_id=? AND workspace_id=? AND expires_at>?",
            selection_ref, owner_id, workspace_id, timestamp,
        )
        return self._public(row) if row is not None else None
