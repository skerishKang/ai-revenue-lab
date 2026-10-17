"""#4647 meeting record API — the sidebar page and Claw dialogue share one ledger.

Authority is the existing signed-in B62 session plus the server-resolved workspace;
the browser never sends an owner id, workspace, Drive account or approval. Deleting a
record removes PADIEM ledger rows only and says so: a Google Drive file is a separate
boundary that this route neither sees nor claims to have deleted.
"""
from __future__ import annotations

import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .claw_meeting_store import (
    D1ClawMeetingStore, MeetingRecordError,
)
from .claw_memory_routes import _resolve_memory_workspace
from .same_origin_guard import expected_browser_origin

MEETINGS_PATH = "/api/claw/meetings"
MEETING_PATH = "/api/claw/meetings/{meeting_ref}"
MEETING_END_PATH = "/api/claw/meetings/{meeting_ref}/end"
MEETING_ARTIFACT_PATH = "/api/claw/meetings/{meeting_ref}/artifacts"
MEETING_ACTIONS_PATH = "/api/claw/meetings/{meeting_ref}/actions"
MEETING_ACTION_PATH = "/api/claw/meeting-actions/{action_ref}"

_CONTRACT = "claw-meeting-records.v1"
_MEETING_REF = re.compile(r"^mtg_[0-9a-f]{32}$")
_ACTION_REF = re.compile(r"^mct_[0-9a-f]{32}$")
_DRIVE_FILE_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_MODES = ("record", "transcribe", "both")
_ARTIFACT_KINDS = ("audio", "transcript", "minutes")
_ARTIFACT_STATES = ("local_only", "drive_saved", "drive_failed")
_ACTION_KINDS = ("decision", "followup")
_ACTION_STATUS = ("candidate", "confirmed", "dismissed")
_MAX_JSON_BYTES = 4096
_NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache",
             "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code}},
                        status_code=status, headers=_NO_STORE)


def _safe_filename(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not 1 <= len(name) <= 200 or "/" in name or "\\" in name:
        return None
    if any(ord(char) < 0x20 or ord(char) == 0x7f for char in name):
        return None
    return name


async def _authority(request: Request):
    """Existing session + server-owned workspace + configured ledger, or a bounded verdict."""
    if not auth_ready(request):
        return _error(401, "authentication_required")
    owner = current_user_id(request)
    if not isinstance(owner, str) or not owner:
        return _error(401, "authentication_required")
    if request.headers.get("origin") != expected_browser_origin(request.app.state.settings):
        return _error(403, "meeting_origin_rejected")
    store = getattr(request.app.state, "claw_meeting_store", None)
    if not isinstance(store, D1ClawMeetingStore):
        return _error(503, "meeting_records_unavailable")
    workspace = await _resolve_memory_workspace(request, owner)
    if not workspace:
        return _error(503, "workspace_authority_unavailable")
    return store, owner, workspace


async def _body(request: Request, fields: set[str], *,
                allow_empty: bool = False) -> dict[str, Any] | JSONResponse:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "meeting_json_required")
    try:
        raw = await read_bounded_request_body(request, max_bytes=_MAX_JSON_BYTES)
        data = json.loads(raw.decode("utf-8"))
    except (RequestBodyTooLarge, UnicodeError, ValueError):
        return _error(400, "meeting_request_invalid")
    if not isinstance(data, dict) or not set(data) <= fields:
        return _error(400, "meeting_request_invalid")
    if not data and not allow_empty:
        return _error(400, "meeting_request_invalid")
    return data


async def claw_meetings(request: Request) -> Response:
    authority = await _authority(request)
    if isinstance(authority, Response):
        return authority
    store, owner, workspace = authority
    if request.method == "GET":
        try:
            rows = await store.list_owner(owner_id=owner, workspace_id=workspace)
        except MeetingRecordError:
            return _error(503, "meeting_records_unavailable")
        except Exception:
            return _error(503, "meeting_records_unavailable")
        return JSONResponse({"ok": True, "contract_version": _CONTRACT,
                             "meetings": rows}, headers=_NO_STORE)
    data = await _body(request, {"title", "mode"})
    if isinstance(data, Response):
        return data
    if set(data) != {"title", "mode"} or data.get("mode") not in _MODES:
        return _error(400, "meeting_request_invalid")
    try:
        created = await store.create(owner_id=owner, workspace_id=workspace,
                                     title=data.get("title"), mode=data["mode"])
    except MeetingRecordError:
        return _error(400, "meeting_title_invalid")
    except Exception:
        return _error(503, "meeting_records_unavailable")
    return JSONResponse({"ok": True, "contract_version": _CONTRACT, "meeting": created},
                        status_code=201, headers=_NO_STORE)


