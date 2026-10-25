"""#4434 — owner-visible XLSX revision request: review the edits, then approve them.

Two POSTs, one authority chain already built for the TXT read lane:

1. ``POST /api/claw/connector/xlsx-revisions/preview``
   Names the device, selected root, workbook, worksheet and the literal edits. The
   server verifies the owner session and CSRF, Identity consent, the
   Broker-confirmed binding, the stored conversation run and the installed
   Resident execution profile, refuses anything outside the selected root or
   outside the Resident's literal edit contract, and returns exactly what would
   change — cell by cell, current value and proposed value, and the derived
   result file name. Nothing is minted and nothing is queued here.
2. ``POST /api/claw/connector/xlsx-revisions/request``
   Carries ``confirmed: true`` with the same intent and the preview reference. The
   stored preview must still belong to this owner, this run, this device and this
   exact intent — a ref alone is not an approval, and edited bytes between the two
   calls are refused rather than silently approved. Only then is the READ
   attestation minted and one command queued.

What this module never does: it does not mint a write approval, a result digest or
a write request fingerprint. The PC produces the result, has it verified, and the
Resident resolves the write approval through the existing P01 evidence route
(``kagent/verified_p01_xlsx_revision_plan_source.py``). A number invented here
would be an approval bypass wearing a digest.
"""

from __future__ import annotations

import inspect
import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .claw_connector_enrollment_routes import _verified_owner_request
from .claw_memory_routes import _resolve_memory_workspace
from .connector_txt_approval_material import (
    OwnerTxtApprovalProof, TxtApprovalMaterialError,
)
from .connector_xlsx_revision_approval_material import (
    PREVIEW_WINDOW, XlsxRevisionMaterialError, derived_result_path,
    installed_executable_profile, mint_xlsx_revision_envelope,
    normalize_revision_edits, normalize_revision_path, preview_digest,
)
from .control_plane_broker_pairing_client import IdentityBridgeError
from .request_telemetry import emit_stage_event

XLSX_REVISION_PREVIEW_PATH = "/api/claw/connector/xlsx-revisions/preview"
XLSX_REVISION_REQUEST_PATH = "/api/claw/connector/xlsx-revisions/request"
_MAX_BODY_BYTES = 8192
_PREVIEW_LIMIT = 32

_PREVIEW_KEYS = frozenset({
    "device_id", "root_ref", "path_relative", "sheet_name", "edits", "run_id",
})
_REQUEST_KEYS = _PREVIEW_KEYS | frozenset({"preview_ref", "confirmed"})

_HEADERS = {
    "Cache-Control": "no-store, max-age=0", "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
}


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code}}, status_code=status,
                        headers=_HEADERS)


