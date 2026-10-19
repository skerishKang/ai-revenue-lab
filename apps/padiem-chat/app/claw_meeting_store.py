"""#4647 owner-scoped meeting record ledger (metadata only, no media bytes).

Reuses the canonical B62 D1 and the existing signed-in owner/workspace authority.
This store cannot reach Google Drive, mint an upload session, start a recording,
register a Calendar event or approve anything: it only persists which meeting
exists, which mode it used, where its outputs are kept, and which follow-up
candidates were extracted. `registered` is reserved for the verified Calendar
path and is refused here on purpose.
"""
from __future__ import annotations

import inspect
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .workspace_storage import _row_to_dict

_MEETING_REF = re.compile(r"^mtg_[0-9a-f]{32}$")
_ARTIFACT_REF = re.compile(r"^mfa_[0-9a-f]{32}$")
_ACTION_REF = re.compile(r"^mct_[0-9a-f]{32}$")
_DRIVE_FILE_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_MODES = frozenset({"record", "transcribe", "both"})
_MEETING_STATUS = frozenset({"active", "ended", "discarded"})
_ARTIFACT_KINDS = frozenset({"audio", "transcript", "minutes"})
_ARTIFACT_STATES = frozenset({"local_only", "drive_saved", "drive_failed"})
_ACTION_KINDS = frozenset({"decision", "followup"})
_ACTION_STATUS = frozenset({"candidate", "confirmed", "dismissed"})
_DUE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_TITLE = 200
_MAX_SUMMARY = 500
_MAX_OWNER_LABEL = 120
_MAX_LIST = 50