async def claw_meeting_detail(request: Request) -> Response:
    authority = await _authority(request)
    if isinstance(authority, Response):
        return authority
    store, owner, workspace = authority
    meeting_ref = request.path_params.get("meeting_ref")
    if not isinstance(meeting_ref, str) or not _MEETING_REF.fullmatch(meeting_ref):
        return _error(404, "meeting_not_found")
    if request.method == "GET":
        try:
            meeting = await store.load(owner_id=owner, workspace_id=workspace,
                                       meeting_ref=meeting_ref)
            if meeting is None:
                return _error(404, "meeting_not_found")
            artifacts = await store.list_artifacts(owner_id=owner, workspace_id=workspace,
                                                   meeting_ref=meeting_ref)
            actions = await store.list_actions(owner_id=owner, workspace_id=workspace,
                                               meeting_ref=meeting_ref)
        except MeetingRecordError:
            return _error(503, "meeting_records_unavailable")
        except Exception:
            return _error(503, "meeting_records_unavailable")
        return JSONResponse({"ok": True, "contract_version": _CONTRACT, "meeting": meeting,
                             "artifacts": artifacts, "actions": actions}, headers=_NO_STORE)
    if request.method == "DELETE":
        try:
            removed = await store.delete(owner_id=owner, workspace_id=workspace,
                                         meeting_ref=meeting_ref)
        except MeetingRecordError:
            return _error(503, "meeting_records_unavailable")
        except Exception:
            return _error(503, "meeting_records_unavailable")
        if not removed:
            return _error(404, "meeting_not_found")
        return JSONResponse({
            "ok": True, "contract_version": _CONTRACT, "meeting_ref": meeting_ref,
            "record_deleted": True,
            # A Drive object is the customer's file in the customer's own Drive.
            # This route never touched it, so it must not be reported as deleted.
            "drive_files_deleted": False,
            "drive_note": "PADIEM 회의 기록만 삭제되었습니다. Google Drive 파일은 사용자 Drive에 남아 있습니다.",
        }, headers=_NO_STORE)
    data = await _body(request, {"title"})
    if isinstance(data, Response):
        return data
    if set(data) != {"title"}:
        return _error(400, "meeting_request_invalid")
    try:
        renamed = await store.rename(owner_id=owner, workspace_id=workspace,
                                     meeting_ref=meeting_ref, title=data.get("title"))
        projection = (await store.load(owner_id=owner, workspace_id=workspace,
                                       meeting_ref=meeting_ref)) if renamed else None
    except MeetingRecordError:
        return _error(400, "meeting_title_invalid")
    except Exception:
        return _error(503, "meeting_records_unavailable")
    if projection is None:
        return _error(404, "meeting_not_found")
    return JSONResponse({"ok": True, "contract_version": _CONTRACT, "meeting": projection},
                        headers=_NO_STORE)


async def claw_meeting_end(request: Request) -> Response:
    authority = await _authority(request)
    if isinstance(authority, Response):
        return authority
    store, owner, workspace = authority
    meeting_ref = request.path_params.get("meeting_ref")
    if not isinstance(meeting_ref, str) or not _MEETING_REF.fullmatch(meeting_ref):
        return _error(404, "meeting_not_found")
    data = await _body(request, {"discard"}, allow_empty=True)
    if isinstance(data, Response):
        return data
    discard = data.get("discard", False)
    if type(discard) is not bool:
        return _error(400, "meeting_request_invalid")
    try:
        ended = await store.finish(owner_id=owner, workspace_id=workspace,
                                   meeting_ref=meeting_ref, discard=discard)
        projection = (await store.load(owner_id=owner, workspace_id=workspace,
                                       meeting_ref=meeting_ref)) if ended else None
    except MeetingRecordError:
        return _error(503, "meeting_records_unavailable")
    except Exception:
        return _error(503, "meeting_records_unavailable")
    if projection is None:
        return _error(409, "meeting_not_active")
    return JSONResponse({"ok": True, "contract_version": _CONTRACT, "meeting": projection},
                        headers=_NO_STORE)