class RevisionPreviewStore:
    """Short-lived, owner-bound records of what the owner was shown.

    The store holds the intent digest and the bounded preview, never the minted
    envelope. A confirmation must match the digest of the intent it approves, so
    an edit changed between the two calls is refused instead of executed.
    """

    def __init__(self, *, limit: int = _PREVIEW_LIMIT,
                 clock: Any = None) -> None:
        self._limit = limit
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._records: dict[str, dict[str, Any]] = {}

    def record(self, *, owner_id: str, run_id: str, device_id: str, root_ref: str,
               path_relative: str, sheet_name: str, edits: list[dict[str, Any]],
               preview: dict[str, Any]) -> str:
        ref = f"xlsxrevpreview-{abs(hash((owner_id, run_id, preview_digest(
            owner_id=owner_id, run_id=run_id, device_id=device_id, root_ref=root_ref,
            path_relative=path_relative, sheet_name=sheet_name, edits=edits))))}"
        entry = {
            "owner_id": owner_id, "run_id": run_id, "device_id": device_id,
            "root_ref": root_ref, "path_relative": path_relative,
            "sheet_name": sheet_name, "edits": edits, "preview": preview,
            "expires_at": self._clock() + PREVIEW_WINDOW,
        }
        with self._lock:
            self._prune()
            if len(self._records) >= self._limit:
                raise XlsxRevisionMaterialError("revision preview capacity is full")
            self._records[ref] = entry
        return ref

    def confirm(self, *, ref: str, owner_id: str, run_id: str, device_id: str,
                root_ref: str, path_relative: str, sheet_name: str,
                edits: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            self._prune()
            entry = self._records.get(ref)
            if entry is None:
                raise XlsxRevisionMaterialError("revision preview is unknown or expired")
            del self._records[ref]
        now = self._clock()
        if entry["expires_at"] <= now:
            raise XlsxRevisionMaterialError("revision preview has expired")
        same_intent = preview_digest(
            owner_id=owner_id, run_id=run_id, device_id=device_id, root_ref=root_ref,
            path_relative=path_relative, sheet_name=sheet_name, edits=edits)
        stored = preview_digest(
            owner_id=entry["owner_id"], run_id=entry["run_id"],
            device_id=entry["device_id"], root_ref=entry["root_ref"],
            path_relative=entry["path_relative"], sheet_name=entry["sheet_name"],
            edits=entry["edits"])
        if same_intent != stored:
            # One refusal for every divergence: a different owner, run, device,
            # root, workbook, worksheet or cell value is not the intent shown.
            raise XlsxRevisionMaterialError("confirmed intent is not the intent that was previewed")
        return entry

    def _prune(self) -> None:
        now = self._clock()
        for ref in [key for key, value in self._records.items()
                    if value["expires_at"] <= now]:
            del self._records[ref]

    def safe_dict(self) -> dict[str, Any]:
        with self._lock:
            return {"stored_count": len(self._records), "limit": self._limit,
                    "raw_values_stored": False, "envelope_stored": False,
                    "one_shot": True}


_previews = RevisionPreviewStore()


def revision_preview_store() -> RevisionPreviewStore:
    return _previews


def _body(value: bytes, allowed: frozenset[str]) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError):
        return None
    if not isinstance(parsed, dict) or frozenset(parsed) != allowed:
        return None
    for key in ("device_id", "root_ref", "path_relative", "run_id", "sheet_name"):
        item = parsed.get(key)
        if not isinstance(item, str) or not item or len(item) > 1024:
            return None
    if not isinstance(parsed.get("edits"), list) or not 1 <= len(parsed["edits"]) <= 64:
        return None
    return parsed


