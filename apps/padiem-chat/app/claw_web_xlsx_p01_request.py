"""Web-first #3580: bounded owner-run pause dispatch; never an approval grant."""
from __future__ import annotations

import inspect
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .workspace_storage import _row_to_dict

_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:@+-]{0,127}$")
_SEL = re.compile(r"^sel_[0-9a-f]{32}$")
_DOC = re.compile(r"^doc_[0-9a-f]{32}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_CONT = re.compile(r"^cont_[a-zA-Z0-9_-]{8,123}$")
_PAUSE = re.compile(r"^pause:[0-9a-f]{24,64}$")
_TOOL = "workspace.xlsx.confirm_original_read"
_APP = "padiem-web-xlsx-p01"


class WebXlsxP01RequestError(ValueError):
    pass


def _utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise WebXlsxP01RequestError("timestamp required")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WebXlsxP01RequestError("invalid timestamp") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise WebXlsxP01RequestError("aware timestamp required")
    return instant


@dataclass(frozen=True, slots=True)
class TrustedWebXlsxP01Request:
    owner_id: str
    workspace_id: str
    run_id: str
    selection_ref: str
    document_id: str
    source_sha256: str
    filename: str
    selection_expires_at: str

    def __post_init__(self):
        if not all(isinstance(getattr(self, key), str) and _ID.fullmatch(getattr(self, key))
                   for key in ("owner_id", "workspace_id", "run_id")):
            raise WebXlsxP01RequestError("invalid owner-run scope")
        if not _SEL.fullmatch(self.selection_ref) or not _DOC.fullmatch(self.document_id):
            raise WebXlsxP01RequestError("invalid selection scope")
        if not _SHA.fullmatch(self.source_sha256):
            raise WebXlsxP01RequestError("invalid source fingerprint")
        if not isinstance(self.filename, str) or not self.filename.lower().endswith(".xlsx"):
            raise WebXlsxP01RequestError("invalid source filename")
        if _utc(self.selection_expires_at) <= datetime.now(timezone.utc):
            raise WebXlsxP01RequestError("selection expired")


@dataclass(frozen=True, slots=True)
class VerifiedWebXlsxEnginePause:
    """Validated Engine-produced pause projection, not a user decision."""
    engine_run_id: str
    continuation_ref: str
    pause_id: str
    expires_at: str

    def __post_init__(self):
        if not isinstance(self.engine_run_id, str) or not _ID.fullmatch(self.engine_run_id):
            raise WebXlsxP01RequestError("invalid Engine run")
        if not isinstance(self.continuation_ref, str) or not _CONT.fullmatch(self.continuation_ref):
            raise WebXlsxP01RequestError("invalid Engine continuation")
        if not isinstance(self.pause_id, str) or not _PAUSE.fullmatch(self.pause_id):
            raise WebXlsxP01RequestError("invalid Engine pause")
        now = datetime.now(timezone.utc)
        expires = _utc(self.expires_at)
        if not now < expires <= now + timedelta(minutes=30):
            raise WebXlsxP01RequestError("invalid Engine pause lifetime")


def parse_engine_pause(result: Any, *, original: TrustedWebXlsxP01Request) -> VerifiedWebXlsxEnginePause:
    """Accept only a genuine Core/Engine paused-tool projection for this app."""
    if not isinstance(result, dict) or set(result) != {"orchestration"}:
        raise WebXlsxP01RequestError("unrecognized Engine result")
    body = result["orchestration"]
    if not isinstance(body, dict) or body.get("app_id") != _APP:
        raise WebXlsxP01RequestError("Engine application mismatch")
    pause = body.get("approval_pause")
    execution = body.get("execution")
    if not isinstance(pause, dict) or not isinstance(execution, dict):
        raise WebXlsxP01RequestError("missing real Engine pause")
    metadata = execution.get("metadata")
    events = metadata.get("tool_events") if isinstance(metadata, dict) else None
    if (metadata is None or metadata.get("status") != "paused"
        or not isinstance(events, list)
        or not any(isinstance(e, dict) and e.get("tool_id") == _TOOL
                   and e.get("status") == "policy_blocked" for e in events)
        or pause.get("status") != "paused" or pause.get("tool_id") != _TOOL
        or pause.get("requirement") != "user_confirmation"
        or pause.get("approval_scope") != ["workspace.xlsx.original.read.intent"]
        or pause.get("trace_id") != "web_xlsx_" + original.selection_ref):
        raise WebXlsxP01RequestError("Engine pause does not bind XLSX source intent")
    if _utc(pause.get("expires_at")) > _utc(original.selection_expires_at):
        # Engine may support a longer grant window than a 30-min selection.
        # No web approval may outlive the original selection authority.
        raise WebXlsxP01RequestError("pause would outlive selected original")
    return VerifiedWebXlsxEnginePause(
        engine_run_id=pause["run_id"], continuation_ref=body.get("continuation_ref"),
        pause_id=pause.get("continuation_id"), expires_at=pause["expires_at"],
    )


class D1WebXlsxP01RequestStore:
    """One-shot reservation means uncertain Engine dispatch never auto-retries."""

    def __init__(self, db: Any):
        if db is None:
            raise ValueError("private D1 binding required")
        self.db = db

    async def reserve(self, request: TrustedWebXlsxP01Request) -> str:
        if not isinstance(request, TrustedWebXlsxP01Request):
            raise WebXlsxP01RequestError("trusted selection required")
        ident = "wpr_" + uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        statement = self.db.prepare(
            "INSERT INTO claw_web_xlsx_p01_requests "
            "(request_ref,selection_ref,user_id,workspace_id,run_id,document_id,"
            "source_sha256,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,'dispatching',?,?)"
        ).bind(ident, request.selection_ref, request.owner_id, request.workspace_id,
               request.run_id, request.document_id, request.source_sha256, now, now)
        await statement.run()
        return ident

    async def commit_pause(self, *, request: TrustedWebXlsxP01Request,
                           request_ref: str, pause: VerifiedWebXlsxEnginePause) -> bool:
        if (not isinstance(request, TrustedWebXlsxP01Request)
                or not isinstance(pause, VerifiedWebXlsxEnginePause)
                or not isinstance(request_ref, str)
                or not re.fullmatch(r"wpr_[0-9a-f]{32}", request_ref)
                or _utc(pause.expires_at) > _utc(request.selection_expires_at)):
            raise WebXlsxP01RequestError("invalid pause scope")
        now = datetime.now(timezone.utc).isoformat()
        statement = self.db.prepare(
            "UPDATE claw_web_xlsx_p01_requests SET status='waiting_p01', "
            "engine_run_id=?,continuation_ref=?,pause_id=?,pause_expires_at=?,updated_at=? "
            "WHERE request_ref=? AND selection_ref=? AND user_id=? AND workspace_id=? "
            "AND run_id=? AND document_id=? AND source_sha256=? AND status='dispatching'"
        ).bind(pause.engine_run_id, pause.continuation_ref, pause.pause_id,
               pause.expires_at, now, request_ref, request.selection_ref,
               request.owner_id, request.workspace_id, request.run_id,
               request.document_id, request.source_sha256)
        await statement.run()
        check = self.db.prepare(
            "SELECT status,engine_run_id,continuation_ref,pause_id "
            "FROM claw_web_xlsx_p01_requests "
            "WHERE request_ref=? AND user_id=? AND workspace_id=? AND run_id=?"
        ).bind(request_ref, request.owner_id, request.workspace_id, request.run_id)
        row = _row_to_dict(await check.first())
        return bool(row and row.get("status") == "waiting_p01"
                    and row.get("engine_run_id") == pause.engine_run_id
                    and row.get("continuation_ref") == pause.continuation_ref
                    and row.get("pause_id") == pause.pause_id)


async def dispatch_owner_web_xlsx_p01(
    *, request: TrustedWebXlsxP01Request, store: Any, client: Any,
) -> dict[str, Any]:
    """Bounded single dispatch; no approval evidence ever accepted from caller."""
    if not isinstance(request, TrustedWebXlsxP01Request):
        raise WebXlsxP01RequestError("trusted request required")
    if not callable(getattr(store, "reserve", None)) or not callable(
            getattr(store, "commit_pause", None)):
        raise WebXlsxP01RequestError("durable dispatch ledger required")
    if not callable(getattr(client, "start_pause", None)):
        raise WebXlsxP01RequestError("private Engine adapter required")
    # Reserve BEFORE network dispatch. Duplicate, uncertain or failed attempts
    # retain reservation and cannot be retried by a second web POST.
    request_ref = store.reserve(request)
    if inspect.isawaitable(request_ref):
        request_ref = await request_ref
    result = client.start_pause(request)
    if inspect.isawaitable(result):
        result = await result
    pause = parse_engine_pause(result, original=request)
    committed = store.commit_pause(request=request, request_ref=request_ref, pause=pause)
    if inspect.isawaitable(committed):
        committed = await committed
    if committed is not True:
        raise WebXlsxP01RequestError("durable Engine pause write unavailable")
    return {
        "request_ref": request_ref, "run_id": request.run_id,
        "selection_ref": request.selection_ref,
        "status": "waiting_p01",
        "pause_expires_at": pause.expires_at,
        "processing_started": False, "workcopy_created": False,
        "owner_decision_enabled": False,
    }