async def claw_meeting_artifact(request: Request) -> Response:
    """Record where a meeting output is kept after the browser's own Drive upload."""
    authority = await _authority(request)
    if isinstance(authority, Response):
        return authority
    store, owner, workspace = authority
    meeting_ref = request.path_params.get("meeting_ref")
    if not isinstance(meeting_ref, str) or not _MEETING_REF.fullmatch(meeting_ref):
        return _error(404, "meeting_not_found")
    data = await _body(request, {"kind", "state", "drive_file_id", "filename",
                                 "mime_type", "byte_size"})
    if isinstance(data, Response):
        return data
    kind, state = data.get("kind"), data.get("state")
    if kind not in _ARTIFACT_KINDS or state not in _ARTIFACT_STATES:
        return _error(400, "meeting_artifact_invalid")
    filename = _safe_filename(data.get("filename"))
    if filename is None:
        return _error(400, "meeting_artifact_invalid")
    drive_file_id = data.get("drive_file_id")
    if state == "drive_saved":
        if not isinstance(drive_file_id, str) or not _DRIVE_FILE_ID.fullmatch(drive_file_id):
            return _error(400, "meeting_artifact_invalid")
    elif "drive_file_id" in data and drive_file_id is not None:
        return _error(400, "meeting_artifact_invalid")
    mime_type = data.get("mime_type")
    if mime_type is not None and (not isinstance(mime_type, str)
                                  or not 1 <= len(mime_type) <= 80
                                  or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.+-]*/"
                                                      r"[a-zA-Z0-9][a-zA-Z0-9.+-]*", mime_type)):
        return _error(400, "meeting_artifact_invalid")
    byte_size = data.get("byte_size")
    if byte_size is not None and (type(byte_size) is not int
                                  or not 1 <= byte_size <= 188743680):
        return _error(400, "meeting_artifact_invalid")
    try:
        row = await store.put_artifact(owner_id=owner, workspace_id=workspace,
                                       meeting_ref=meeting_ref, kind=kind, state=state,
                                       drive_file_id=drive_file_id if state == "drive_saved" else None,
                                       filename=filename, mime_type=mime_type,
                                       byte_size=byte_size)
    except MeetingRecordError as exc:
        code = str(exc)
        return _error(404 if code == "meeting not found" else 400, "meeting_artifact_invalid")
    except Exception:
        return _error(503, "meeting_records_unavailable")
    return JSONResponse({"ok": True, "contract_version": _CONTRACT,
                         "meeting_ref": meeting_ref, "artifact": row},
                        status_code=201, headers=_NO_STORE)


async def claw_meeting_action_create(request: Request) -> Response:
    authority = await _authority(request)
    if isinstance(authority, Response):
        return authority
    store, owner, workspace = authority
    meeting_ref = request.path_params.get("meeting_ref")
    if not isinstance(meeting_ref, str) or not _MEETING_REF.fullmatch(meeting_ref):
        return _error(404, "meeting_not_found")
    data = await _body(request, {"kind", "summary", "owner_label", "due_date",
                                 "evidence_offset_start", "evidence_offset_end"})
    if isinstance(data, Response):
        return data
    if data.get("kind") not in _ACTION_KINDS:
        return _error(400, "meeting_action_invalid")
    try:
        row = await store.add_action(
            owner_id=owner, workspace_id=workspace, meeting_ref=meeting_ref,
            kind=data["kind"], summary=data.get("summary"),
            owner_label=data.get("owner_label"), due_date=data.get("due_date"),
            evidence_start=data.get("evidence_offset_start"),
            evidence_end=data.get("evidence_offset_end"))
    except MeetingRecordError:
        return _error(400, "meeting_action_invalid")
    except Exception:
        return _error(503, "meeting_records_unavailable")
    return JSONResponse({"ok": True, "contract_version": _CONTRACT,
                         "meeting_ref": meeting_ref, "action": row},
                        status_code=201, headers=_NO_STORE)


async def claw_meeting_action(request: Request) -> Response:
    authority = await _authority(request)
    if isinstance(authority, Response):
        return authority
    store, owner, workspace = authority
    action_ref = request.path_params.get("action_ref")
    if not isinstance(action_ref, str) or not _ACTION_REF.fullmatch(action_ref):
        return _error(404, "meeting_action_not_found")
    if request.method == "DELETE":
        try:
            removed = await store.delete_action(owner_id=owner, workspace_id=workspace,
                                                action_ref=action_ref)
        except MeetingRecordError:
            return _error(503, "meeting_records_unavailable")
        except Exception:
            return _error(503, "meeting_records_unavailable")
        return (JSONResponse({"ok": True, "contract_version": _CONTRACT,
                              "action_ref": action_ref, "action_deleted": True},
                             headers=_NO_STORE)
                if removed else _error(404, "meeting_action_not_found"))
    data = await _body(request, {"status"})
    if isinstance(data, Response):
        return data
    status = data.get("status")
    if status not in _ACTION_STATUS:
        # `registered` is only ever written by the verified Padiem Calendar path.
        return _error(400, "meeting_action_status_not_settable")
    try:
        decided = await store.decide_action(owner_id=owner, workspace_id=workspace,
                                            action_ref=action_ref, status=status)
    except MeetingRecordError:
        return _error(400, "meeting_action_status_not_settable")
    except Exception:
        return _error(503, "meeting_records_unavailable")
    if not decided:
        return _error(409, "meeting_action_not_candidate")
    return JSONResponse({"ok": True, "contract_version": _CONTRACT,
                         "action_ref": action_ref, "status": status}, headers=_NO_STORE)
