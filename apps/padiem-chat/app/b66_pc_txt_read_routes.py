"""#4434: B66 product-scoped PC TXT read dispatch and terminal-result read.

WHAT THIS IS
    Two B66-owned product routes over the existing canonical Connector/Broker
    execution and return legs:

    * ``POST /api/b66/connect/txt-reads/request`` — stage one B66-linked run
      in the caller's B66 conversation and enqueue one bounded TXT read on the
      verified PC. The browser names only the file and (optionally) the
      device; the root, the run id and the approval wire are server-derived.
    * ``POST /api/b66/runs/{run_id}/pc-result`` — reconcile one B66-staged run
      against the canonical Broker terminal fact and land the verified result
      text in the run's own B66 conversation. The browser never chooses the
      destination conversation, the command or the file bytes.

AUTHORITY BOUNDARY (must stay true)
    SERVER_OWNER       The owner and workspace come from the authenticated
                       session and the server-owned workspace resolution only.
    PRODUCT_SCOPED     Every check pins ``b66`` through
                       ``b66_pc_operations_allowed``; a Chat/Claw grant, an
                       unscoped grant or a grant for another operation never
                       qualifies. Dispatch additionally requires the existing
                       verified owner session, Identity consent, Broker device
                       binding and TXT execution profile inside
                       ``dispatch_verified_txt_read``.
    NO_NEW_CONNECTOR   Enrollment, pairing, Broker bindings and the Resident
                       stay exactly the existing canonical ones. A trusted
                       operator B66 grant must already be injected in
                       ``b66_pc_access_policy``; the default policy grants
                       nothing, so both routes fail closed without it.
    ORIGINAL_B66_ONLY  The dispatch route only stages runs linked to an
                       existing B66 conversation owned by the caller, and the
                       result route only projects runs marked ``channel=b66``
                       / ``action=b66_txt_read`` back into that same B66
                       conversation. A Claw run is never readable here and the
                       canonical correlation checks are never skipped.
    BOUNDED            One TXT file per request, server-fixed ``root.3140``,
                       canonical Resident path rules, bounded bodies and
                       bounded safe identifiers throughout.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from padiem_control_plane.local_agent_pc_access import PcAccessOperation

from .b66_dialogue_routes import b66_dialogue_store
from .b66_pc_directory_routes import b66_pc_operations_allowed
from .b66_quote_routes import _error, _json, _member_access, _NO_STORE, _owner
from .claw_local_task_result_projection import LocalTaskResultError
from .claw_memory_routes import _resolve_memory_workspace
from .connector_txt_read_routes import dispatch_verified_txt_read
from .history import HistoryForbidden, validate_conversation_id

B66_PC_TXT_READ_PATH = "/api/b66/connect/txt-reads/request"
B66_PC_RESULT_PATH = "/api/b66/runs/{run_id}/pc-result"

_B66_PRODUCT_ID = "b66"
_B66_PC_TXT_ROOT_REF = "root.3140"
_B66_PC_TXT_CHANNEL = "b66"
_B66_PC_TXT_ACTION = "b66_txt_read"
_MAX_BODY_BYTES = 4096
_MAX_PATH_CHARS = 1024
_MAX_DEVICE_CHARS = 128
_ALLOWED_FIELDS = frozenset({"device_id", "path_relative", "conversation_id"})
_RUN_ID_RE = re.compile(r"^run_[A-Za-z0-9]{12,80}$")


def _run_id(value: Any) -> str | None:
    if not isinstance(value, str) or not _RUN_ID_RE.fullmatch(value.strip()):
        return None
    return value.strip()


def _mint_run_id() -> str:
    return "run_" + uuid.uuid4().hex[:24]


def _device_id(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not 0 < len(text) <= _MAX_DEVICE_CHARS:
        return None
    return text


def _txt_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not 0 < len(text) <= _MAX_PATH_CHARS:
        return None
    if "\x00" in text or "\r" in text or "\n" in text:
        return None
    if not text.lower().endswith(".txt"):
        return None
    return text


async def _mark_run_failed(history: Any, uid: str, run_id: str) -> None:
    mark = getattr(history, "update_claw_run_status", None)
    if not callable(mark):
        return
    try:
        await mark(uid, run_id, "failed")
    except Exception:
        pass


async def b66_pc_txt_read_request(request: Request) -> JSONResponse:
    """Stage a B66-linked TXT read and enqueue it on the verified PC."""
    uid = _owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    _, denied = await _member_access(request, uid)
    if denied is not None:
        return denied
    try:
        workspace_id = await _resolve_memory_workspace(request, uid)
    except Exception:
        workspace_id = None
    if not workspace_id:
        return _error(503, "b66_pc_workspace_unavailable", "대화 범위를 확인할 수 없습니다.")

    data = await _json(request, max_body_bytes=_MAX_BODY_BYTES)
    if isinstance(data, JSONResponse):
        return data
    if not isinstance(data, dict) or set(data) - _ALLOWED_FIELDS:
        return _error(400, "invalid_txt_read_request", "요청 형식이 올바르지 않습니다.")

    try:
        conversation_id = validate_conversation_id(data.get("conversation_id"))
    except ValueError:
        conversation_id = None
    if conversation_id is None:
        return _error(422, "b66_pc_conversation_required", "PC 작업을 연결할 B66 대화를 확인해 주세요.")
    path_relative = _txt_path(data.get("path_relative"))
    if path_relative is None:
        return _error(422, "b66_pc_txt_path_invalid", "PC에서 읽을 TXT 파일의 상대 경로를 하나 지정해 주세요.")
    device_id = _device_id(data.get("device_id"))
    if data.get("device_id") is not None and device_id is None:
        return _error(422, "b66_pc_device_invalid", "선택한 PC를 확인할 수 없습니다.")

    if not await b66_pc_operations_allowed(
        request, uid, workspace_id, (PcAccessOperation.FILE_READ,),
    ):
        return _error(403, "b66_pc_txt_read_unavailable", "PC 파일 읽기 권한이 없습니다.")

    store = b66_dialogue_store(request)
    if store is None:
        return _error(503, "b66_pc_conversation_unavailable", "PC 작업 대화를 확인할 수 없습니다.")
    try:
        conversation = await store.load(uid, conversation_id)
    except Exception:
        return _error(503, "b66_pc_conversation_unavailable", "PC 작업 대화를 확인할 수 없습니다.")
    if conversation is None:
        return _error(404, "conversation_not_found", "대화를 찾을 수 없습니다.")

    history_store = getattr(request.app.state, "history_store", None)
    stage = getattr(history_store, "record_claw_run", None)
    if not callable(stage):
        return _error(503, "b66_pc_run_unavailable", "PC 작업 대기를 기록할 수 없습니다.")

    run_id = _mint_run_id()
    try:
        await stage(
            user_id=uid, run_id=run_id, channel=_B66_PC_TXT_CHANNEL,
            action=_B66_PC_TXT_ACTION,
            title=("B66 PC TXT: " + path_relative)[:120],
            status="pending", conversation_id=conversation_id,
            workspace_id=workspace_id,
        )
    except Exception:
        return _error(503, "b66_pc_run_unavailable", "PC 작업 대기를 기록할 수 없습니다.")

    wire = {
        "device_id": device_id,
        "root_ref": _B66_PC_TXT_ROOT_REF,
        "path_relative": path_relative,
        "run_id": run_id,
        "confirmed": True,
    }
    try:
        dispatched = await dispatch_verified_txt_read(request, wire)
    except Exception:
        await _mark_run_failed(history_store, uid, run_id)
        return _error(503, "b66_pc_dispatch_unavailable", "PC 작업 요청을 전달하지 못했습니다.")
    if getattr(dispatched, "status_code", 500) != 200:
        await _mark_run_failed(history_store, uid, run_id)
        return dispatched
    return JSONResponse(
        {"ok": True, "run_id": run_id, "conversation_id": conversation_id},
        headers=_NO_STORE,
    )


async def b66_pc_run_result(request: Request) -> JSONResponse:
    """Reconcile one B66 PC run and land its terminal result in B66 chat."""
    uid = _owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    _, denied = await _member_access(request, uid)
    if denied is not None:
        return denied
    try:
        workspace_id = await _resolve_memory_workspace(request, uid)
    except Exception:
        workspace_id = None
    if not workspace_id:
        return _error(503, "b66_pc_workspace_unavailable", "대화 범위를 확인할 수 없습니다.")

    run_id = _run_id(request.path_params.get("run_id"))
    if run_id is None:
        return _error(404, "run_not_found", "PC 작업을 찾을 수 없습니다.")

    if not await b66_pc_operations_allowed(
        request, uid, workspace_id, (PcAccessOperation.TASK_RESULT,),
    ):
        return _error(403, "b66_pc_result_unavailable", "PC 작업 결과를 확인할 권한이 없습니다.")

    history_store = getattr(request.app.state, "history_store", None)
    get_run = getattr(history_store, "get_claw_run", None)
    if not callable(get_run):
        return _error(503, "b66_pc_run_unavailable", "PC 작업 기록을 확인할 수 없습니다.")
    try:
        run_row = await get_run(uid, run_id)
    except Exception:
        return _error(503, "b66_pc_run_unavailable", "PC 작업 기록을 확인할 수 없습니다.")
    if (
        not isinstance(run_row, dict)
        or run_row.get("run_id") != run_id
        or not isinstance(run_row.get("conversation_id"), str)
        or not run_row["conversation_id"]
    ):
        return _error(404, "run_not_found", "PC 작업을 찾을 수 없습니다.")
    if run_row.get("workspace_id") != workspace_id:
        return _error(409, "b66_pc_run_workspace_mismatch", "워크스페이스가 일치하지 않습니다.")
    if run_row.get("channel") != _B66_PC_TXT_CHANNEL or run_row.get("action") != _B66_PC_TXT_ACTION:
        # A Claw run row is never readable through the B66 product lane, and
        # the existence of another owner's run stays indistinguishable.
        return _error(404, "run_not_found", "PC 작업을 찾을 수 없습니다.")
    conversation_id = run_row["conversation_id"]

    store = b66_dialogue_store(request)
    if store is None:
        return _error(503, "b66_pc_conversation_unavailable", "PC 작업 대화를 확인할 수 없습니다.")
    try:
        conversation = await store.load(uid, conversation_id)
    except Exception:
        return _error(503, "b66_pc_conversation_unavailable", "PC 작업 대화를 확인할 수 없습니다.")
    if conversation is None:
        return _error(404, "conversation_not_found", "대화를 찾을 수 없습니다.")

    source = getattr(request.app.state, "local_task_result_source", None)
    project = getattr(source, "project_local_runner_result", None)
    if not callable(project) or getattr(source, "configured", True) is not True:
        return _error(503, "b66_pc_result_unavailable", "PC 작업 결과를 확인할 수 없습니다.")
    try:
        decision = await project(owner_id=uid, run_id=run_id, workspace_id=workspace_id)
    except HistoryForbidden:
        return _error(403, "b66_pc_result_forbidden", "해당 PC 작업에 접근할 수 없습니다.")
    except LocalTaskResultError as exc:
        if exc.code == "local_task_result_workspace_mismatch":
            return _error(409, "b66_pc_run_workspace_mismatch", "워크스페이스가 일치하지 않습니다.")
        if exc.code == "local_task_result_workspace_missing":
            return _error(409, "b66_pc_run_workspace_missing", "PC 작업의 워크스페이스 범위가 없습니다.")
        return _error(409, "b66_pc_result_conflict", "PC 작업 결과를 확정할 수 없습니다.")
    except Exception:
        return _error(503, "b66_pc_result_unavailable", "PC 작업 결과를 확인할 수 없습니다.")
    if not isinstance(decision, dict):
        return _error(404, "b66_pc_result_absent", "종료된 PC 작업 결과가 없습니다.")
    return JSONResponse(
        {
            "ok": True,
            "run_id": run_id,
            "conversation_id": conversation_id,
            "appended": decision.get("appended") is True,
            "status": decision.get("status"),
            "reason": decision.get("reason"),
        },
        headers=_NO_STORE,
    )


__all__ = [
    "B66_PC_RESULT_PATH",
    "B66_PC_TXT_READ_PATH",
    "b66_pc_run_result",
    "b66_pc_txt_read_request",
]