async def _owner_and_target(
    request: Request, *, device_id: str, run_id: str,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Every material fact comes from a server authority, never the browser."""

    uid = current_user_id(request) if auth_ready(request) else None
    if uid is None:
        return None, _error(401, "unauthorized")
    session, denial = await _verified_owner_request(request)
    if denial is not None or session is None:
        return None, denial or _error(401, "canonical_session_required")
    workspace_id = await _resolve_memory_workspace(request, uid)
    if workspace_id is None:
        return None, _error(503, "revision_workspace_unavailable")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    broker = getattr(request.app.state, "connector_txt_read_source", None)
    if (not callable(getattr(identity, "resolve_connector_enrollment_consent_for_device", None))
            or not callable(getattr(identity, "resolve_connector_workspace", None))
            or not callable(getattr(broker, "resolve_device_binding", None))
            or not callable(getattr(broker, "installed_txt_execution_profile", None))):
        return None, _error(503, "revision_authority_unavailable")

    try:
        consent = identity.resolve_connector_enrollment_consent_for_device(
            session_id=session.session_id, device_id=device_id)
        if inspect.isawaitable(consent):
            consent = await consent
    except Exception:
        return None, _error(403, "revision_consent_required")
    if (not isinstance(consent, dict) or consent.get("device_id") != device_id
            or not isinstance(consent.get("account_ref"), str) or not consent["account_ref"]
            or not isinstance(consent.get("workspace_ref"), str) or not consent["workspace_ref"]
            or consent.get("withdrawn_at") is not None):
        return None, _error(403, "revision_consent_required")
    try:
        connector_workspace = identity.resolve_connector_workspace(
            session_id=session.session_id)
        if inspect.isawaitable(connector_workspace):
            connector_workspace = await connector_workspace
    except Exception:
        return None, _error(503, "revision_authority_unavailable")
    if connector_workspace != consent["workspace_ref"]:
        return None, _error(403, "revision_consent_required")

    try:
        binding = await broker.resolve_device_binding(
            account_ref=consent["account_ref"],
            workspace_ref=consent["workspace_ref"], device_id=device_id)
    except IdentityBridgeError as exc:
        status = exc.status_code if isinstance(exc.status_code, int) else 503
        return None, _error(status if status in (403, 404) else 503,
                            "revision_device_unusable")
    except Exception:
        return None, _error(503, "revision_broker_unavailable")
    if (not isinstance(binding, dict) or not isinstance(binding.get("binding_ref"), str)
            or not isinstance(binding.get("credential_generation"), int)
            or binding.get("credential_generation") < 1):
        return None, _error(503, "revision_broker_unavailable")

    history = getattr(request.app.state, "history_store", None)
    if not callable(getattr(history, "get_claw_run", None)):
        return None, _error(503, "revision_run_unavailable")
    try:
        run_row = await history.get_claw_run(uid, run_id)
        if inspect.isawaitable(run_row):
            run_row = await run_row
    except Exception:
        return None, _error(503, "revision_run_unavailable")
    if (not isinstance(run_row, dict) or run_row.get("run_id") != run_id
            or run_row.get("workspace_id") != workspace_id
            or not isinstance(run_row.get("conversation_id"), str)
            or not run_row["conversation_id"]):
        return None, _error(404, "revision_run_unavailable")

    try:
        executable = await broker.installed_txt_execution_profile(
            account_ref=consent["account_ref"], workspace_ref=consent["workspace_ref"],
            device_id=device_id, binding_ref=binding["binding_ref"])
    except Exception:
        return None, _error(503, "revision_execution_profile_unavailable")

    return {
        "owner_id": uid, "memory_workspace_id": workspace_id,
        "account_ref": consent["account_ref"],
        "connector_workspace_ref": consent["workspace_ref"],
        "consent_id": consent["consent_id"], "device_id": device_id,
        "binding_ref": binding["binding_ref"],
        "credential_generation": binding["credential_generation"],
        "run_id": run_id, "conversation_id": run_row["conversation_id"],
        "executable_path": executable, "broker": broker,
    }, None


def _intent(raw: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    path = normalize_revision_path(raw["path_relative"])
    sheet, edits = normalize_revision_edits(raw["sheet_name"], raw["edits"])
    return path, sheet, edits


async def preview_revision(request: Request) -> JSONResponse:
    """Show the owner exactly what would change. Mint and queue nothing."""

    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "revision_unsupported_media_type")
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdecimal() or int(declared) > _MAX_BODY_BYTES):
        return _error(413, "revision_request_too_large")
    raw_body = await request.body()
    if len(raw_body) > _MAX_BODY_BYTES:
        return _error(413, "revision_request_too_large")
    wire = _body(raw_body, _PREVIEW_KEYS)
    if wire is None:
        return _error(400, "revision_invalid_body")

    scope, denial = await _owner_and_target(
        request, device_id=wire["device_id"], run_id=wire["run_id"])
    if denial is not None:
        return denial
    try:
        path, sheet, edits = _intent(wire)
        derived = derived_result_path(path)
        installed_executable_profile(scope["executable_path"])
    except XlsxRevisionMaterialError:
        return _error(400, "revision_intent_refused")

    stored = _previews.record(
        owner_id=scope["owner_id"], run_id=scope["run_id"], device_id=scope["device_id"],
        root_ref=wire["root_ref"], path_relative=path, sheet_name=sheet, edits=edits,
        preview={"sheet_name": sheet, "edits": edits, "result_path_relative": derived})
    emit_stage_event(stage="xlsx_revision.preview", outcome="ok", duration_ms=0)
    return JSONResponse({
        "ok": True,
        "preview_ref": stored,
        "device_id": scope["device_id"],
        "root_ref": wire["root_ref"],
        "path_relative": path,
        "run_id": scope["run_id"],
        "sheet_name": sheet,
        "edits": edits,
        "result_path_relative": derived,
        "expires_at": (_preview_expires()).isoformat().replace("+00:00", "Z"),
        "read_only_envelope": True,
        "write_approval_minted_here": False,
    }, headers=_HEADERS)


async def request_revision(request: Request) -> JSONResponse:
    """Confirm the previewed intent, mint the READ attestation, queue one command."""

    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "revision_unsupported_media_type")
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdecimal() or int(declared) > _MAX_BODY_BYTES):
        return _error(413, "revision_request_too_large")
    raw_body = await request.body()
    if len(raw_body) > _MAX_BODY_BYTES:
        return _error(413, "revision_request_too_large")
    wire = _body(raw_body, _REQUEST_KEYS)
    if wire is None or wire.get("confirmed") is not True:
        return _error(400, "revision_invalid_body")
    if not isinstance(wire.get("preview_ref"), str) or not wire["preview_ref"]:
        return _error(400, "revision_invalid_body")

    scope, denial = await _owner_and_target(
        request, device_id=wire["device_id"], run_id=wire["run_id"])
    if denial is not None:
        return denial
    try:
        path, sheet, edits = _intent(wire)
    except XlsxRevisionMaterialError:
        return _error(400, "revision_intent_refused")

    try:
        _previews.confirm(
            ref=wire["preview_ref"], owner_id=scope["owner_id"], run_id=scope["run_id"],
            device_id=scope["device_id"], root_ref=wire["root_ref"],
            path_relative=path, sheet_name=sheet, edits=edits)
    except XlsxRevisionMaterialError:
        return _error(409, "revision_preview_not_confirmed")

    try:
        proof = OwnerTxtApprovalProof(
            owner_id=scope["owner_id"], workspace_id=scope["connector_workspace_ref"],
            device_id=scope["device_id"], binding_ref=scope["binding_ref"],
            credential_generation=scope["credential_generation"],
            consent_id=scope["consent_id"], run_id=scope["run_id"],
        )
        issued = mint_xlsx_revision_envelope(
            approval=proof, root_ref=wire["root_ref"], path_relative=path,
            sheet_name=sheet, edits=edits, executable_path=scope["executable_path"])
    except (XlsxRevisionMaterialError, TxtApprovalMaterialError):
        return _error(400, "revision_refused")

    enqueue = getattr(scope["broker"], "enqueue_xlsx_revision_command", None)
    if not callable(enqueue):
        return _error(503, "revision_enqueue_unavailable")
    try:
        receipt = await enqueue(command=issued["enqueue"], material=issued["material"])
    except IdentityBridgeError:
        return _error(409, "revision_enqueue_refused")
    except Exception:
        return _error(503, "revision_enqueue_unavailable")
    if not isinstance(receipt, dict) or receipt.get("command_id") != issued["enqueue"]["command_id"]:
        return _error(503, "revision_enqueue_unavailable")

    emit_stage_event(stage="xlsx_revision.enqueue", outcome="ok", duration_ms=0)
    return JSONResponse({
        "ok": True,
        "command": {
            "command_id": receipt["command_id"],
            "run_id": scope["run_id"],
            "tool_request_ref": issued["enqueue"]["tool_request_ref"],
        },
        "conversation_id": scope["conversation_id"],
        "result_path_relative": issued["preview"]["result_path_relative"],
        "read_approval_issued": True,
        "write_approval_issued": False,
        "file_modified_by_this_call": False,
    }, headers=_HEADERS)


def _preview_expires() -> datetime:
    return datetime.now(timezone.utc) + PREVIEW_WINDOW