class MeetingRecordError(ValueError):
    pass


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _owner(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise MeetingRecordError("meeting owner required")
    return value


def _workspace(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise MeetingRecordError("meeting workspace required")
    return value


def _text(value: Any, limit: int, label: str) -> str:
    if not isinstance(value, str) or not (1 <= len(value.strip()) <= limit):
        raise MeetingRecordError(f"invalid meeting {label}")
    return value.strip()


class D1ClawMeetingStore:
    """D1 projection of the meeting ledger, always filtered by owner AND workspace."""

    def __init__(self, db: Any):
        if not callable(getattr(db, "prepare", None)):
            raise ValueError("private B62 D1 required")
        self.db = db

    async def _one(self, sql: str, *values: Any) -> dict[str, Any] | None:
        return _row_to_dict(await _await(self.db.prepare(sql).bind(*values).first()))

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        result = await _await(self.db.prepare(sql).bind(*values).all())
        rows = (result.get("results") if isinstance(result, dict)
                else getattr(result, "results", None))
        if rows is None:
            rows = result
        if not isinstance(rows, (list, tuple)):
            raise MeetingRecordError("meeting list unavailable")
        return [_row_to_dict(row) for row in rows]

    async def _run(self, sql: str, *values: Any) -> None:
        await _await(self.db.prepare(sql).bind(*values).run())

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, object]:
        if (not isinstance(row.get("meeting_ref"), str)
                or not _MEETING_REF.fullmatch(row["meeting_ref"])
                or row.get("mode") not in _MODES
                or row.get("status") not in _MEETING_STATUS):
            raise MeetingRecordError("meeting record corrupt")
        return {
            "meeting_ref": row["meeting_ref"],
            "title": row.get("title"),
            "mode": row["mode"],
            "status": row["status"],
            "started_at": row.get("started_at"),
            "ended_at": row.get("ended_at"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    async def create(self, *, owner_id: str, workspace_id: str, title: str,
                     mode: str, now: str | None = None) -> dict[str, object]:
        owner, workspace = _owner(owner_id), _workspace(workspace_id)
        if mode not in _MODES:
            raise MeetingRecordError("invalid meeting mode")
        stamp = now or _now()
        row = {
            "meeting_ref": "mtg_" + uuid.uuid4().hex,
            "user_id": owner, "workspace_id": workspace,
            "title": _text(title, _MAX_TITLE, "title"), "mode": mode,
            "status": "active", "started_at": stamp, "ended_at": None,
            "created_at": stamp, "updated_at": stamp,
        }
        await self._run(
            "INSERT INTO claw_meetings (meeting_ref,user_id,workspace_id,title,mode,"
            "status,started_at,ended_at,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            *(row[k] for k in ("meeting_ref", "user_id", "workspace_id", "title", "mode",
                               "status", "started_at", "ended_at", "created_at", "updated_at")))
        return self._public(row)

    async def list_owner(self, *, owner_id: str, workspace_id: str,
                         limit: int = 20) -> list[dict[str, object]]:
        owner, workspace = _owner(owner_id), _workspace(workspace_id)
        size = limit if isinstance(limit, int) and 1 <= limit <= _MAX_LIST else 20
        rows = await self._all(
            "SELECT meeting_ref,title,mode,status,started_at,ended_at,created_at,updated_at "
            "FROM claw_meetings WHERE user_id=? AND workspace_id=? AND status<>'discarded' "
            "ORDER BY updated_at DESC,meeting_ref DESC LIMIT ?",
            owner, workspace, size)
        return [self._public(row) for row in rows]

    async def load(self, *, owner_id: str, workspace_id: str,
                   meeting_ref: str) -> dict[str, object] | None:
        if not isinstance(meeting_ref, str) or not _MEETING_REF.fullmatch(meeting_ref):
            return None
        row = await self._one(
            "SELECT meeting_ref,title,mode,status,started_at,ended_at,created_at,updated_at "
            "FROM claw_meetings WHERE meeting_ref=? AND user_id=? AND workspace_id=? LIMIT 1",
            meeting_ref, _owner(owner_id), _workspace(workspace_id))
        return self._public(row) if row is not None else None

    async def rename(self, *, owner_id: str, workspace_id: str, meeting_ref: str,
                     title: str, now: str | None = None) -> bool:
        wanted = _text(title, _MAX_TITLE, "title")
        owner, workspace = _owner(owner_id), _workspace(workspace_id)
        current = await self.load(owner_id=owner, workspace_id=workspace,
                                  meeting_ref=meeting_ref)
        if current is None or current.get("status") == "discarded":
            return False
        await _await(self.db.prepare(
            "UPDATE claw_meetings SET title=?,updated_at=? "
            "WHERE meeting_ref=? AND user_id=? AND workspace_id=? AND status<>'discarded'"
        ).bind(wanted, now or _now(), meeting_ref, owner, workspace).run())
        # Read back the scoped row: a mutation is only reported when the ledger
        # itself now carries the requested title.
        row = await self.load(owner_id=owner, workspace_id=workspace,
                              meeting_ref=meeting_ref)
        return bool(row and row.get("title") == wanted)

    async def finish(self, *, owner_id: str, workspace_id: str, meeting_ref: str,
                     ended_at: str | None = None, discard: bool = False,
                     now: str | None = None) -> bool:
        """End an active session, or discard it. Never reopens or double-ends one."""
        stamp = now or _now()
        wanted = "discarded" if discard else "ended"
        owner, workspace = _owner(owner_id), _workspace(workspace_id)
        current = await self.load(owner_id=owner, workspace_id=workspace,
                                  meeting_ref=meeting_ref)
        if current is None or current.get("status") != "active":
            return False
        await _await(self.db.prepare(
            "UPDATE claw_meetings SET status=?,ended_at=?,updated_at=? "
            "WHERE meeting_ref=? AND user_id=? AND workspace_id=? AND status='active'"
        ).bind(wanted, ended_at or stamp, stamp, meeting_ref, owner, workspace).run())
        row = await self._one(
            "SELECT status,ended_at FROM claw_meetings "
            "WHERE meeting_ref=? AND user_id=? AND workspace_id=? LIMIT 1",
            meeting_ref, owner, workspace)
        return bool(row and row.get("status") == wanted and row.get("ended_at"))

    async def delete(self, *, owner_id: str, workspace_id: str,
                     meeting_ref: str) -> bool:
        """Remove the ledger rows only. Drive files are a separate, explicit boundary."""
        owner, workspace = _owner(owner_id), _workspace(workspace_id)
        meeting = await self.load(owner_id=owner, workspace_id=workspace,
                                  meeting_ref=meeting_ref)
        if meeting is None:
            return False
        await self._run("DELETE FROM claw_meeting_actions WHERE meeting_ref=? AND user_id=? "
                        "AND workspace_id=?", meeting_ref, owner, workspace)
        await self._run("DELETE FROM claw_meeting_artifacts WHERE meeting_ref=? AND user_id=? "
                        "AND workspace_id=?", meeting_ref, owner, workspace)
        await _await(self.db.prepare(
            "DELETE FROM claw_meetings WHERE meeting_ref=? AND user_id=? AND workspace_id=?"
        ).bind(meeting_ref, owner, workspace).run())
        return await self.load(owner_id=owner, workspace_id=workspace,
                               meeting_ref=meeting_ref) is None

    async def put_artifact(self, *, owner_id: str, workspace_id: str, meeting_ref: str,
                           kind: str, state: str, drive_file_id: str | None = None,
                           filename: str, mime_type: str | None = None,
                           byte_size: int | None = None,
                           now: str | None = None) -> dict[str, object]:
        """Persist one reference per (meeting, kind); the latest receipt replaces the previous."""
        owner, workspace = _owner(owner_id), _workspace(workspace_id)
        if kind not in _ARTIFACT_KINDS or state not in _ARTIFACT_STATES:
            raise MeetingRecordError("invalid meeting artifact classification")
        meeting = await self.load(owner_id=owner, workspace_id=workspace,
                                  meeting_ref=meeting_ref)
        if meeting is None:
            raise MeetingRecordError("meeting not found")
        if (state == "drive_saved") != (drive_file_id is not None):
            raise MeetingRecordError("drive receipt and artifact state disagree")
        if drive_file_id is not None and (not isinstance(drive_file_id, str)
                                          or not _DRIVE_FILE_ID.fullmatch(drive_file_id)):
            raise MeetingRecordError("invalid Drive file id")
        if byte_size is not None and (type(byte_size) is not int
                                      or not 1 <= byte_size <= 188743680):
            raise MeetingRecordError("invalid artifact size")
        stamp = now or _now()
        ref = "mfa_" + uuid.uuid4().hex
        await self._run(
            "INSERT INTO claw_meeting_artifacts (artifact_ref,meeting_ref,user_id,workspace_id,"
            "kind,state,drive_file_id,filename,mime_type,byte_size,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(meeting_ref,kind) DO UPDATE SET state=excluded.state,"
            "drive_file_id=excluded.drive_file_id,filename=excluded.filename,"
            "mime_type=excluded.mime_type,byte_size=excluded.byte_size,"
            "updated_at=excluded.updated_at",
            ref, meeting_ref, owner, workspace, kind, state, drive_file_id,
            _text(filename, 200, "artifact filename"), mime_type, byte_size, stamp, stamp)
        row = await self._one(
            "SELECT artifact_ref,kind,state,drive_file_id,filename,mime_type,byte_size,"
            "created_at,updated_at FROM claw_meeting_artifacts "
            "WHERE meeting_ref=? AND kind=? AND user_id=? AND workspace_id=? LIMIT 1",
            meeting_ref, kind, owner, workspace)
        if row is None:
            raise MeetingRecordError("meeting artifact write unconfirmed")
        return row

    async def list_artifacts(self, *, owner_id: str, workspace_id: str,
                             meeting_ref: str) -> list[dict[str, Any]]:
        return await self._all(
            "SELECT artifact_ref,kind,state,drive_file_id,filename,mime_type,byte_size,"
            "created_at,updated_at FROM claw_meeting_artifacts "
            "WHERE meeting_ref=? AND user_id=? AND workspace_id=? "
            "ORDER BY kind ASC", meeting_ref, _owner(owner_id), _workspace(workspace_id))

    async def add_action(self, *, owner_id: str, workspace_id: str, meeting_ref: str,
                         kind: str, summary: str, owner_label: str | None = None,
                         due_date: str | None = None, evidence_start: int | None = None,
                         evidence_end: int | None = None,
                         now: str | None = None) -> dict[str, object]:
        owner, workspace = _owner(owner_id), _workspace(workspace_id)
        if kind not in _ACTION_KINDS:
            raise MeetingRecordError("invalid meeting action kind")
        if await self.load(owner_id=owner, workspace_id=workspace,
                           meeting_ref=meeting_ref) is None:
            raise MeetingRecordError("meeting not found")
        if due_date is not None and (not isinstance(due_date, str)
                                     or not _DUE_DATE.fullmatch(due_date)):
            raise MeetingRecordError("invalid meeting action due date")
        if evidence_start is not None or evidence_end is not None:
            if (type(evidence_start) is not int or type(evidence_end) is not int
                    or evidence_start < 0 or evidence_end <= evidence_start):
                raise MeetingRecordError("invalid transcript evidence range")
        stamp = now or _now()
        row = {
            "action_ref": "mct_" + uuid.uuid4().hex, "meeting_ref": meeting_ref,
            "user_id": owner, "workspace_id": workspace, "kind": kind,
            "summary": _text(summary, _MAX_SUMMARY, "action summary"),
            "owner_label": (None if owner_label is None
                            else _text(owner_label, _MAX_OWNER_LABEL, "action owner")),
            "due_date": due_date, "status": "candidate",
            "evidence_offset_start": evidence_start, "evidence_offset_end": evidence_end,
            "created_at": stamp, "updated_at": stamp,
        }
        await self._run(
            "INSERT INTO claw_meeting_actions (action_ref,meeting_ref,user_id,workspace_id,"
            "kind,summary,owner_label,due_date,status,evidence_offset_start,"
            "evidence_offset_end,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            *(row[k] for k in ("action_ref", "meeting_ref", "user_id", "workspace_id", "kind",
                               "summary", "owner_label", "due_date", "status",
                               "evidence_offset_start", "evidence_offset_end",
                               "created_at", "updated_at")))
        return {k: row[k] for k in ("action_ref", "kind", "summary", "owner_label",
                                    "due_date", "status", "evidence_offset_start",
                                    "evidence_offset_end", "created_at", "updated_at")}

    async def list_actions(self, *, owner_id: str, workspace_id: str,
                           meeting_ref: str) -> list[dict[str, Any]]:
        return await self._all(
            "SELECT action_ref,kind,summary,owner_label,due_date,status,"
            "evidence_offset_start,evidence_offset_end,created_at,updated_at "
            "FROM claw_meeting_actions WHERE meeting_ref=? AND user_id=? AND workspace_id=? "
            "ORDER BY created_at ASC,action_ref ASC",
            meeting_ref, _owner(owner_id), _workspace(workspace_id))

    async def decide_action(self, *, owner_id: str, workspace_id: str, action_ref: str,
                            status: str, now: str | None = None) -> bool:
        """Only the human states move here; `registered` belongs to the Calendar path."""
        if status not in _ACTION_STATUS:
            raise MeetingRecordError("meeting action status not settable")
        if not isinstance(action_ref, str) or not _ACTION_REF.fullmatch(action_ref):
            return False
        owner, workspace = _owner(owner_id), _workspace(workspace_id)
        current = await self._one(
            "SELECT status FROM claw_meeting_actions WHERE action_ref=? AND user_id=? "
            "AND workspace_id=? LIMIT 1", action_ref, owner, workspace)
        if current is None or current.get("status") != "candidate":
            return False
        await _await(self.db.prepare(
            "UPDATE claw_meeting_actions SET status=?,updated_at=? "
            "WHERE action_ref=? AND user_id=? AND workspace_id=? AND status='candidate'"
        ).bind(status, now or _now(), action_ref, owner, workspace).run())
        row = await self._one(
            "SELECT status FROM claw_meeting_actions WHERE action_ref=? AND user_id=? "
            "AND workspace_id=? LIMIT 1", action_ref, owner, workspace)
        return bool(row and row.get("status") == status)

    async def delete_action(self, *, owner_id: str, workspace_id: str,
                            action_ref: str) -> bool:
        if not isinstance(action_ref, str) or not _ACTION_REF.fullmatch(action_ref):
            return False
        owner, workspace = _owner(owner_id), _workspace(workspace_id)
        row = await self._one(
            "SELECT action_ref FROM claw_meeting_actions WHERE action_ref=? AND user_id=? "
            "AND workspace_id=? LIMIT 1", action_ref, owner, workspace)
        if row is None:
            return False
        await _await(self.db.prepare(
            "DELETE FROM claw_meeting_actions WHERE action_ref=? AND user_id=? "
            "AND workspace_id=?"
        ).bind(action_ref, owner, workspace).run())
        return await self._one(
            "SELECT action_ref FROM claw_meeting_actions WHERE action_ref=? AND user_id=? "
            "AND workspace_id=? LIMIT 1", action_ref, owner, workspace) is None
