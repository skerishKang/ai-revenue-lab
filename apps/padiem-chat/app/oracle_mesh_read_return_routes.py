"""#4139 — Oracle management-host MeshCentral read: intent, poll, result.

The Windows Resident trial stays a separate Draft experiment: nothing here
executes on, or requires, the trial PC. This is the product path, and it
executes on the Oracle management host, where the official ``meshctrl.js``
client talks to the local MeshCentral server directly.

Actual call path (no browser carriage of content, no manual copying, no
browser session handed to Oracle):

* Owner intent (browser, owner session + CSRF): ``POST .../mesh-reads/request``
  carries intent only — device, run, root/path, confirmation. The server
  verifies the full existing chain (session, workspace, consent, live broker
  binding, origin run, complete stored correlation, deployment mesh
  ownership) and stages one dispatch row. The browser learns only a
  dispatch id; it never sees content, nonces or secrets.
* Executor poll (Oracle, deployment channel secret): ``POST
  .../mesh-reads/poll`` returns the single oldest claimable dispatch with a
  fresh single-use nonce. The nonce is stored hashed; a database read cannot
  replay an execution.
* Executor submit (Oracle, channel secret + nonce): ``POST
  .../mesh-reads/result`` carries the execution outcome and, on a clean
  exited/0 run, the bytes. The server revalidates everything — secret,
  dispatch state, nonce, expiry, exact correlation against the broker-bound
  row, execution outcome, size, UTF-8, control characters, SHA-256 — and
  appends once through the existing history authority under the standard
  stable message id. A tampered body+hash, a replayed nonce, or a
  cross-command package fails closed; a non-clean execution is delivered to
  the conversation as a truthful bounded failure, never silence.

What these routes are NOT: they enqueue, admit, acknowledge or write nothing
on the broker. The destination conversation is read from the origin run row,
never taken from the caller. The executor identity
(``oracle_management_host``) and the absence of a broker acknowledgment are
reported explicitly: a management-host return never poses as a
device-acknowledged one.
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from padiem_ai_core.pc_device_identity import is_pc_device_id
from padiem_ai_core.powershell_literal import ps_literal, ps_utf8_literal
from .oracle_mesh_log import (
    _RESULT_LOG,
    ensure_result_log_host_visible,
    _identity_bridge_failure_log_line,
    _PC_RESULT_ACTION_WORDS,
    _PC_RESULT_STATUS_WORDS,
    _PC_RESULT_REASON_WORDS,
    _pc_result_word,
    log_pc_result_store_stage,
)

from .pc_device_pairing_store import PcPairingError
from .pc_dispatch_ttl import chat_pc_dispatch_ttl, dispatch_ttl_seconds
from .pc_share_timeout import (
    PC_SHARE_UNAVAILABLE_CODE,
    PC_SHARE_UNAVAILABLE_MESSAGE_KO,
    share_command_prefix,
    share_roots_of,
)

from .auth_routes import current_user_id
from .claw_connector_enrollment_routes import _verified_owner_request
from .journal_host import ensure_journal_visible
from .claw_memory_routes import _resolve_memory_workspace
from .claw_pc_read_command import (
    pc_read_chunk_command,
    pc_read_length,
    pc_read_offset,
)
from .claw_pc_search_command import (
    PC_SEARCH_MAX_LIMIT,
    PC_SEARCH_SCAN_MAX_FILES,
    pc_search_command,
    pc_search_mode,
    pc_search_path,
    pc_search_query,
    pc_search_roots,
)
#: One deep pc_list answer carries at most this many rows, whatever the depth.
_PC_LIST_DEPTH_ROW_CAP = 200
from .claw_local_task_result_projection import result_message_id
from .connector_account_shadow import mode_connector_read
from .control_plane_identity import IdentityBridgeError
from .desktop_typed_text import (
    MAX_TYPED_CHARS as _MAX_TYPED_TEXT_CHARS,
    deposit_typed_text,
    text_is_deliverable,
    type_marker_op,
)
from .history import (
    HistoryError,
    HistoryForbidden,
    MAX_HISTORY_MESSAGE_CHARS,
    is_multi_command_action,
    validate_conversation_id,
)
from .history_append_reason import last_append_reason
from .request_telemetry import emit_stage_event


from .oracle_mesh_contract import (
    ORACLE_MESH_READ_REQUEST_PATH,
    ORACLE_MESH_READ_POLL_PATH,
    ORACLE_MESH_READ_RESULT_PATH,
    ORACLE_MESH_READ_CANCEL_PATH,
    ORACLE_MESH_READ_BUSY_PATH,
    ORACLE_MESH_READ_CANCEL_POLL_PATH,
    ORACLE_MESH_READ_LANE_STATUS_PATH,
    ORACLE_MESH_READ_ORIGINAL_PATH,
    ORACLE_MESH_OWNERSHIP_MAP_ENV,
    ORACLE_MESH_LEGACY_MAP_LANE_ENV,
    RETIRED_OWNERSHIP_MAP,
    ORACLE_MESH_EXECUTION_MODE_ENV,
    EXECUTION_MODE_OFF,
    EXECUTION_MODE_MESH,
    EXECUTION_MODE_NATIVE,
    _EXECUTION_MODES,
    ORACLE_MESH_CHANNEL_SECRET_ENV,
    CONNECTOR_WATCH_READ_SECRET_ENV,
    ORACLE_MESH_CHANNEL_HEADER,
    _DISPATCH_TTL,
    _MAX_RESULT_BODY_BYTES,
    _MAX_BODY_BYTES,
    _MAX_DESKTOP_ENGINE_BODY_BYTES,
    _MAX_COMMAND_MESSAGE_CHARS,
    _MAX_COMMAND_MESSAGE_PARTS,
    _MAX_PATH_VALUE_CHARS,
    _SAFE_REF_CHARS,
    _PRESENCE_BODY_KEYS,
    _PRESENCE_ENTRY_KEYS,
    _PRESENCE_ENTRY_OPTIONAL_KEYS,
    _MAX_PRESENCE_BODY_BYTES,
    _MAX_FILE_TEXT_BYTES,
    _EXECUTOR,
    _COMMAND_ROOT_REF,
    _COMMAND_PATH_RELATIVE,
    _COMMAND_FILE_SENTINEL,
    _COMMAND_SHELL_LABEL,
    _COMMAND_ECHO_MARK,
    _COMMAND_ECHO_PREFIX,
    _REQUEST_KEYS,
    _RESULT_KEYS,
    _RESULT_BLOB_KEYS,
    _RESULT_OPTIONAL_KEYS,
    _DESKTOP_COMMAND_PREFIX,
    _DESKTOP_OPS,
    _DESKTOP_SHELL_LABEL,
    _DESKTOP_SCREENSHOT_MEDIA_TYPE,
    _DESKTOP_SCREENSHOT_MAGIC,
    _DESKTOP_ORIGINAL_MARKER_PREFIX,
    _EMPTY_RESULT_SHA256,
)

from .oracle_mesh_source import (
    legacy_map_lane_enabled,
    UnconfiguredOracleMeshReturnSource,
    OracleMeshReturnSource,
    _resolve_oracle_store_text,
    build_oracle_mesh_return_source,
    _mesh_source_unconfigured,
    _resolve_optional_secret,
    build_oracle_mesh_return_source_from_env,
    valid_claw_engine_desktop_secret,
    host_engine_lane_mount_marker,
)


async def resolve_oracle_mesh_execution(
    request: Request, *, path_relative: str, selected_device_id: str | None = None,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Decide whether one ordinary TXT request runs on the Mesh lane.

    Returns ``(target, None)`` when the request should execute on the
    management host, ``(None, None)`` when it must stay on the native lane, and
    ``(None, response)`` for a refusal that the caller must surface.

    Order matters: the ownership decision comes from the deployment map, so an
    unregistered PC is never filtered out by the native device directory first.
    Consent, consent withdrawal and the OFF switch are still enforced here —
    only the *native binding* requirement is dropped, never the checks.
    """

    if not getattr(request.app.state, "oracle_mesh_legacy_map_lane", True):
        # Retired on purpose: this request names a file for the deployment map, which
        # is no longer an authority. Tell the owner where the working path is instead
        # of a 403 that says "not yours" about a file that is theirs.
        return None, _error(
            409, "oracle_mesh_map_lane_retired",
            "이 방식은 더 이상 쓰지 않아요 — 내 컴퓨터 연결에서 폴더를 고르세요.",
        )
    source = getattr(request.app.state, "oracle_mesh_return_source", None)
    if getattr(source, "configured", False) is not True:
        return None, None
    mode = source.execution_mode
    if mode == EXECUTION_MODE_OFF:
        return None, None
    if mode == EXECUTION_MODE_NATIVE:
        return None, None

    session, denial = await _verified_owner_request(request)
    if denial is not None or session is None:
        return None, denial or _error(401, "canonical_session_required")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(identity, "resolve_connector_owner_scope", None)):
        return None, _error(503, "oracle_mesh_unconfigured")
    try:
        scope = await mode_connector_read(identity, "owner_scope", session_id=session.session_id)
    except Exception as exc:
        # #4139: this is the only place the canonical owner-scope refusal is
        # observed. The public projection is one fixed code, so the Identity
        # code is retained on the existing bounded stage-telemetry channel
        # (code + stage + request-scoped id only; build_stage_event sanitizes
        # the value and never carries a message).
        emit_stage_event(
            stage="mesh.owner_scope", outcome="error", duration_ms=0,
            code=getattr(exc, "code", None),
        )
        return None, _error(503, "oracle_mesh_device_directory_unavailable")
    account_ref = scope.get("account_ref") if isinstance(scope, dict) else None
    if not isinstance(account_ref, str) or not account_ref:
        return None, _error(503, "oracle_mesh_device_directory_unavailable")
    disposition = source.classify(account_ref=account_ref, path_relative=path_relative)
    if disposition == "none":
        # The deployment maps no Mesh target for this file: the request keeps
        # the native lane rather than silently executing somewhere else.
        return None, None
    if disposition == "foreign":
        # The file IS mapped, but only to other accounts. That is a hard
        # ownership refusal, never a lane fallback.
        return None, _error(403, "oracle_mesh_ownership_unverified")
    # Consent withdrawal is enforced HERE, before a run is staged: an owner
    # who withdrew the connector consent must be refused up front. Absence of
    # a consent record is not a precondition on this lane (no native
    # enrollment is required); a backend failure still fails closed.
    if callable(getattr(identity, "resolve_connector_enrollment_consent_for_device", None)):
        try:
            consent = await mode_connector_read(
                identity, "consent",
                session_id=session.session_id,
                device_id=source.device_hint_for(
                    account_ref=account_ref, path_relative=path_relative,
                    selected_device_id=selected_device_id,
                ),
            )
        except IdentityBridgeError as exc:
            if getattr(exc, "code", None) != "enrollment_consent_required":
                return None, _error(503, "oracle_mesh_unconfigured")
        except Exception:
            return None, _error(503, "oracle_mesh_unconfigured")
        else:
            if isinstance(consent, dict) and consent.get("withdrawn_at") is not None:
                return None, _error(403, "oracle_mesh_consent_required")
    target = source.target_for(
        account_ref=account_ref, path_relative=path_relative,
        device_id=selected_device_id,
    )
    if target is None:
        return None, _error(403, "oracle_mesh_ownership_unverified")
    return {
        "device_id": target.get("device_id") or target["node_ref"],
        "root_ref": target["root_ref"],
        "path_relative": target["path_relative"],
        "account_ref": account_ref,
    }, None


from .oracle_mesh_http import (
    _NO_STORE,
    _response,
    _error,
    _BODY_REFUSAL,
    _refused,
    _invalid_body,
    _read_json,
    _text_value,
    _ref,
    _read_body,
    _read_result_body,
    _channel_source,
    _channel_proof,
    _watch_read_proof,
)


from .oracle_mesh_dispatch import (
    oracle_mesh_read_request,
    _dispatch_workspace_id,
    dispatch_oracle_mesh_read_intent,
    _active_owner_link_node,
    _owner_command_target,
    dispatch_oracle_mesh_command_intent,
    dispatch_oracle_mesh_file_read_intent,
    dispatch_oracle_mesh_desktop_intent,
    _deployment_target_for,
)


from .oracle_mesh_desktop_ops import (
    _DESKTOP_KEY_NAMES,
    _DESKTOP_KEY_MODIFIER_CODES,
    _DESKTOP_RESERVED_KEY_COMBOS,
    _desktop_key_combo_is_valid,
    _parse_desktop_op_text,
    _DESKTOP_TYPE_MARKER,
    _desktop_text_ref,
)


from .oracle_mesh_presence import (
    _read_presence,
    _PairingRefusalLog,
    _refusal_reason,
    _pairing_refusal_log,
    _record_mesh_presence,
)


from .oracle_mesh_poll import (
    _oracle_mesh_poll_max_bytes,
    _oracle_mesh_poll_granted_root,
    _oracle_mesh_poll_share_roots,
    oracle_mesh_read_poll,
    oracle_mesh_read_cancel_check,
    oracle_mesh_read_cancel_poll,
    oracle_mesh_read_busy_check,
    oracle_mesh_read_lane_status,
)


def _verified_desktop_note(wire: dict[str, Any]) -> str | None:
    """Revalidate a desktop observation note: short text, no control bytes."""
    note = wire.get("content_utf8")
    if not isinstance(note, str):
        return None
    try:
        note.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in note) or "\x7f" in note:
        return None
    return note


def _verified_desktop_blob(
    wire: dict[str, Any], max_bytes: int | None = _MAX_FILE_TEXT_BYTES,
    raw: bytes | None = None,
) -> bytes | bytearray | None:
    """Revalidate a desktop screenshot blob, or ``b""`` when absent.

    Returns None for a malformed blob. Absence (act ops) is ``b""``, never
    an error: only a half-present blob is untrusted. ``raw`` is the body of
    the binary frame; the legacy JSON shape carries the same bytes as base64.
    """
    media = wire.get("content_blob_media_type")
    encoded = wire.get("content_blob_base64")
    digest = wire.get("content_blob_sha256")
    size = wire.get("content_blob_bytes")
    if raw is None and media is None and encoded is None and digest is None and size is None:
        return b""
    if media != _DESKTOP_SCREENSHOT_MEDIA_TYPE:
        return None
    if not isinstance(digest, str) or not digest:
        return None
    if isinstance(size, bool) or not isinstance(size, int):
        return None
    if size <= 0 or (max_bytes is not None and size > max_bytes):
        return None
    if raw is not None:
        # A binary frame never also carries the base64 copy: exactly one shape.
        if encoded is not None:
            return None
        blob = raw
    else:
        if not isinstance(encoded, str) or not encoded:
            return None
        try:
            blob = base64.b64decode(encoded, validate=True)
        except ValueError:
            return None
    if len(blob) != size or hashlib.sha256(blob).hexdigest() != digest:
        return None
    if not blob.startswith(_DESKTOP_SCREENSHOT_MAGIC):
        return None
    return blob


_DESKTOP_OP_LABELS = {
    "capture": "화면 캡처",
    "type": "문자 입력",
    "keys": "키 입력",
    "click": "마우스 클릭",
}


def _desktop_op_description(op: str, arg: str | None) -> str:
    label = _DESKTOP_OP_LABELS.get(op, op)
    if op == "keys" and arg:
        return f"키 입력 ({arg})"
    if op == "click" and arg:
        return f"마우스 클릭 ({arg})"
    return label


def _desktop_head(dispatch: dict[str, Any], wire: dict[str, Any], op: str, arg: str | None) -> list[str]:
    """The fixed head of one desktop message: what ran, how, what is known."""
    lines = [
        "COM1 데스크톱 " + _DESKTOP_OP_LABELS.get(op, op),
        "동작: " + _desktop_op_description(op, arg),
        "실행 방식: " + _DESKTOP_SHELL_LABEL,
    ]
    termination = wire["termination"]
    if termination == "captured":
        lines.append("종료 상태: 화면 관측 완료")
    elif termination == "acted":
        lines.append("종료 상태: 입력 전달 완료 (릴레이 연결·화면 확인 후 전송)")
    elif termination == "desktop_unavailable":
        lines.append("종료 상태: 데스크톱 응답 없음 (세션이 연결되지 않았거나 화면이 완성되지 않음)")
    elif termination == "timed_out":
        lines.append("종료 상태: 대기 시간 초과 (PC 입력의 도달을 확인하지 못함)")
    elif termination == "not_executed":
        lines.append("종료 상태: 실행되지 않음 (실행 경계에서 거부됨)")
    elif termination == "output_too_large":
        lines.append("종료 상태: 화면이 전송 한도를 초과")
    else:
        lines.append("종료 상태: " + str(termination))
    return lines


def _desktop_capture_content(
    dispatch: dict[str, Any], wire: dict[str, Any], op: str, arg: str | None,
    note: str, digest: str,
) -> str:
    """One conversation message for one real screen capture.

    The message carries the observation and the owner-scoped retrieval
    reference in a server-shaped marker line; the browser renders the image
    from that same-origin path. The bytes live in the private original
    store, pinned by the dispatch row.
    """
    lines = _desktop_head(dispatch, wire, op, arg)
    lines.append("관측: " + note)
    lines.append("SHA-256: " + digest)
    lines.append(
        _DESKTOP_ORIGINAL_MARKER_PREFIX + str(dispatch["dispatch_id"])
    )
    return "\n".join(lines)


def _desktop_act_content(
    dispatch: dict[str, Any], wire: dict[str, Any], op: str, arg: str | None,
    note: str,
) -> str:
    """One conversation message for one delivered desktop input."""
    lines = _desktop_head(dispatch, wire, op, arg)
    lines.append("관측: " + note)
    return "\n".join(lines)


def _desktop_failed_content(
    dispatch: dict[str, Any], wire: dict[str, Any], op: str, arg: str | None,
    note: str,
) -> str:
    """A desktop turn that observed no success stays an explicit notice."""
    lines = _desktop_head(dispatch, wire, op, arg)
    if note:
        lines.append("관측: " + note)
    if wire["termination"] == "output_too_large":
        lines.append(
            "화면 본문은 전송 한도를 초과하여 전달되지 않았습니다. "
            "원문이 서버에 보관되지 않았으므로 다시 조회할 수 없습니다. "
            "한 번에 관측하는 화면 범위를 좁혀 다시 실행하십시오."
        )
    else:
        lines.append(
            "PC 화면·입력에 도달하지 못했습니다. "
            "같은 입력을 반복하기 전에 화면 캡처로 현재 상태를 확인하십시오."
        )
    return "\n".join(lines)


def _verified_result_text(
    dispatch: dict[str, Any], wire: dict[str, Any],
    max_bytes: int | None = _MAX_FILE_TEXT_BYTES,
) -> str | None:
    """Revalidate a submission against the claimed dispatch; return the text."""
    text = wire["content_utf8"]
    if not isinstance(text, str):
        return None
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if (
        (max_bytes is not None and len(raw) > max_bytes)
        or wire["content_bytes"] != len(raw)
        or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text)
        or not isinstance(wire["content_sha256"], str)
        or wire["content_sha256"] != hashlib.sha256(raw).hexdigest()
    ):
        return None
    return text


def _verified_read_result_text(
    dispatch: dict[str, Any], wire: dict[str, Any],
) -> str | None:
    """Verify a read body by its own bytes and digest (#5882 A).

    The PC read lane no longer has a product cap of its own: a 20 MB answer
    bound refused a body the connector had already produced and the digest had
    already proved, while the reader's real limits are the connector's read
    envelope (what it is asked for) and the store. A file larger than one
    answer is paged by the Engine from its first range, not rejected here.
    Other read consumers keep the shared 6 MB envelope unchanged.
    """
    if dispatch.get("root_ref") == _PC_FILES_READ_ROOT_REF:
        return _verified_result_text(dispatch, wire, max_bytes=None)
    return _verified_result_text(dispatch, wire, max_bytes=_MAX_FILE_TEXT_BYTES)


def _pc_share_unavailable_output(output: str) -> bool:
    """#8037: the closed share-unavailable verdict the connector delivers.

    Only the exact closed shape counts — ok=false with the one reviewed code.
    Any other body keeps the lane's existing judgement.
    """
    try:
        parsed = json.loads(output)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(parsed, dict)
        and parsed.get("ok") is False
        and parsed.get("error") == PC_SHARE_UNAVAILABLE_CODE
    )


def _command_header(dispatch: dict[str, Any], wire: dict[str, Any]) -> list[str]:
    """The fixed head of one command message: what ran, how, and what is known.

    A wait timeout is never reported as a terminated process, and an unobserved
    exit code stays "확인되지 않음" instead of 0.
    """
    lines = [
        "COM1 명령 실행 결과",
        "명령: " + str(dispatch.get("command_text") or ""),
        "실행 방식: " + _COMMAND_SHELL_LABEL,
        "출력: stdout+stderr 병합",
    ]
    termination = wire["termination"]
    if termination == "timed_out":
        lines.append("종료 상태: 대기 시간 초과 (PC 프로세스가 계속 실행 중일 수 있음)")
        lines.append("종료 코드: 확인되지 않음")
    elif termination == "cancelled":
        lines.append("종료 상태: 중지 요청됨 (PC에서 중지가 확인되지 않음; 계속 실행 중일 수 있음)")
        lines.append("종료 코드: 확인되지 않음")
    elif termination == "no_reply":
        lines.append("종료 상태: 콘솔 응답 없음")
        lines.append("종료 코드: 확인되지 않음")
    elif termination == "not_executed":
        # The command never reached the PC: the execution boundary refused it
        # (an argv element over the host limit, a bad node reference). Reporting
        # that as "콘솔 응답 없음" would blame a console that was never asked.
        lines.append("종료 상태: 실행되지 않음 (실행 경계에서 거부됨)")
        lines.append("종료 코드: 확인되지 않음")
    elif termination == "bad_reply":
        # The console answered and its envelope could not be read. Calling that
        # "응답 없음" would blame a console that did reply, and printing the raw
        # bytes would present mangled text as though the PC had printed it.
        lines.append("종료 상태: PC 응답을 해석하지 못했습니다 (인코딩 오류)")
        lines.append(
            "종료 코드: " + (
                str(wire["exit_code"])
                if isinstance(wire["exit_code"], int)
                else "확인되지 않음"
            )
        )
    elif termination == "no_exit_code":
        # The console answered and the shell reached the statement this lane
        # appends, but PowerShell only records $LASTEXITCODE for a native program
        # or script, so a cmdlet-only pipeline reports no number. The output is
        # delivered whole and the code stays "확인되지 않음" — never 0.
        lines.append(
            "종료 상태: 콘솔 응답 완료 (cmdlet 전용 파이프라인이라 종료 코드가 보고되지 않음)"
        )
        lines.append("종료 코드: 확인되지 않음")
    elif termination == "output_too_large":
        lines.append("종료 상태: 출력이 전송 한도를 초과")
        lines.append(
            "종료 코드: " + (
                str(wire["exit_code"])
                if isinstance(wire["exit_code"], int)
                else "확인되지 않음"
            )
        )
    else:
        lines.append("종료 상태: " + str(termination))
        lines.append(
            "종료 코드: " + (
                str(wire["exit_code"])
                if isinstance(wire["exit_code"], int)
                else "확인되지 않음"
            )
        )
    return lines


def _command_result_content(
    dispatch: dict[str, Any], wire: dict[str, Any], output: str,
) -> str:
    """One conversation message for one real command execution.

    The output is delimited by explicit markers so its own leading/trailing
    whitespace and newlines survive the shared history projection unchanged:
    the markers, not the output, are the message edges.
    """
    lines = _command_header(dispatch, wire)
    lines.append("--- 출력 시작 ---")
    lines.append(output)
    lines.append("--- 출력 끝 ---")
    return "\n".join(lines)


def _command_output_withheld_content(
    dispatch: dict[str, Any], wire: dict[str, Any],
) -> str:
    """An execution whose output never crossed the wire.

    The executor withheld the body at the wire envelope, so there is no
    stored original to point at: the message says exactly that instead of
    claiming the dispatch row holds a body it does not. Only the observed
    termination and exit code are delivered.
    """
    lines = _command_header(dispatch, wire)
    lines.append(
        "출력 본문은 전송 한도를 초과하여 전달되지 않았습니다. "
        "원문이 서버에 보관되지 않았으므로 다시 조회할 수 없습니다. "
        "출력 범위를 좁힌 명령으로 다시 실행하십시오."
    )
    return "\n".join(lines)


def _command_original_stored_content(
    dispatch: dict[str, Any], wire: dict[str, Any], output: str,
) -> str:
    """One notice for an output larger than the conversation budget.

    The full output passed verification (bytes and digest are pinned on the
    dispatch row) and the private original store accepted it before this
    message was built, so "stored" is only claimed after the put succeeds.
    The conversation carries a head preview sized to this message's own frame —
    a preview taken from another shape could overflow the shared per-message
    limit and strand the result — and the whole original is fetched through the
    owner-scoped retrieval reference below.
    """
    head = _command_head(dispatch, wire)
    opening = head + [
        "출력 " + str(wire["content_bytes"]) + "바이트 전체는 비공개 원문 저장소에 "
        "보관되었습니다. 아래는 앞부분 미리보기입니다.",
        "--- 출력 미리보기 시작 ---",
    ]
    closing = [
        "--- 출력 미리보기 끝 ---",
        "SHA-256: " + str(wire["content_sha256"]),
        "원문 전체 조회: GET "
        + "/api/claw/connector/mesh-results/" + str(dispatch["dispatch_id"]),
    ]
    room = (
        _MAX_COMMAND_MESSAGE_CHARS
        - sum(len(line) for line in opening + closing)
        - (len(opening) + len(closing))
    )
    return "\n".join(opening + [output[:max(room, 0)]] + closing)


def _command_part_messages(head: list[str], parts: list[str]) -> list[str]:
    """Wrap each output part in the shared frame, in order.

    ``"".join(parts)`` is the output verbatim, so the conversation carries every
    byte across its messages; the frame lines are display furniture and the
    pinned digest belongs to the unwrapped body.
    """
    total = str(len(parts))
    messages = []
    for index, part in enumerate(parts):
        lines = list(head)
        lines.append("--- 출력 " + str(index + 1) + "/" + total + " 시작 ---")
        lines.append(part)
        lines.append("--- 출력 끝 ---")
        messages.append("\n".join(lines))
    return messages


def _file_read_part_messages(parts: list[str]) -> list[str]:
    total = str(len(parts))
    messages = []
    for index, part in enumerate(parts):
        lines = ["PC 파일 읽기 결과"]
        lines.append("--- 출력 " + str(index + 1) + "/" + total + " 시작 ---")
        lines.append(part)
        lines.append("--- 출력 끝 ---")
        messages.append("\n".join(lines))
    return messages


async def _store_oracle_mesh_read_original(
    history_store: Any, *, dispatch: dict[str, Any],
    conversation_id: str, message_id: str, raw: str,
    expected_sha256: str, expected_bytes: int,
) -> None:
    """Store one verified read body through the existing command-result store.

    The raw bytes (file text or a bounded ``PADIEM_PC_FILE_ERROR`` marker) are
    keyed by the same deterministic result message id the command result mode
    already uses. No new store or DB row is introduced. The small-output method
    is preferred because the over-budget method skips short texts; both apply
    the same owner and dispatch-pin checks.
    """
    store = getattr(history_store, "store_oracle_mesh_command_result", None)
    if not callable(store):
        store = getattr(history_store, "store_oracle_mesh_original", None)
    if not callable(store):
        raise HistoryError("oracle mesh result store is unavailable")
    await store(
        user_id=dispatch["user_id"], dispatch_id=dispatch["dispatch_id"],
        conversation_id=conversation_id, message_id=message_id,
        raw=raw, expected_sha256=expected_sha256,
        expected_bytes=expected_bytes,
    )


def _file_read_stored_content(
    dispatch: dict[str, Any], wire: dict[str, Any], output: str,
) -> str:
    """Read-lane twin of the stored-original notice, sized to its own frame."""
    opening = [
        "PC 파일 읽기 결과",
        "출력 " + str(wire["content_bytes"]) + "바이트 전체는 비공개 원문 저장소에 "
        "보관되었습니다. 아래는 앞부분 미리보기입니다.",
        "--- 출력 미리보기 시작 ---",
    ]
    closing = [
        "--- 출력 미리보기 끝 ---",
        "SHA-256: " + str(wire["content_sha256"]),
        "원문 전체 조회: GET "
        + "/api/claw/connector/mesh-results/" + str(dispatch["dispatch_id"]),
    ]
    room = (
        _MAX_COMMAND_MESSAGE_CHARS
        - sum(len(line) for line in opening + closing)
        - (len(opening) + len(closing))
    )
    return "\n".join(opening + [output[:max(room, 0)]] + closing)


def _command_markers() -> tuple[str, str]:
    """The widest part-marker pair one message can carry.

    The digit count comes from the part guard, so the widest index/total pair
    the caller can ever print is already paid for.
    """
    digits = len(str(_MAX_COMMAND_MESSAGE_PARTS + 1))
    return (
        "--- 출력 " + "9" * digits + "/" + "9" * digits + " 시작 ---",
        "--- 출력 끝 ---",
    )


def _command_part_budget(head: list[str]) -> int:
    """How many characters one output part may use in this message shape.

    Derived, never estimated: the shared per-message bound minus the message
    head minus the marker frame around the part.
    """
    start, end = _command_markers()
    return _MAX_COMMAND_MESSAGE_CHARS - len("\n".join(head)) - len(start) - len(end) - 3


def _command_head(dispatch: dict[str, Any], wire: dict[str, Any]) -> list[str]:
    """The message head, fitted so an output part always has room.

    A command can now be as long as its dispatch row allows, and the head
    echoes it. Left unbounded, every part of a large output would overflow the
    shared per-message limit and the whole result would strand on a storage
    refusal. The echo is a label and the output is the payload, so when the head
    does not fit the label keeps at most half of what the fixed header lines and
    the marker frame leave over; the full command stays in the user's own turn
    and in the dispatch row, and the mark says so.
    """
    head = _command_header(dispatch, wire)
    if _command_part_budget(head) >= 1:
        return head
    index = next(
        (position for position, line in enumerate(head)
         if line.startswith(_COMMAND_ECHO_PREFIX)),
        None,
    )
    if index is None:
        return head
    start, end = _command_markers()
    others = len("\n".join(
        line for position, line in enumerate(head) if position != index
    ))
    room = max(
        0,
        (
            _MAX_COMMAND_MESSAGE_CHARS
            - others
            - len(start)
            - len(end)
            - 4
            - len(_COMMAND_ECHO_MARK)
        ) // 2,
    )
    bounded = list(head)
    bounded[index] = bounded[index][:room] + _COMMAND_ECHO_MARK
    if _command_part_budget(bounded) >= 1:
        return bounded
    # No label fits beside the output at all: drop it rather than let the
    # message carry no result. The dispatch row still holds the whole command.
    del bounded[index]
    return bounded


def _command_output_parts(output: str, limit: int) -> list[str]:
    """Partition one output so that ``"".join(parts)`` is the output verbatim.

    #4139: the former splitter kept the pending part as a joined string, so an
    empty line was indistinguishable from "nothing buffered" and every line
    boundary it crossed was swallowed — ``"\\n" + "a"*7401`` came back 7401
    characters. Each terminator now travels with its own line
    (``splitlines(keepends=True)``), so blank lines, consecutive newlines, CRLF
    and one long line reassemble byte for byte. A line longer than the limit is
    sliced, never cut, and no part is ever dropped.
    """
    if limit < 1:
        # Fail fast instead of looping: a head that leaves no room is a caller
        # bug, and slicing against a zero or negative bound would never finish.
        raise ValueError("output part limit must be at least one character")
    if len(output) <= limit:
        return [output]
    parts: list[str] = []
    buffer = ""
    for line in output.splitlines(keepends=True):
        while len(line) > limit:
            room = limit - len(buffer)
            if room > 0:
                buffer += line[:room]
                line = line[room:]
            parts.append(buffer)
            buffer = ""
        if len(buffer) + len(line) > limit:
            parts.append(buffer)
            buffer = line
        else:
            buffer += line
    if buffer:
        parts.append(buffer)
    return parts


async def oracle_mesh_read_result(request: Request) -> JSONResponse:
    """Executor submit: secret + single-use nonce, verified, appended once."""
    ensure_result_log_host_visible()
    resp, bundle = await _oracle_mesh_read_result_verify(request)
    if resp is not None:
        return resp
    wire = bundle["wire"]
    result_blob_raw = bundle["result_blob_raw"]
    result_log = bundle["result_log"]
    result_run_hash = bundle["result_run_hash"]
    result_dispatch_id = bundle["result_dispatch_id"]
    history_store = bundle["history_store"]
    dispatch = bundle["dispatch"]
    claim = bundle["claim"]

    resp, bundle = await _oracle_mesh_read_result_outcome(
        dispatch, result_blob_raw, wire,
    )
    if resp is not None:
        return resp
    outcome = bundle["outcome"]
    content = bundle["content"]
    summary = bundle["summary"]
    status = bundle["status"]
    command_output = bundle["command_output"]
    read_output = bundle["read_output"]
    read_stored_output = bundle["read_stored_output"]
    desktop_note = bundle["desktop_note"]
    desktop_blob = bundle["desktop_blob"]
    desktop_op = bundle["desktop_op"]
    desktop_arg = bundle["desktop_arg"]
    result_digest = bundle["result_digest"]
    result_size = bundle["result_size"]
    # Every stored message is now bounded by the splitter, so the former
    # 1 000-character refusal has no case left to serve.

    # Pin the first accepted result. A resend after a transient store failure
    # must be the identical bytes: the executor holds them and never re-reads
    # the PC file, and a differing resend is refused rather than appended.
    try:
        try:
            same_result = await history_store.record_oracle_mesh_first_result(
                dispatch_id=wire["dispatch_id"],
                content_sha256=result_digest,
                content_bytes=result_size,
                termination=wire.get("termination") if isinstance(wire.get("termination"), str) else None,
                exit_code=wire.get("exit_code"),
            )
        except TypeError:
            same_result = await history_store.record_oracle_mesh_first_result(
                dispatch_id=wire["dispatch_id"],
                content_sha256=result_digest,
                content_bytes=result_size,
            )
    except Exception:
        # A pin failure must stay retryable: park the received row so the
        # identical resend is accepted as claim="retry" instead of dying
        # on 409. Pin comparison and idempotent append still prevent any
        # second delivery.
        try:
            await history_store.mark_oracle_mesh_store_failed(
                dispatch_id=wire["dispatch_id"],
            )
        except Exception:
            pass
        return _error(503, "oracle_mesh_dispatch_unavailable")
    if same_result is not True:
        # Park the claim again: a rejected resend must not burn the retry the
        # executor still legitimately owns for its identical bytes.
        try:
            await history_store.mark_oracle_mesh_store_failed(
                dispatch_id=wire["dispatch_id"],
            )
        except Exception:
            pass
        return _error(409, "oracle_mesh_result_fingerprint_mismatch")

    run_row = None
    try:
        run_row = await history_store.get_claw_run(
            dispatch["user_id"], dispatch["run_id"],
        )
    except Exception:
        run_row = None
    conversation_id = (
        validate_conversation_id((run_row or {}).get("conversation_id"))
        if isinstance(run_row, dict) else None
    )
    if not conversation_id:
        try:
            await history_store.finish_oracle_mesh_dispatch(
                dispatch_id=wire["dispatch_id"], outcome="failed",
            )
        except Exception:
            pass
        return _error(404, "oracle_mesh_run_unavailable")

    base_message_id = result_message_id(
        conversation_id=conversation_id,
        command_id=dispatch["command_id"],
        revision_ref=dispatch["revision_ref"],
    )
    from .chat_pc_session import project_history_result, is_session_dispatch
    session_messages = project_history_result(run_row, dispatch, command_output)
    if read_stored_output is not None:
        # #5015: the Engine read lane retrieves the exact verified body from
        # this existing store. Storing before the conversation projection
        # keeps a store failure retryable with the same bytes; the executor
        # is never asked to read the PC file again.
        try:
            await _store_oracle_mesh_read_original(
                history_store, dispatch=dispatch,
                conversation_id=conversation_id, message_id=base_message_id,
                raw=read_stored_output,
                expected_sha256=result_digest,
                expected_bytes=result_size,
            )
        except HistoryForbidden:
            try:
                await history_store.finish_oracle_mesh_dispatch(
                    dispatch_id=wire["dispatch_id"], outcome="failed",
                )
            except Exception:
                pass
            return _error(403, "oracle_mesh_conversation_forbidden")
        except Exception:
            try:
                await history_store.mark_oracle_mesh_store_failed(
                    dispatch_id=wire["dispatch_id"],
                )
            except Exception:
                pass
            return _error(503, "oracle_mesh_original_unavailable")
    resp, bundle = await _oracle_mesh_read_result_store(
        base_message_id=base_message_id,
        command_output=command_output,
        content=content,
        conversation_id=conversation_id,
        desktop_arg=desktop_arg,
        desktop_blob=desktop_blob,
        desktop_note=desktop_note,
        desktop_op=desktop_op,
        dispatch=dispatch,
        history_store=history_store,
        is_session_dispatch=is_session_dispatch,
        read_output=read_output,
        result_digest=result_digest,
        result_size=result_size,
        summary=summary,
        wire=wire,
    )
    if resp is not None:
        return resp
    messages = bundle["messages"]
    if session_messages is not None:
        messages = session_messages
    appended = False
    # #5015: a run that may hold more than one PC tool call stores each
    # command's own result beside the others and never seals the run row, so
    # one command's completion is never read as the whole work's completion.
    command_scope = None
    if is_multi_command_action((run_row or {}).get("action")):
        command_scope = dispatch.get("command_id")
    # #6460 step 3: a model-driven desktop loop stages one dispatch per step.
    # Each step's message is evidence of that step alone, so it never writes
    # the run's terminal result; the verified final answer owns that.
    step_message_only = (
        command_scope is None
        and dispatch.get("kind") == "desktop"
        and isinstance(dispatch.get("tool_call_ref"), str)
        and bool(dispatch["tool_call_ref"])
        and len(messages) == 1
    )
    append_step = getattr(history_store, "append_step_result_message", None)
    if step_message_only and not callable(append_step):
        step_message_only = False
    try:
        for index, part in enumerate(messages):
            message_id = base_message_id if len(messages) == 1 else (
                base_message_id + "_p" + str(index)
            )
            if step_message_only:
                appended = await append_step(
                    user_id=dispatch["user_id"],
                    run_id=dispatch["run_id"],
                    message_id=message_id,
                    content=part,
                ) or appended
                continue
            appended = await history_store.append_local_task_result(
                user_id=dispatch["user_id"],
                run_id=dispatch["run_id"],
                message_id=message_id,
                summary=summary,
                content=part,
                status=("failed" if command_scope is not None and outcome == "failed" else status),
                # A terminal result is the only caller that opts out of the
                # shared edge trim; every other message keeps today's behavior.
                preserve_edges=(dispatch.get("kind") == "command"),
                command_scope=command_scope,
            ) or appended
        if command_scope is not None and outcome == "failed":
            # Seal before acknowledging the queue result: an unavailable Chat
            # store leaves the dispatch retryable with the same pinned result.
            await history_store.seal_run_terminal(
                user_id=dispatch["user_id"], run_id=dispatch["run_id"],
                summary="pc_read_failed", status="failed",
            )
    except HistoryForbidden:
        # Ownership refusal is final: retrying cannot change it.
        try:
            await history_store.finish_oracle_mesh_dispatch(
                dispatch_id=wire["dispatch_id"], outcome="failed",
            )
        except Exception:
            pass
        return _error(403, "oracle_mesh_conversation_forbidden")
    except Exception:
        # Transient conversation-store failure. The verified result is parked
        # (claim and expiry intact) so the executor can resend the SAME result
        # — the PC file is not read again, and the stable message id keeps the
        # eventual append exactly-once.
        try:
            await history_store.mark_oracle_mesh_store_failed(
                dispatch_id=wire["dispatch_id"],
            )
        except Exception:
            pass
        return _error(503, "oracle_mesh_append_unavailable")
    store_stage = "stored" if appended else "not_appended"
    # #7841 instrumentation: a refused append names the guard that refused it
    # and the run row it saw before the write. Values only; the stored line is
    # unchanged, and nothing here changes a return value or a write.
    log_pc_result_store_stage(
        result_log, stage=store_stage, run_hash=result_run_hash,
        dispatch_id=result_dispatch_id,
        reason=last_append_reason() if not appended else None,
        run_action=_pc_result_word(
            (run_row or {}).get("action"), _PC_RESULT_ACTION_WORDS,
        ),
        run_status_before=_pc_result_word(
            (run_row or {}).get("status"), _PC_RESULT_STATUS_WORDS,
        ),
        scoped=command_scope is not None,
    )
    try:
        finished = await history_store.finish_oracle_mesh_dispatch(
            dispatch_id=wire["dispatch_id"], outcome=outcome,
        )
    except Exception:
        result_log.info("pc_result stage=queue_finish_error run_hash=%s dispatch_id=%s", result_run_hash, result_dispatch_id)
    else:
        stage = "queue_finished" if finished else "queue_not_finished"
        result_log.info("pc_result stage=%s run_hash=%s dispatch_id=%s", stage, result_run_hash, result_dispatch_id)
    return _response({
        "ok": True,
        "runId": dispatch["run_id"],
        "commandId": dispatch["command_id"],
        "appended": bool(appended),
        "status": status,
        "claim": claim,
        "executor": _EXECUTOR,
        "brokerAcknowledged": False,
    })


async def _oracle_mesh_read_result_verify(
    request: Request,
) -> tuple[JSONResponse | None, dict[str, object]]:
    """서명·nonce·lease·termination·디스패치 조회 구간.

    본문은 리팩터 전 `oracle_mesh_read_result`의 연속 구간을 글자 그대로 옮긴다.
    보안 검사 순서와 `stage=received` 로그의 자리·문구를 그대로 지킨다.
    """
    parsed_result = await _read_result_body(request)
    if parsed_result is None:
        return _invalid_body("result"), {}
    wire, result_blob_raw = parsed_result
    if _ref(wire.get("dispatch_id"), 128) is None:
        return _invalid_body("result", "dispatch_id"), {}
    if _ref(wire.get("nonce"), 128) is None:
        return _invalid_body("result", "nonce"), {}
    submitted_node = wire.get("node_ref")
    if submitted_node is not None and (
        not isinstance(submitted_node, str) or not submitted_node
        or len(submitted_node) > 256
        or any(
            ch not in _SAFE_REF_CHARS and ch not in "\\/"
            for ch in submitted_node
        )
    ):
        return _invalid_body("result", "node_ref"), {}
    if wire.get("termination") not in (
        "exited", "cancelled", "timed_out", "no_reply", "no_exit_code",
        "not_executed", "output_too_large",
        "captured", "acted", "desktop_unavailable",
    ):
        return _invalid_body("result", "termination"), {}
    # #4139: a wait timeout and a console that never answered have NO observed
    # exit code. That is carried as null, never invented as 0; only a real
    # "exited" run must report an integer. A desktop turn never reports one
    # at all — there is no console sentinel on that lane.
    if wire.get("exit_code") is None:
        # ``no_exit_code`` keeps the code unobserved: PowerShell records
        # $LASTEXITCODE only for a native program or script, so a cmdlet-only
        # pipeline answers completely without reporting a number.
        if wire.get("termination") not in (
            "timed_out", "no_reply", "no_exit_code", "not_executed",
            "captured", "acted", "desktop_unavailable", "output_too_large",
            # An owner's stop ends the client, so nothing was ever observed from
            # the PC's console. That is carried as null, never invented as 0.
            "cancelled",
        ):
            return _invalid_body("result", "exit_code_missing"), {}
    elif isinstance(wire.get("exit_code"), bool) or not isinstance(wire.get("exit_code"), int):
        return _invalid_body("result", "exit_code_type"), {}
    if wire.get("content_bytes") == 0 and wire.get("content_sha256") == "":
        # Legacy empty-read shape: canonicalize before verification and
        # pinning so a 0-byte outcome is delivered instead of stranding.
        wire = {**wire, "content_sha256": _EMPTY_RESULT_SHA256}

    mesh_source = _channel_source(request)
    if mesh_source is None:
        return _error(503, "oracle_mesh_unconfigured"), {}
    if not _channel_proof(request, mesh_source):
        return _error(403, "oracle_mesh_channel_rejected"), {}
    history_store = getattr(request.app.state, "history_store", None)
    for method in ("consume_oracle_mesh_dispatch", "finish_oracle_mesh_dispatch",
                   "mark_oracle_mesh_store_failed",
                   "record_oracle_mesh_first_result",
                   "store_oracle_mesh_original",
                   "get_claw_run", "append_local_task_result"):
        if not callable(getattr(history_store, method, None)):
            return _error(503, "oracle_mesh_unconfigured"), {}

    try:
        dispatch = await history_store.consume_oracle_mesh_dispatch(
            dispatch_id=wire["dispatch_id"], nonce=wire["nonce"],
            node_ref=submitted_node,
        )
    except Exception:
        return _error(503, "oracle_mesh_dispatch_unavailable"), {}
    if dispatch is None:
        # Unknown, expired, already-consumed or nonce-mismatched dispatch. A
        # concurrent second submit of the same result loses the atomic update
        # here and is refused, rather than looking like the accepted request.
        return _error(409, "oracle_mesh_dispatch_rejected"), {}
    from .pc_correlation import run_hash as _result_run_hash, dispatch_id as _result_dispatch_id
    result_run_hash = _result_run_hash(dispatch.get("run_id")) or "none"
    result_dispatch_id = _result_dispatch_id(wire.get("dispatch_id")) or "none"
    result_log = _RESULT_LOG
    result_log.info("pc_result stage=received run_hash=%s dispatch_id=%s", result_run_hash, result_dispatch_id)
    claim = dispatch.get("claim")
    if claim not in ("first", "retry"):
        return _error(503, "oracle_mesh_dispatch_unavailable"), {}
    return None, {
        "wire": wire,
        "result_blob_raw": result_blob_raw,
        "result_log": result_log,
        "result_run_hash": result_run_hash,
        "result_dispatch_id": result_dispatch_id,
        "history_store": history_store,
        "dispatch": dispatch,
        "claim": claim,
    }


async def _oracle_mesh_read_result_outcome(
    dispatch: dict, result_blob_raw: bytes | None, wire: dict,
) -> tuple[JSONResponse | None, dict[str, object]]:
    """결과 검증·outcome 산출 구간 (본문 글자 그대로)."""
    outcome = "done"
    content = ""
    summary = ""
    status = ""
    #: #4139: the verified body of each lane, kept so a result larger than one
    #: conversation message can be split across deterministic message ids.
    command_output: str | None = None
    read_output: str | None = None
    #: #5015: the verified read body (a successful file or a bounded error
    #: marker) is stored through the existing original store before the
    #: conversation message is built, so the Engine result mode can re-feed
    #: exact bytes and the model lane sees the same error mapping.
    read_stored_output: str | None = None
    #: #4139 desktop lane: the verified observation note, the verified
    #: screenshot bytes (None when the turn carries no image) and the op the
    #: dispatch row ordered. Messages are built after the pin below.
    desktop_note: str | None = None
    desktop_blob: bytes | None = None
    desktop_op: str | None = None
    desktop_arg: str | None = None
    result_digest = wire["content_sha256"] if wire["content_bytes"] else _EMPTY_RESULT_SHA256
    result_size = wire["content_bytes"]
    if dispatch.get("kind") != "desktop" and (
        result_blob_raw is not None
        or any(key in wire for key in _RESULT_BLOB_KEYS)
    ):
        # Screenshot evidence on a non-desktop turn is untrusted by shape.
        # The consumed dispatch still closes as failed and nothing reaches
        # the conversation; an identical resend pins the same digest and
        # lands on the same verdict instead of appending twice.
        outcome = "failed"
        summary = "untrusted-result"
        status = "failed"
        content = (
            "실행 결과를 검증하지 못했습니다. "
            "사유: 결과 무결성 불일치."
        )
    elif dispatch.get("kind") == "command":
        # #4139 terminal lane. The body is the command output, verified with the
        # same UTF-8/SHA rules; the exit code is whatever the PC reported, and a
        # console that never answered stays "확인되지 않음". A large output is
        # split across messages, so this branch never rejects a verified result.
        verified_output = _verified_result_text(
            dispatch, wire, max_bytes=_MAX_FILE_TEXT_BYTES,
        )
        command_text = dispatch.get("command_text")
        if (
            verified_output is None
            or not isinstance(command_text, str) or not command_text
        ):
            outcome = "failed"
            summary = "untrusted-result"
            status = "failed"
            content = (
                "명령 실행 결과를 검증하지 못했습니다. "
                "사유: 결과 무결성 불일치."
            )
        else:
            content = _command_result_content(dispatch, wire, verified_output)
            command_output = verified_output
            if _pc_share_unavailable_output(verified_output):
                # #8037: the share bound closed this command. The row finishes
                # (the console answered a closed verdict), the turn is a named
                # failure, and the owner reads the one guidance sentence — not
                # a wedged command line.
                outcome, summary, status = "done", PC_SHARE_UNAVAILABLE_CODE, "failed"
                content = (
                    "PC 명령이 네트워크 공유에 연결하지 못해 20초 만에 정리되었습니다.\n"
                    + PC_SHARE_UNAVAILABLE_MESSAGE_KO
                )
            elif wire["termination"] in ("exited", "output_too_large"):
                if wire["exit_code"] == 0:
                    outcome, summary, status = "done", "exited/0", "completed"
                else:
                    outcome = "failed"
                    summary = str(wire["termination"]) + "/" + str(wire["exit_code"])
                    status = "failed"
            elif wire["termination"] == "not_executed":
                # Nothing ran, so nothing succeeded: a refusal is reported as a
                # failure of this turn without inventing a program exit code.
                outcome = "failed"
                summary = "not_executed"
                status = "failed"
            elif wire["termination"] == "no_exit_code":
                # Delivered and complete, with the code unobserved: the console
                # answered and the shell ran the appended sentinel statement, so
                # the turn is finished, while nothing here claims exit 0.
                outcome, summary, status = "done", "no_exit_code", "completed"
            else:
                outcome = "failed"
                summary = str(wire["termination"])
                status = "failed"
    elif dispatch.get("kind") == "desktop":
        # #4139 desktop lane. The note is the observation text, verified with
        # the same text rules; the screenshot (captures only) is verified
        # beside it with its own digest. A desktop turn never reports an exit
        # code — there is no console sentinel on this lane — so a non-null
        # code is untrusted. The pin covers the screenshot when one is
        # present, else the note, matching what the executor pinned first.
        parsed = _parse_desktop_op_text(dispatch.get("command_text"))
        verified_note = _verified_desktop_note(wire)
        verified_blob = _verified_desktop_blob(wire, raw=result_blob_raw)
        if (
            parsed is None
            or verified_note is None
            or verified_blob is None
            or wire.get("exit_code") is not None
        ):
            outcome = "failed"
            summary = "untrusted-result"
            status = "failed"
            content = (
                "데스크톱 실행 결과를 검증하지 못했습니다. "
                "사유: 결과 무결성 불일치."
            )
        else:
            blob = bytes(verified_blob)
            note_raw = verified_note.encode("utf-8")
            if blob:
                pinned_ok = (
                    wire["content_sha256"] == hashlib.sha256(blob).hexdigest()
                    and wire["content_bytes"] == len(blob)
                )
            else:
                pinned_ok = (
                    wire["content_sha256"] == hashlib.sha256(note_raw).hexdigest()
                    and wire["content_bytes"] == len(note_raw)
                )
            if not pinned_ok:
                outcome = "failed"
                summary = "untrusted-result"
                status = "failed"
                content = (
                    "데스크톱 실행 결과를 검증하지 못했습니다. "
                    "사유: 결과 무결성 불일치."
                )
            else:
                desktop_op, desktop_arg = parsed
                desktop_note = verified_note
                desktop_blob = blob if blob else None
                if wire["termination"] == "captured" and blob:
                    outcome, summary, status = "done", "captured", "completed"
                    content = ""
                elif wire["termination"] == "acted" and not blob:
                    outcome, summary, status = "done", "acted", "completed"
                    content = ""
                elif wire["termination"] in (
                    "desktop_unavailable", "timed_out", "not_executed",
                    "output_too_large",
                ):
                    outcome = "failed"
                    summary = str(wire["termination"])
                    status = "failed"
                    content = ""
                else:
                    outcome = "failed"
                    summary = "untrusted-result"
                    status = "failed"
                    content = (
                        "데스크톱 실행 결과를 검증하지 못했습니다. "
                        "사유: 결과 무결성 불일치."
                    )
    elif wire["termination"] == "exited" and wire["exit_code"] == 0:
        verified_text = _verified_read_result_text(dispatch, wire)
        if verified_text is None:
            # A clean execution claim with tampered body+hash is refused, and
            # the consumed dispatch still closes as failed: the bytes are
            # untrusted and must never reach a conversation.
            outcome = "failed"
            summary = "untrusted-result"
            status = "failed"
            content = (
                "로컬 러너 작업 결과를 검증하지 못했습니다. "
                f"명령: {dispatch['command_id']}, 사유: 결과 무결성 불일치."
            )
        else:
            content = (
                "PC 파일 읽기 결과\n--- 출력 1/1 시작 ---\n"
                + (verified_text if verified_text else "(빈 파일)")
                + "\n--- 출력 끝 ---"
            )
            read_output = verified_text if verified_text else None
            read_stored_output = read_output
            summary = "exited/0"
            status = "completed"
    elif wire["termination"] == "cancelled":
        summary = "cancelled"
        status = "cancelled"
        outcome = "failed"
        content = (
            "로컬 러너 작업에 중지 요청이 기록되었습니다. "
            "PC에서 중지가 확인되지 않았을 수 있습니다. "
            f"명령: {dispatch['command_id']}."
        )
    elif dispatch.get("kind") == "read":
        # #5015: a failed read keeps its verified body. The executor reports
        # ``PADIEM_PC_FILE_ERROR:too_large`` or ``:read_failed`` as an
        # exited/1 body, and the Engine maps that same marker. The
        # conversation still reports a failure, never the file as a success.
        verified_text = _verified_read_result_text(dispatch, wire)
        if verified_text is None:
            outcome = "failed"
            summary = "untrusted-result"
            status = "failed"
            content = (
                "PC 파일 읽기 결과를 검증하지 못했습니다. "
                f"명령: {dispatch['command_id']}, 사유: 결과 무결성 불일치."
            )
        else:
            outcome = "failed"
            # Keep the read lane's existing failure vocabulary: only a wait
            # timeout is named as such; every other non-clean read is
            # "failed". The verified marker body is stored separately.
            summary = "timed_out" if wire["termination"] == "timed_out" else "failed"
            status = summary
            read_stored_output = verified_text if verified_text else None
            content = (
                "PC 파일 읽기 작업이 실패했습니다. "
                f"명령: {dispatch['command_id']}, 상태: {wire['termination']}, "
                f"종료 코드: {wire['exit_code']}."
            )
    else:
        summary = "timed_out" if wire["termination"] == "timed_out" else "failed"
        status = summary
        outcome = "failed"
        content = (
            "로컬 러너 작업이 실패했습니다. "
            f"명령: {dispatch['command_id']}, 상태: {wire['termination']}, "
            f"종료 코드: {wire['exit_code']}."
        )
    return None, {
        "outcome": outcome,
        "content": content,
        "summary": summary,
        "status": status,
        "command_output": command_output,
        "read_output": read_output,
        "read_stored_output": read_stored_output,
        "desktop_note": desktop_note,
        "desktop_blob": desktop_blob,
        "desktop_op": desktop_op,
        "desktop_arg": desktop_arg,
        "result_digest": result_digest,
        "result_size": result_size,
    }


async def _oracle_mesh_read_result_store(
    *, base_message_id, command_output, content, conversation_id,
    desktop_arg,
    desktop_blob,
    desktop_note,
    desktop_op,
    dispatch,
    history_store,
    is_session_dispatch,
    read_output,
    result_digest,
    result_size,
    summary,
    wire,
) -> tuple[JSONResponse | None, dict[str, object]]:
    """메시지 조립·원본 저장 구간 (본문 글자 그대로)."""
    if command_output is not None:
        # #5015: the Engine model lane re-feeds exact bytes, including small
        # drive inventories that never needed the over-budget original store.
        # Errors are never promoted by storing: this only preserves bytes, the
        # outcome below stays as verified. Withheld bodies (empty) are owned
        # by the non-delivery notice and store nothing, so no result is lost.
        # no_reply: the console's bounded message (for example a client-side
        # refusal) is the only account of why no exit code exists; keep it as
        # the original so the MCP output read can show it instead of a generic
        # "output not verified".
        if command_output and (is_session_dispatch(dispatch) or (
                len(command_output) <= 65536 and wire["termination"] in ("exited", "no_exit_code", "no_reply"))):
            try:
                store_small = getattr(history_store, "store_oracle_mesh_command_result", None)
                if not callable(store_small):
                    store_small = history_store.store_oracle_mesh_original
                await store_small(
                    user_id=dispatch["user_id"], dispatch_id=wire["dispatch_id"],
                    conversation_id=conversation_id, message_id=base_message_id,
                    raw=command_output, expected_sha256=result_digest,
                    expected_bytes=result_size,
                )
            except HistoryForbidden:
                try:
                    await history_store.finish_oracle_mesh_dispatch(
                        dispatch_id=wire["dispatch_id"], outcome="failed",
                    )
                except Exception:
                    pass
                return _error(403, "oracle_mesh_conversation_forbidden"), {}
            except Exception:
                try:
                    await history_store.mark_oracle_mesh_store_failed(
                        dispatch_id=wire["dispatch_id"],
                    )
                except Exception:
                    pass
                return _error(503, "oracle_mesh_original_unavailable"), {}
        if wire["termination"] == "output_too_large" and not command_output:
            # The executor withheld the body at the wire envelope, so there
            # is no original to store and nothing to split: the observed
            # exit code is delivered with an explicit non-delivery notice.
            messages = [_command_output_withheld_content(dispatch, wire)]
        else:
            head = _command_head(dispatch, wire)
            output_parts = _command_output_parts(
                command_output, _command_part_budget(head),
            )
            if len(output_parts) > _MAX_COMMAND_MESSAGE_PARTS:
                # Over the per-run message-row guard: the verified original is
                # kept in the private store first. The conversation carries a
                # head preview plus the owner-scoped retrieval reference;
                # "stored" is claimed only after the put succeeds, never before.
                try:
                    await history_store.store_oracle_mesh_original(
                        user_id=dispatch["user_id"],
                        dispatch_id=wire["dispatch_id"],
                        conversation_id=conversation_id,
                        message_id=base_message_id,
                        raw=command_output,
                        expected_sha256=result_digest,
                        expected_bytes=result_size,
                    )
                except HistoryForbidden:
                    # Ownership refusal is final: retrying cannot change it.
                    try:
                        await history_store.finish_oracle_mesh_dispatch(
                            dispatch_id=wire["dispatch_id"], outcome="failed",
                        )
                    except Exception:
                        pass
                    return _error(403, "oracle_mesh_conversation_forbidden"), {}
                except Exception:
                    # Storage failed: park the row so the executor resends
                    # the SAME bytes. No completion is reported, and the PC
                    # command is never re-run for a store failure.
                    try:
                        await history_store.mark_oracle_mesh_store_failed(
                            dispatch_id=wire["dispatch_id"],
                        )
                    except Exception:
                        pass
                    return _error(503, "oracle_mesh_original_unavailable"), {}
                messages = [_command_original_stored_content(
                    dispatch, wire, command_output,
                )]
            else:
                messages = _command_part_messages(head, output_parts)
    elif read_output is not None:
        head = ["PC 파일 읽기 결과"]
        output_parts = _command_output_parts(
            read_output, _command_part_budget(head),
        )
        if len(output_parts) > _MAX_COMMAND_MESSAGE_PARTS:
            # The read lane carries the same guard as the command lane. The
            # verified file body is stored whole first, so a large document
            # becomes a preview plus a retrieval reference instead of either
            # hundreds of messages or a silent refusal.
            try:
                await history_store.store_oracle_mesh_original(
                    user_id=dispatch["user_id"],
                    dispatch_id=wire["dispatch_id"],
                    conversation_id=conversation_id,
                    message_id=base_message_id,
                    raw=read_output,
                    expected_sha256=result_digest,
                    expected_bytes=result_size,
                )
            except HistoryForbidden:
                try:
                    await history_store.finish_oracle_mesh_dispatch(
                        dispatch_id=wire["dispatch_id"], outcome="failed",
                    )
                except Exception:
                    pass
                return _error(403, "oracle_mesh_conversation_forbidden"), {}
            except Exception:
                try:
                    await history_store.mark_oracle_mesh_store_failed(
                        dispatch_id=wire["dispatch_id"],
                    )
                except Exception:
                    pass
                return _error(503, "oracle_mesh_original_unavailable"), {}
            messages = [_file_read_stored_content(dispatch, wire, read_output)]
        else:
            messages = _file_read_part_messages(output_parts)
    elif desktop_note is not None and desktop_op is not None:
        # #4139 desktop lane. A capture stores its screenshot bytes first:
        # "stored" is claimed only after the put succeeds, never before. An
        # input or failed turn carries its note directly; notes are short by
        # construction (executor observations, never file bodies).
        if desktop_blob is not None:
            if not callable(getattr(
                history_store, "store_oracle_mesh_original_bytes", None
            )):
                return _error(503, "oracle_mesh_unconfigured"), {}
            try:
                await history_store.store_oracle_mesh_original_bytes(
                    user_id=dispatch["user_id"],
                    dispatch_id=wire["dispatch_id"],
                    conversation_id=conversation_id,
                    message_id=base_message_id,
                    raw=desktop_blob,
                    media_type=_DESKTOP_SCREENSHOT_MEDIA_TYPE,
                    expected_sha256=result_digest,
                    expected_bytes=result_size,
                )
            except HistoryForbidden:
                try:
                    await history_store.finish_oracle_mesh_dispatch(
                        dispatch_id=wire["dispatch_id"], outcome="failed",
                    )
                except Exception:
                    pass
                return _error(403, "oracle_mesh_conversation_forbidden"), {}
            except Exception:
                try:
                    await history_store.mark_oracle_mesh_store_failed(
                        dispatch_id=wire["dispatch_id"],
                    )
                except Exception:
                    pass
                return _error(503, "oracle_mesh_original_unavailable"), {}
            messages = [_desktop_capture_content(
                dispatch, wire, desktop_op, desktop_arg,
                desktop_note, result_digest,
            )]
        elif summary in ("acted",):
            messages = [_desktop_act_content(
                dispatch, wire, desktop_op, desktop_arg, desktop_note,
            )]
        else:
            messages = [_desktop_failed_content(
                dispatch, wire, desktop_op, desktop_arg, desktop_note,
            )]
    else:
        messages = [content]
    return None, {"messages": messages}


async def oracle_mesh_read_original(request: Request) -> Response:
    """Owner-scoped read of one stored over-budget command original.

    Only the dispatch id comes from the browser. The dispatch row (owner,
    run, correlation), the originating conversation and the deterministic
    result id are all re-derived server-side, so no browser-chosen object
    key or foreign-account result is addressable. Unknown ids, foreign
    accounts and missing objects all answer 404 without disclosing which
    part failed; a stored object that disagrees with the dispatch pin is a
    503, never served bytes.
    """
    uid = current_user_id(request)
    if not isinstance(uid, str) or not uid:
        return _error(401, "canonical_session_required")
    params = getattr(request, "path_params", None) or {}
    dispatch_id = _ref(params.get("dispatch_id"), 128)
    if dispatch_id is None:
        return _error(404, "oracle_mesh_original_unavailable")
    history_store = getattr(request.app.state, "history_store", None)
    for method in ("get_oracle_mesh_dispatch_for_owner", "get_claw_run",
                   "read_oracle_mesh_original"):
        if not callable(getattr(history_store, method, None)):
            return _error(503, "oracle_mesh_unconfigured")
    try:
        dispatch = await history_store.get_oracle_mesh_dispatch_for_owner(
            user_id=uid, dispatch_id=dispatch_id,
        )
    except Exception:
        return _error(503, "oracle_mesh_unconfigured")
    if not isinstance(dispatch, dict):
        return _error(404, "oracle_mesh_original_unavailable")
    try:
        run_row = await history_store.get_claw_run(uid, dispatch.get("run_id"))
    except Exception:
        run_row = None
    conversation_id = (
        validate_conversation_id((run_row or {}).get("conversation_id"))
        if isinstance(run_row, dict) else None
    )
    if not conversation_id:
        return _error(404, "oracle_mesh_original_unavailable")
    try:
        message_id = result_message_id(
            conversation_id=conversation_id,
            command_id=dispatch.get("command_id"),
            revision_ref=dispatch.get("revision_ref"),
        )
    except Exception:
        return _error(404, "oracle_mesh_original_unavailable")
    try:
        stored = await history_store.read_oracle_mesh_original(
            user_id=uid, dispatch_id=dispatch_id,
            conversation_id=conversation_id, message_id=message_id,
        )
    except HistoryError:
        return _error(503, "oracle_mesh_original_unavailable")
    except Exception:
        return _error(503, "oracle_mesh_unconfigured")
    if stored is None:
        return _error(404, "oracle_mesh_original_unavailable")
    payload, pinned_sha = stored
    if dispatch.get("kind") == "desktop":
        # A desktop capture serves its screenshot bytes. The pin already
        # binds these exact bytes; the magic is rechecked so a non-image can
        # never leave through the image path.
        if not payload.startswith(_DESKTOP_SCREENSHOT_MAGIC):
            return _error(503, "oracle_mesh_original_unavailable")
        return Response(
            payload, media_type="image/jpeg",
            headers={**_NO_STORE, "X-Oracle-Mesh-Content-SHA256": pinned_sha},
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return _error(503, "oracle_mesh_original_unavailable")
    return Response(
        text, media_type="text/plain; charset=utf-8",
        headers={**_NO_STORE, "X-Oracle-Mesh-Content-SHA256": pinned_sha},
    )


async def _verify_engine_proof(
    request: Request, *, max_body_bytes: int | None = 8192,
) -> tuple[bytes | None, JSONResponse | None]:
    """Shared Engine proof check for the signed Mesh lanes (Claw and Chat).

    The deployment-owned Engine proof secret authenticates the Engine caller;
    browser cookies never act as proof. Returns the raw body or a ready-made
    error response. Both product lanes use this exact check.
    """
    import hmac
    import hashlib
    import time

    secret = valid_claw_engine_desktop_secret(
        getattr(request.app.state, "claw_engine_desktop_secret", None)
    )
    if secret is None:
        return None, _error(503, "claw_engine_desktop_unconfigured")
    raw = await request.body()
    if max_body_bytes is not None and len(raw) > max_body_bytes:
        return None, _error(413, "claw_engine_desktop_invalid_body")
    timestamp = request.headers.get("X-Claw-Engine-Time", "")
    signature = request.headers.get("X-Claw-Engine-Proof", "")
    try:
        seconds = int(timestamp)
    except (ValueError, TypeError):
        return None, _error(401, "claw_engine_proof_required")
    if abs(int(time.time()) - seconds) > 60 or not isinstance(signature, str) or len(signature) != 64:
        return None, _error(401, "claw_engine_proof_required")
    expected = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None, _error(401, "claw_engine_proof_required")
    return raw, None


# ---------------------------------------------------------------------------
# #5015/#4976 — structured PC file tools (list/read) on the existing Mesh
# lane.
#
# The Engine's model-selected list_files/read_file tools send a structured op
# and a path relative to the approved folder; they never send a shell command.
# This server derives the approved root from the deployment ownership row's
# mapped file, rejects traversal/absolute paths, and then:
#
# * list stays on the existing kind="command" PowerShell lane, and
# * read reuses the existing kind="read" MeshCentral download lane
#   (``meshctrl.js download``), whose result bytes are already verified,
#   pinned, stored and retrievable through the command result modes.
#
# The read dispatch carries the server-computed per-call bound so the executor
# cannot be told to accept more than the PC file contract allows.
# ---------------------------------------------------------------------------

from .oracle_mesh_pc_paths import (
    PC_FILES_MAX_PATH_CHARS,
    PC_FILES_LIST_PAGE_SIZE,
    PC_FILES_READ_MAX_BYTES,
    PC_FILES_ERROR_PREFIX,
    _PC_FILES_READ_TOOL_MARKER,
    _PC_FILES_READ_ROOT_REF,
    _PC_FILES_SAFE_REF,
    _pc_files_text,
    _pc_files_approved_root,
    _pc_files_relative_path,
    _pc_files_roots_of_map_row,
    _DRIVE_REFERENCE,
    _ROOT_WORDS,
    _drive_reference,
    _pc_files_pick_root,
    _pc_files_powershell_literal,
    _PC_FILES_OPS,
    _PC_FILES_READ_OPS,
    _pc_files_read_only,
    _PC_WRITE_OPS,
    _pc_files_claim_op,
    _pc_files_search_roots,
)




#: The op ceilings the signed Engine scope claim may name, per admitted or
#: requested scope name. The names mirror the Engine's own table one-to-one
#: (``PC_REQUEST_SCOPE_TOOLS`` in kagent's pc_query_adapter) — #8098: the
#: three #8048 single-step scopes were missing here, so a recursive name
#: search (``admitted=files_search``) was refused 422 before the PC saw it.
#: The op values derive exactly like the Engine derives them: an op pairs
#: with its tool id, so a scope of only the chunk reader carries no named op
#: (``files_chunk`` → ``[]``). The browser scope is absent on purpose — a
#: browser claim verifies in claw_pc_browser_routes, never on this lane.
_ENGINE_PC_FILES_SCOPE_OPS = {
    # A name search is a listing that filters; a content search reads the same
    # files a `files` grant may already read, one match line at a time.
    "files_list": ["list", "search_name"],
    "files": ["list", "read", "search_name", "search_content"],
    "files_write": ["write", "edit", "move", "delete", "mkdir"],
    "query_drives": ["drives"], "none": [],
    "files_search": ["search_name"],
    "files_search_contents": ["search_content"],
    "files_chunk": [],
}


def _engine_pc_scope_claim(request: Request, raw: bytes, *, product: str):
    """Authenticate the optional ceiling without widening the legacy body."""
    import hmac
    encoded = request.headers.get("X-Claw-PC-Scope")
    proof = request.headers.get("X-Claw-PC-Scope-Proof")
    if encoded is None and proof is None:
        return None, None  # Old Engine compatibility; existing auth still runs.
    if not isinstance(encoded, str) or len(encoded) > 1024 or not isinstance(proof, str):
        return None, _error(401, "pc_scope_proof_invalid")
    secret = getattr(request.app.state, "claw_engine_desktop_secret", "")
    timestamp = request.headers.get("X-Claw-Engine-Time", "")
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + raw + b"." + encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(proof, expected):
        return None, _error(401, "pc_scope_proof_invalid")
    try:
        claim = json.loads(encoded)
    except (ValueError, TypeError):
        return None, _error(422, "pc_scope_claim_invalid")
    scopes = _ENGINE_PC_FILES_SCOPE_OPS
    if (
        not isinstance(claim, dict)
        or set(claim) != {"version", "requested", "admitted", "source", "ops", "app_id"}
        or type(claim["version"]) is not int or claim["version"] != 1
        or not isinstance(claim["requested"], str) or claim["requested"] not in scopes
        or not isinstance(claim["admitted"], str) or claim["admitted"] not in scopes
        # The ops list is a ceiling, not an inventory: a claim produced by an
        # Engine that predates a capability still names a real subset of the
        # admitted scope, and the dispatch below refuses any op it did not
        # name. Requiring the full list would fail every file call during a
        # rolling deploy whose Chat side shipped one capability earlier.
        or not set(claim["ops"]).issubset(scopes[claim["admitted"]])
        or not set(claim["ops"]).issubset(scopes[claim["requested"]])
        or len(set(claim["ops"])) != len(claim["ops"])
        or claim["source"] not in ("declared", "decision", "missing")
        or claim["source"] not in ("declared", "decision", "missing")
        or claim["app_id"] != ("padiem-chat" if product == "chat" else "b54-padiem-claw")
    ):
        return None, _error(422, "pc_scope_claim_invalid")
    return claim, None


#: Hidden per-drive backup folder. The original is copied here before anything
#: changes, so a rollback never depends on somebody remembering a path.
PC_BACKUP_FOLDER = ".padiem-backup"
#: The PC answers one write step with this line: the JSON account, base64 encoded
#: so no console code page or quoting rule can change what it says.
PC_WRITE_ACCOUNT_PREFIX = "PADIEM_PC_ACCOUNT="


def _pc_backup_dir(root: str, day: str) -> str:
    """The hidden backup folder on the drive one granted root sits on."""
    drive = (str(root).strip().rstrip(":\\/") or "C")[:1].upper()
    return drive + ":\\" + PC_BACKUP_FOLDER + "\\" + day


def _pc_ps_literal(value: str) -> str:
    """One single-quoted PowerShell literal (#7559: all five quote characters)."""
    return _pc_files_powershell_literal(value)


def _pc_write_backup_fragments(*, relative: str) -> tuple[str, str]:
    """백업·대상 없음 조각: 모든 변경이 같은 백업 단계로 시작한다."""
    backup_step = (
        "New-Item -ItemType Directory -Force -Path $backupDir | Out-Null; "
        "$backup = Join-Path $backupDir ($stamp + '-' + ("
        + _pc_ps_literal(relative) + " -replace '[^\\w.-]','_'));"
        " try { Copy-Item -LiteralPath $source_to_keep -Destination $backup -Force }"
        " catch { $backup = $null; $reason = 'backup_failed'; throw 'padiem backup failed' }"
    )
    target_missing = (
        "if (-not (Test-Path -LiteralPath $source_to_keep -PathType Leaf)) {"
        " $reason = 'path_invalid'; throw 'padiem target missing' }"
    )
    return backup_step, target_missing


def _pc_write_input_statements(
    *, op: str, target: str, backup_dir: str, content_b64: str | None = None,
    old_text_b64: str | None = None, new_text_b64: str | None = None,
    destination: str | None = None,
) -> list[str]:
    """입력 검증 단계: 초기 문장과 관찰 대상을 같은 순서로 만든다."""
    statements = [
        "$ErrorActionPreference = 'Stop'",
        "$ok = $false",
        "$reason = 'failed'",
        "$bytes = 0",
        "$op = " + _pc_ps_literal(op),
        "$target = " + _pc_ps_literal(target),
        "$backupDir = " + _pc_ps_literal(backup_dir),
        "$backup = $null",
        "$stamp = (Get-Date -Format 'yyyyMMddHHmmss') + '-' + "
        "([Guid]::NewGuid().ToString('N')).Substring(0,8)",
    ]
    if content_b64 is not None:
        statements.append(
            "$payload = [Convert]::FromBase64String(" + ps_literal(content_b64) + ")"
        )
    if old_text_b64 is not None:
        statements.append(
            "$oldText = [Convert]::FromBase64String(" + ps_literal(old_text_b64) + ")"
        )
    if new_text_b64 is not None:
        statements.append(
            "$newText = [Convert]::FromBase64String(" + ps_literal(new_text_b64) + ")"
        )
    if destination is not None:
        statements.append("$destination = " + _pc_ps_literal(destination))
    # Keep both observation targets before a move rewrites $target for the
    # legacy account. These paths come from the server's resolved grant, not
    # from model-provided verification fields.
    statements.extend([
        "$verifySource = $target",
        "$verifyTarget = " + ("$destination" if op == "move" else "$target"),
    ])
    return statements


def _pc_write_scope_guard(statements: list[str], *, root: str) -> str:
    """권한·한도 단계: 허용 범위 밖 바로가기 경로를 백업 전에 막는다."""
    # #5994 D3: the guard walks every folder from the granted root down to the
    # target (and, for a move, down to the destination) and refuses the step
    # before any backup or change when one of them is a reparse point — a
    # shortcut folder must never carry a write, a move or a deletion outside
    # the grant. The final normalized path is checked against the root as a
    # second layer. The granted root itself is not checked: a root that is a
    # link was the owner's own grant decision. A guard malfunction fails
    # closed, and the refusal names no internal component.
    link_refusal = "이 위치는 바로가기 폴더를 거쳐서 바꿀 수 없습니다."
    statements.append(
        "$guardRoot = " + _pc_ps_literal(root.rstrip("\\/") + "\\") + ";"
        "$guardHit = $null;"
        "try {"
        " foreach ($rel in (@($target) + $(if ($destination) { @($destination) } else { @() }))) {"
        "  if (-not $rel) { continue };"
        "  $walk = $guardRoot;"
        "  $rest = $rel.Substring($guardRoot.Length).TrimStart('/').Replace('/', '\\');"
        "  foreach ($seg in ($rest -split '\\\\')) {"
        "   $walk = Join-Path $walk $seg;"
        "   if (-not (Test-Path -LiteralPath $walk)) { break };"
        "   $item = Get-Item -LiteralPath $walk -Force -ErrorAction SilentlyContinue;"
        "   if ($item -and (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0))"
        "   { $guardHit = $walk; break } };"
        " if ($guardHit) { break } }"
        "} catch { $guardHit = $guardRoot };"
        "if (-not $guardHit) {"
        " $full = [IO.Path]::GetFullPath($target);"
        " if (-not $full.StartsWith($guardRoot, [System.StringComparison]::OrdinalIgnoreCase))"
        " { $guardHit = $guardRoot } };"
        "if ($destination -and -not $guardHit) {"
        " $fullDestination = [IO.Path]::GetFullPath($destination);"
        " if (-not $fullDestination.StartsWith($guardRoot, [System.StringComparison]::OrdinalIgnoreCase))"
        " { $guardHit = $guardRoot } };"
    )
    return link_refusal


def _pc_write_operation_body(
    *, op: str, append: bool, replace_all: bool, backup_step: str,
    target_missing: str,
) -> str:
    """분기 단계: 덮어쓰기·추가·편집·폴더·이동·삭제 중 하나를 고른다."""
    if op == "write" and append:
        # #7603: append keeps every existing byte and adds the caller's bytes at
        # the end. A file that is not valid UTF-8 is refused exactly like pc_edit
        # because an append is still a text-file edit; a missing file is created
        # through the same atomic temp+Move-Item step as an overwrite, and its
        # parent must already exist.
        body = (
            "try {"
            " if (Test-Path -LiteralPath $target -PathType Leaf) {"
            " $source_to_keep = $target; $appendLength = $payload.Length;"
            + backup_step +
            "; $before = [IO.File]::ReadAllBytes($target);"
            " $strict = New-Object Text.UTF8Encoding($false, $true);"
            " try { $beforeText = $strict.GetString($before) }"
            " catch { $reason = 'edit_encoding_unsupported'; throw 'padiem append encoding' };"
            " if (-not [Linq.Enumerable]::SequenceEqual($strict.GetBytes($beforeText), $before))"
            " { $reason = 'edit_encoding_unsupported'; throw 'padiem append encoding' };"
            " $payload = [byte[]]($before + $payload)"
            " } elseif (-not (Test-Path -LiteralPath "
            "([IO.Path]::GetDirectoryName($target)))) {"
            " $reason = 'path_invalid'; throw 'padiem parent missing' } else { $appendLength = $payload.Length };"
            " $temp = $target + '.padiem-write';"
            " [IO.File]::WriteAllBytes($temp, $payload);"
            " Move-Item -LiteralPath $temp -Destination $target -Force;"
            " $bytes = $payload.Length;"
            " $ok = $true; $reason = $null }"
            " catch { if ($reason -eq 'failed') { $reason = 'path_invalid' } }"
        )
    elif op == "write":
        body = (
            "try {"
            " if (Test-Path -LiteralPath $target -PathType Leaf) {"
            " $source_to_keep = $target; " + backup_step +
            " } elseif (-not (Test-Path -LiteralPath "
            "([IO.Path]::GetDirectoryName($target)))) {"
            " $reason = 'path_invalid'; throw 'padiem parent missing' };"
            " $temp = $target + '.padiem-write';"
            " [IO.File]::WriteAllBytes($temp, $payload);"
            " Move-Item -LiteralPath $temp -Destination $target -Force;"
            " $bytes = $payload.Length;"
            " $ok = $true; $reason = $null }"
            " catch { if ($reason -eq 'failed') { $reason = 'path_invalid' } }"
        )
    elif op == "edit":
        # #7065: find-and-replace inside one existing file. The caller's two
        # byte sequences are compared as byte sequences; the utf8 branch on
        # IndexOf/Replace only lets the two sides be compared. Nothing is
        # written unless the search text occurs exactly once, or once or more
        # when replace_all was asked for; a miss and an ambiguous match each
        # refuse with their own reason and change nothing. The original is
        # backed up first, by the same step every other change uses.
        #
        # Round trip guard: the file is edited as UTF-8 and written back as
        # UTF-8, so a file that is NOT valid UTF-8 (a cp949/ANSI file on a
        # Korean Windows, where one Hangul letter is two bytes that decode to
        # garbage) would have every Korean letter outside the edit rewritten
        # as replacement characters. Before anything is backed up or changed,
        # the read bytes are decoded and encoded again; if that differs the
        # step refuses with edit_encoding_unsupported and leaves the file
        # untouched. A UTF-8 BOM survives because it is part of the decoded
        # text and is encoded back at the head of the file.
        body = (
            "try { $source_to_keep = $target;"
            + target_missing
            + "; $before = [IO.File]::ReadAllBytes($target);"
            " $strict = New-Object Text.UTF8Encoding($false, $true);"
            " try { $beforeText = $strict.GetString($before) }"
            " catch { $reason = 'edit_encoding_unsupported'; throw 'padiem edit encoding' };"
            " if (-not [Linq.Enumerable]::SequenceEqual($strict.GetBytes($beforeText), $before))"
            " { $reason = 'edit_encoding_unsupported'; throw 'padiem edit encoding' };"
            " $beforeText = [Text.Encoding]::UTF8.GetString($before);"
            " $oldPlain = [Text.Encoding]::UTF8.GetString($oldText);"
            " $newPlain = [Text.Encoding]::UTF8.GetString($newText);"
            " $hits = 0; $at = $beforeText.IndexOf($oldPlain, 0, [StringComparison]::Ordinal);"
            " while ($at -ge 0) { $hits += 1; $at = $beforeText.IndexOf($oldPlain, $at + $oldPlain.Length, [StringComparison]::Ordinal) };"
            " if ($hits -eq 0) { $reason = 'edit_not_found'; throw 'padiem edit miss' };"
            " if ($hits -gt 1 -and -not "
            + ("$true" if replace_all else "$false") + ") { $reason = 'edit_not_unique'; throw 'padiem edit ambiguous' };"
            " " + backup_step +
            "; $afterText = "
            + ("$beforeText.Replace($oldPlain, $newPlain)" if replace_all else
               "$beforeText.Substring(0, $beforeText.IndexOf($oldPlain, 0, [StringComparison]::Ordinal)) + $newPlain + "
               "$beforeText.Substring($beforeText.IndexOf($oldPlain, 0, [StringComparison]::Ordinal) + $oldPlain.Length)")
            + "; $payload = [Text.Encoding]::UTF8.GetBytes($afterText);"
            " $temp = $target + '.padiem-write';"
            " [IO.File]::WriteAllBytes($temp, $payload);"
            " Move-Item -LiteralPath $temp -Destination $target -Force;"
            " $bytes = $payload.Length;"
            " $ok = $true; $reason = $null }"
            " catch { if ($reason -eq 'failed') { $reason = 'path_invalid' } }"
        )
    elif op == "mkdir":
        # #7603: one folder, including missing parents. An existing folder is a
        # no-change success; a file of the same name is the one refusal. There is
        # no original to copy, so the backup leg answers none, exactly like a
        # write to a new file.
        body = (
            "try {"
            " if (Test-Path -LiteralPath $target -PathType Leaf)"
            " { $reason = 'target_exists'; throw 'padiem target exists' };"
            " if (-not (Test-Path -LiteralPath $target -PathType Container))"
            " { New-Item -ItemType Directory -Force -Path $target | Out-Null };"
            " $ok = $true; $reason = $null }"
            " catch { if ($reason -eq 'failed') { $reason = 'path_invalid' } }"
        )
    elif op == "move":
        body = (
            "try { $source_to_keep = $target;"
            + target_missing
            + "; if (Test-Path -LiteralPath $destination) { $source_to_keep = $destination; "
            + backup_step +
            " }; Move-Item -LiteralPath $target -Destination $destination -Force;"
            " $target = $destination;"
            " $ok = $true; $reason = $null }"
            " catch { if ($reason -eq 'failed') { $reason = 'path_invalid' } }"
        )
    else:
        body = (
            "try { $source_to_keep = $target;"
            + target_missing
            + "; " + backup_step +
            "; Remove-Item -LiteralPath $target -Force;"
            " $ok = $true; $reason = $null }"
            " catch { if ($reason -eq 'failed') { $reason = 'path_invalid' } }"
        )
    return body


def _pc_write_record_statements(
    statements: list[str], *, body: str, link_refusal: str, append: bool,
) -> None:
    """기록·응답 단계: 거절 문장, 검증, 계정 줄을 같은 순서로 붙인다."""
    # A refused step changes nothing and still answers with one account line:
    # the refusal names the Korean sentence the owner sees, never an internal
    # component.
    statements.append(
        "if ($guardHit) { $reason = " + _pc_ps_literal(link_refusal) + " }"
        " else { " + body + " }"
    )
    # #7603: an append is measured where it lands. The whole-file digest above
    # answers "which file is this" and cannot equal the caller's bytes once the
    # file was not empty, so the tail of the appended length is read back and
    # hashed. Only the append command carries this probe.
    append_probe = "" if not append else (
        " $tailBytes = $null; $tailSha256 = $null;"
        " if ($targetIsFile -and $null -ne $appendLength) {"
        " $stream = [IO.File]::Open($verifyTarget, 'Open', 'Read', 'ReadWrite');"
        " try { $streamLength = $stream.Length; $tailLength = [int64]$appendLength;"
        " if ($tailLength -gt $streamLength) { $tailLength = $streamLength };"
        " $tailBuffer = New-Object byte[] $tailLength;"
        " [void]$stream.Seek(($streamLength - $tailLength), 'Begin');"
        " if ($stream.Read($tailBuffer, 0, $tailLength) -eq $tailLength) {"
        " $tailBytes = $tailLength;"
        " $tailHash = [Security.Cryptography.SHA256]::Create();"
        " try { $tailSha256 = ([BitConverter]::ToString($tailHash.ComputeHash($tailBuffer))"
        " -replace '-', '').ToLowerInvariant() } finally { $tailHash.Dispose() } } }"
        " finally { $stream.Dispose() } }"
    )
    # A command's $ok and its expected payload length are not filesystem
    # evidence. Inspect the result after the mutation's catch, even when the
    # mutation reported failure. Inspection failures have their own state and
    # never leak an exception or turn an unobserved result into success.
    statements.extend([
        "$verification = [ordered]@{version=1; status='unavailable'}",
        "try {"
        " $sourceExists = Test-Path -LiteralPath $verifySource -ErrorAction Stop;"
        " $targetExists = Test-Path -LiteralPath $verifyTarget -ErrorAction Stop;"
        " $targetIsFile = Test-Path -LiteralPath $verifyTarget -PathType Leaf -ErrorAction Stop;"
        " $targetBytes = $null; $targetSha256 = $null;"
        " if ($targetIsFile) {"
        " $targetItem = Get-Item -LiteralPath $verifyTarget -Force -ErrorAction Stop;"
        " $targetBytes = [int64]$targetItem.Length;"
        " if ($op -eq 'write') {"
        " $fileHash = Get-FileHash -LiteralPath $verifyTarget -Algorithm SHA256 -ErrorAction Stop;"
        " $targetSha256 = $fileHash.Hash.ToLowerInvariant() } };"
        + append_probe
        + " $backupExists = $null; $backupIsFile = $null;"
        " if ($null -ne $backup) {"
        " $backupExists = Test-Path -LiteralPath $backup -ErrorAction Stop;"
        " $backupIsFile = Test-Path -LiteralPath $backup -PathType Leaf -ErrorAction Stop };"
        " $verification = [ordered]@{version=1; status='observed';"
        " source_exists=[bool]$sourceExists; target_exists=[bool]$targetExists;"
        " target_is_file=[bool]$targetIsFile; target_bytes=$targetBytes;"
        " target_sha256=$targetSha256; backup_exists=$backupExists;"
        " backup_is_file=$backupIsFile}"
        + ("" if not append else
           "; if ($null -ne $tailBytes) { $verification['append_bytes'] = $tailBytes;"
           " $verification['append_sha256'] = $tailSha256 }")
        + " } catch { $verification = [ordered]@{version=1; status='unavailable'} }",
    ])
    statements.extend([
        "$account = [ordered]@{ok=$ok; op=$op; reason=$reason; target=$target; "
        "backup=$backup; bytes=$bytes; verification=$verification}",
        "$json = ConvertTo-Json -InputObject $account -Compress",
        "$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))",
        "Write-Output ('" + PC_WRITE_ACCOUNT_PREFIX + "' + $encoded)",
    ])


def _pc_write_command(
    *, op: str, root: str, target: str, backup_dir: str, relative: str,
    destination: str | None = None, content_b64: str | None = None,
    old_text_b64: str | None = None, new_text_b64: str | None = None,
    append: bool = False, replace_all: bool = False,
) -> str:
    """Build one write, move or delete step for the paired PC.

    Four rules hold across all three operations. The original is copied to the
    hidden backup folder on the same drive *before* anything changes, and a
    backup that fails stops the step there, so no change is made that cannot be
    undone. The step prints exactly one account line saying what happened and
    where the original landed - including when it refused. There is no
    confirmation anywhere in it: the change happens when the account says it
    did. And the step refuses a path that crosses a reparse point (#5994 D3):
    every folder from the granted root down to the target - and the target
    itself - is checked for the ReparsePoint attribute (junctions, symbolic
    links, mounts), the final normalized path must still sit inside the granted
    root, and a refusal happens before the backup, so nothing changes.

    The command is cmdlet and .NET calls only, like the listing command: no
    native program runs, so the PC reports no exit code and the existing result
    lane stays truthful.

    It is also exactly ONE line, which is not a style choice. The agent runs a
    console command as ``powershell -noprofile -nologo -command -`` and feeds the
    script through that process's standard input: a script carrying a newline
    never completes there, so its PowerShell stays alive, and because that agent
    serves one console task at a time every later PC operation - reads included -
    waits behind it. Measured on the real machines on 2026-10-28: one line
    answered in under two seconds and wrote the file with its backup; the same
    statements on two lines never answered at all. Semicolons are what PowerShell
    needs on one line, so nothing here changed meaning.

    For the same reason the parent folder is taken with
    ``[IO.Path]::GetDirectoryName`` and not with ``Split-Path -LiteralPath ...
    -Parent``: on the PC's own Windows PowerShell 5.1 that combination is refused
    with ``AmbiguousParameterSet``, which would turn every new file into a
    refusal. Both rules are about what the customer's PC actually accepts, so
    they are checked here where the script is built.
    """
    backup_step, target_missing = _pc_write_backup_fragments(relative=relative)
    statements = _pc_write_input_statements(
        op=op,
        target=target,
        backup_dir=backup_dir,
        content_b64=content_b64,
        old_text_b64=old_text_b64,
        new_text_b64=new_text_b64,
        destination=destination,
    )
    link_refusal = _pc_write_scope_guard(statements, root=root)
    body = _pc_write_operation_body(
        op=op,
        append=append,
        replace_all=replace_all,
        backup_step=backup_step,
        target_missing=target_missing,
    )
    _pc_write_record_statements(
        statements, body=body, link_refusal=link_refusal, append=append,
    )
    return "; ".join(statements)



#: Characters the provider's own -Filter can carry harmlessly. Anything else (a
#: wildcard, a quote, a path separator, a semicolon) makes the coarse pre-filter '*'
#: and lets the exact -like test decide — so a term can never become a pattern or a
#: second statement, and correctness never depends on which branch ran.
_FILTER_PREFILTER_SAFE = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-.,()")


def _pc_files_filter_prefilter(term: str) -> str:
    if term and all(ch in _FILTER_PREFILTER_SAFE or ord(ch) > 127 for ch in term):
        return "*" + term + "*"
    return "*"


def _pc_files_windows_folder(root: str, relative: str) -> str:
    """The folder to list: a bare drive is the volume root, not ``D:``.

    Windows reads ``-LiteralPath 'D:'`` as the *current directory on D:*, not
    the drive root. Spelling it ``D:/`` makes a granted drive list the drive.
    #7978: a network share reaches PowerShell in its own Windows spelling —
    the stored ``//server/share`` becomes ``\\\\server\\share\\relative``. A
    single leading slash would be a drive-relative path, never the share.
    """
    trimmed = str(root or "").replace("\\", "/").rstrip("/")
    if trimmed.startswith("//"):
        unc = "\\\\" + trimmed[2:].replace("/", "\\")
        if not relative:
            return unc
        return unc + "\\" + str(relative).replace("/", "\\")
    bare_drive = len(trimmed) == 2 and trimmed[1] == ":"
    base = trimmed + "/" if bare_drive else trimmed
    return base.rstrip("/") + "/" + relative if relative else base


def _pc_files_command(*, op: str, root: str, relative: str,
                      offset: int = 0, page_size: int = PC_FILES_LIST_PAGE_SIZE,
                      filter_term: str | None = None,
                      recursive: bool = False, depth: int = 1) -> str:
    """Build the one command this server will execute for a file tool call.

    Only ``list`` uses the PowerShell command lane. ``read`` uses the existing
    kind="read" MeshCentral download lane: the former ``ReadAllText`` command
    timed out through the MeshCentral PowerShell reply, and replacing it with
    another shell command is not the contract.

    A listing is one page of a **fixed order**: folders first, then name. Without a
    fixed order an offset means nothing — two calls could sort the same folder
    differently and skip or repeat rows. The reply carries the folder's own total
    and whether this page was the last, so the caller never has to guess that a
    short page was the end.

    The list command is cmdlet-only on purpose: no native program runs, so the
    PC reports no exit code (``no_exit_code``) and the existing result lane
    stays truthful.

    depth > 1 walks that many levels in one answer: every row carries its
    relative path and level, the walk stops at 200 rows with ``truncated``,
    and offset paging does not apply (the walk is one bounded answer).
    Hidden, system and reparse-point directories are listed but never
    descended into, so a shortcut cannot widen the walk past the granted
    root. recursive keeps the pre-#7447 name search rules instead: it matches
    the caller's name fragment while walking, stops at
    ``PC_SEARCH_SCAN_MAX_FILES`` walked entries or ``PC_SEARCH_MAX_LIMIT``
    matched rows and reports the cut through ``has_more``/``truncated``.
    """
    if op != "list":
        raise ValueError("only list uses the read-only command builder")
    if (not isinstance(offset, int) or isinstance(offset, bool) or offset < 0
            or not isinstance(page_size, int) or isinstance(page_size, bool)
            or not 1 <= page_size <= 2000):
        raise ValueError("a paging offset and a page size are required")
    if type(recursive) is not bool or type(depth) is not int or isinstance(depth, bool):
        raise ValueError("a depth and a recursive flag are validated booleans and integers")
    if not 1 <= depth <= 3 or (recursive and depth > 1):
        raise ValueError("depth is 1..3 and cannot combine with a recursive name search")
    if depth > 1 and (offset != 0 or filter_term is not None):
        raise ValueError("a deep walk is one bounded answer, not a page")
    if recursive and offset != 0:
        raise ValueError("a recursive search is one bounded answer, not a page")
    if recursive and (not isinstance(filter_term, str) or not filter_term):
        # The walk matches this fragment on the PC; without it the caller is
        # asking for an unbounded listing, which stays a depth-1 feature.
        raise ValueError("a recursive name search requires a filter term")
    if filter_term is not None:
        # The term is a name fragment, never a pattern: it travels as a single-quoted
        # literal and is escaped with the wildcard escaper before -like sees it. No
        # length cap is imposed here — the exec boundary already refuses an argument
        # the OS cannot carry — but a control character or an empty term is refused.
        if not isinstance(filter_term, str) or not filter_term:
            raise ValueError("a filter term must be non-empty text")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in filter_term):
            raise ValueError("a filter term may not carry control characters")
    # #7976: a bare drive is the volume root, not a drive-relative directory.
    folder = _pc_files_windows_folder(root, relative)
    # #7973: a path, a relative segment or a name fragment is carried as base64
    # of its UTF-8 bytes, never as characters in the command text. The MeshCentral
    # agent hands that text to a PowerShell console whose input decoder is the
    # PC's legacy code page on a Korean installation; Korean written into the
    # command arrives as mojibake, Get-ChildItem cannot find the folder and the
    # answer is an error instead of JSON (stage pc_list_output_invalid). An
    # ASCII-only command decodes to the exact value on the PC whatever that code
    # page is. The root/relative grant and reparse checks below are unchanged.
    # Measured through the same wrapper the executor sends: one page of 200 rows on
    # 컴1's System32 came back as 20,647 transcript bytes in 1,240 ms, and the
    # matching 500-row page as 53,979 bytes in 1,454 ms. `-First` alone silently cut
    # the folder at 200; `-Skip`/`-First` over a fixed sort is a page of the whole
    # list, and total/has_more make the cut visible.
    # #5994 D3: a listing must not open a shortcut folder either — the same
    # reparse walk the write lane uses refuses a folder that is reached through
    # a junction or a symbolic link below the granted root.
    guard_root = root.rstrip("\\/") + "\\"
    if guard_root.startswith("//"):
        # #7978: a UNC root reaches the guard in its Windows spelling, the same
        # way _pc_files_windows_folder spells the folder itself.
        guard_root = "\\\\" + guard_root[2:].replace("/", "\\")
    guard = (
        "$folder = " + ps_utf8_literal(folder) + ";"
        "$guardRoot = " + ps_utf8_literal(guard_root) + ";"
        "$relText = " + ps_utf8_literal(relative) + ";"
        "$guardHit = $null;"
        "try {"
        " $walk = $guardRoot;"
        " foreach ($seg in ($relText.Replace('/', '\\') -split '\\\\')) {"
        "  if (-not $seg) { continue };"
        "  $walk = Join-Path $walk $seg;"
        "  if (-not (Test-Path -LiteralPath $walk)) { break };"
        "  $item = Get-Item -LiteralPath $walk -Force -ErrorAction SilentlyContinue;"
        "  if ($item -and (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0))"
        "  { $guardHit = $walk; break } };"
        "} catch { $guardHit = $guardRoot };"
        "if ($guardHit) {"
        " @{error=" + ps_utf8_literal("이 위치는 바로가기 폴더를 거쳐서 볼 수 없습니다.")
        + "} | ConvertTo-Json -Compress"
        " } elseif (-not (Test-Path -LiteralPath $folder)) {"
        # A folder that is not there is a closed verdict, not a malformed page.
        # The engine can then answer pc_path_not_found instead of output_invalid.
        " @{error='path_not_found'} | ConvertTo-Json -Compress"
        " } else {"
    )
    if recursive:
        # A recursive name search walks the granted subtree and keeps only the
        # matching rows: at most PC_SEARCH_SCAN_MAX_FILES entries visited and
        # PC_SEARCH_MAX_LIMIT rows returned, with both cuts reported. The
        # descent never enters hidden, system or reparse-point directories, so
        # a shortcut cannot carry the walk past the granted root.
        # A literal substring, never a wildcard pattern: IndexOf keeps every
        # caller character (quote, semicolon, backtick, $()) a character on
        # both Windows PowerShell 5.1 and pwsh 7, where -like treats the
        # backtick differently. -like would also need an escape the caller
        # never asked for.
        match = (
            "$needle=" + ps_utf8_literal(filter_term) + ";"
        )
        walk = (
            "$ErrorActionPreference='SilentlyContinue';"
            "[Console]::OutputEncoding=New-Object Text.UTF8Encoding $false;"
            "$cap=" + str(PC_SEARCH_MAX_LIMIT) + ";"
            "$scan=" + str(PC_SEARCH_SCAN_MAX_FILES) + ";"
            "$skip=2 -bor 4 -bor 1024;"
            "$rows=New-Object System.Collections.ArrayList;"
            "$flags=@{truncated=$false;scan=$false};"
            "$scanned=0;"
            "$stop=$false;"
            "$full=$false;"
            "function Add-Match([object]$item,[string]$rel){"
            "  if($rows.Count -ge $cap){ $flags.truncated=$true; return };"
            "  [void]$rows.Add([ordered]@{Name=$item.Name; Length=$item.Length;"
            "  Modified=$item.LastWriteTimeUtc.ToString('o'); PSIsContainer=$item.PSIsContainer;"
            "  relative_path=$rel})"
            "};"
            "$frontier=@(@{dir=$folder; rel=''});"
            "while($frontier.Count -gt 0 -and -not $stop){"
            "  $next=@();"
            "  foreach($f in $frontier){"
            "    if($stop){ break };"
            "    foreach($i in @(Get-ChildItem -LiteralPath $f.dir -Force"
            " -ErrorAction SilentlyContinue)){"
            "      $scanned++;"
            "      if($scanned -gt $scan){ $flags.scan=$true; $stop=$true; break };"
            "      $rel=if($f.rel){ $f.rel + [char]92 + $i.Name } else { $i.Name };"
            # A name search answers with files: a folder name that matches is
            # not a result the caller can open, and it must not take one of the
            # 50 rows away from a file that does.
            "      if(-not $i.PSIsContainer -and $i.Name.IndexOf($needle,"
            "        [StringComparison]::OrdinalIgnoreCase) -ge 0){"
            # The first match past the cap is the proof that has_more is true;
            # a run of exactly 50 with nothing left is a complete answer.
            "        if($full){ $flags.truncated=$true; $stop=$true; break };"
            "        Add-Match $i $rel;"
            "        if($rows.Count -ge $cap){ $full=$true }"
            "      };"
            "      if($full){ continue };"
            "      if($i.PSIsContainer -and (($i.Attributes -band $skip) -eq 0)){"
            "        $next+=[ordered]@{dir=$i.FullName; rel=$rel}"
            "      }"
            "    }"
            "  };"
            "  $frontier=$next"
            "};"
            "$s=@($rows | Sort-Object -Property @{Expression={$_.relative_path}});"
            "@{offset=0; total=$s.Count; has_more=$flags.truncated;"
            " truncated=$flags.truncated; scan_truncated=$flags.scan;"
            " recursive=$true; items=$s}"
            " | ConvertTo-Json -Compress -Depth 3"
            + " }"
        )
        return guard + match + walk
    if depth > 1:
        # A depth walk answers in one bounded response: per level the children
        # are listed with their relative path and level, the walk descends
        # only into directories that are not hidden, system or reparse-point
        # folders, and the whole answer stops at 200 rows with ``truncated``.
        # Offset paging stays a depth-1 feature.
        walk = (
            "$ErrorActionPreference='SilentlyContinue';"
            "[Console]::OutputEncoding=New-Object Text.UTF8Encoding $false;"
            "$cap=" + str(_PC_LIST_DEPTH_ROW_CAP) + ";"
            "$maxDepth=" + str(depth) + ";"
            "$skip=2 -bor 4 -bor 1024;"
            "$rows=New-Object System.Collections.ArrayList;"
            "$flags=@{truncated=$false};"
            "$baseLen=" + str(len(folder.replace("/", "\\"))) + ";"
            "function Add-DepthRow([object]$item,[string]$rel,[int]$level){"
            "  if($rows.Count -ge $cap){ $flags.truncated=$true; return };"
            "  [void]$rows.Add([ordered]@{Name=$item.Name; Length=$item.Length;"
            "  Modified=$item.LastWriteTimeUtc.ToString('o'); PSIsContainer=$item.PSIsContainer;"
            "  relative_path=$rel; depth=$level})"
            "};"
            "$frontier=@(@{dir=$folder; rel=''});"
            "$level=1;"
            "while($frontier.Count -gt 0 -and $level -le $maxDepth){"
            "  $next=@();"
            "  $ordered=@();"
            "  foreach($f in $frontier){"
            "    foreach($i in @(Get-ChildItem -LiteralPath $f.dir -Force"
            " -ErrorAction SilentlyContinue)){"
            "      $rel=if($f.rel){ $f.rel + [char]92 + $i.Name } else { $i.Name };"
            "      $ordered+=[ordered]@{item=$i; rel=$rel}"
            "    }"
            "  };"
            "  $ordered=@($ordered | Sort-Object -Property rel);"
            "  foreach($e in $ordered){"
            "    if($rows.Count -ge $cap){ $flags.truncated=$true; break };"
            "    Add-DepthRow $e.item $e.rel $level"
            "  };"
            "  foreach($e in $ordered){"
            "    if($e.item.PSIsContainer"
            " -and (($e.item.Attributes -band $skip) -eq 0)){"
            "      $next+=[ordered]@{dir=$e.item.FullName; rel=$e.rel}"
            "    }"
            "  };"
            "  if($rows.Count -ge $cap){"
            # Exactly at the cap is only a cut when something was left: another
            # row at this level, or a deeper folder still to walk.
            "    if($flags.truncated -or ($next.Count -gt 0 -and $level -lt $maxDepth))"
            "    { $flags.truncated=$true };"
            "    break"
            "  };"
            "  $frontier=$next;"
            "  $level++"
            "};"
            "$s=@($rows | Sort-Object -Property @{Expression={$_.relative_path}});"
            "@{offset=0; total=$s.Count; has_more=$false;"
            " truncated=$flags.truncated; depth=" + str(depth) + "; items=$s}"
            " | ConvertTo-Json -Compress -Depth 3"
            + " }"
        )
        return guard + walk
    if filter_term is None:
        scan = ("$p=@(Get-ChildItem -LiteralPath $folder"
                " -Force -ErrorAction Stop);")
    else:
        scan = (
            "$needle=" + ps_utf8_literal(filter_term) + ";"
            "$filter=" + ps_utf8_literal(_pc_files_filter_prefilter(filter_term)) + ";"
            "$p=@(Get-ChildItem -LiteralPath $folder -Filter $filter"
            " -Force -ErrorAction Stop"
            " | Where-Object { $_.Name.IndexOf($needle,"
            "[StringComparison]::OrdinalIgnoreCase) -ge 0 });"
        )
    return (
        guard
        + scan
        + "$s=@($p | Sort-Object -Property @{Expression={-not $_.PSIsContainer}}, Name);"
        "$n=$s.Count;"
        "$pg=@($s | Select-Object -Skip " + str(offset) + " -First " + str(page_size)
        + " | Select-Object Name, Length, "
        "@{n='Modified';e={$_.LastWriteTimeUtc.ToString('o')}}, PSIsContainer);"
        "@{offset=" + str(offset) + "; total=$n;"
        " has_more=(($pg.Count + " + str(offset) + ") -lt $n); items=@($pg)}"
        " | ConvertTo-Json -Compress -Depth 3"
        + " }"
    )


async def _engine_pc_files_owner(
    request: Request, *, product: str, subject_id: str,
) -> tuple[str | None, Any, JSONResponse | None]:
    """Resolve the product's current canonical owner session from the proof.

    The Engine proof authenticates the caller; the canonical session is still
    re-resolved here exactly like the existing signed Mesh lanes. No browser
    cookie, subject value or device value is trusted as authority.
    """
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(identity, "resolve_product_user_for_subject", None)):
        return None, None, _error(503, "claw_engine_identity_unavailable")
    try:
        uid = await identity.resolve_product_user_for_subject(
            product_id="b62", canonical_subject_id=subject_id,
        )
    except Exception:
        return None, None, _error(401, "canonical_session_required")
    if product == "claw":
        from padiem_control_plane.b54_identity_bridge import (
            resolve_current_b54_canonical_session as resolve_b54_session,
        )
        try:
            bridged = await resolve_b54_session(identity, uid)
        except Exception:
            return None, None, _error(401, "canonical_session_required")
        if (
            bridged is None
            or bridged.auth_session.subject.subject_id != subject_id
            or not bridged.auth_session.tenant_id
        ):
            return None, None, _error(401, "canonical_session_required")
        return uid, bridged.auth_session, None
    if not callable(getattr(identity, "resolve_current_auth_session", None)):
        return None, None, _error(503, "claw_engine_identity_unavailable")
    try:
        session = await identity.resolve_current_auth_session(
            product_id="b62", product_user_id=uid,
        )
    except Exception:
        return None, None, _error(401, "canonical_session_required")
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    if (
        session is None
        or session.subject.subject_id != subject_id
        or session.product_id != "b62"
        or not session.is_active(now=_dt.now(_tz.utc))
        or not session.tenant_id
    ):
        return None, None, _error(401, "canonical_session_required")
    # The product identity above is b62; the connector owner scope is the
    # shared B54 canonical session (#5088). Resolve the same bridge the Claw
    # signed lane uses instead of handing the b62 product session to the
    # owner-scope lookup.
    from padiem_control_plane.b54_identity_bridge import (
        resolve_current_b54_canonical_session as resolve_b54_session,
    )
    try:
        bridged = await resolve_b54_session(identity, uid)
    except Exception:
        return None, None, _error(401, "canonical_session_required")
    if (
        bridged is None
        or bridged.auth_session.subject.subject_id != subject_id
        or not bridged.auth_session.tenant_id
    ):
        return None, None, _error(401, "canonical_session_required")
    return uid, bridged.auth_session, None


#: The pairing directory could not be consulted at all, so the deployment map
#: decides. Distinct from the directory answering "this account has no PC",
#: which is a real answer and must never widen back to the map.
_DIRECTORY_UNUSABLE = "directory_unusable"


async def _pc_files_directory_target(
    request: Request, *, user_id: str, selected_device_id: str | None,
) -> tuple[str, dict[str, Any] | None]:
    """The owner's own linked PC, from migration 072's link table.

    R4's directory-first rule. A deployment with no pairing store, or one whose
    072 tables are not applied yet, falls through to the ownership map so it
    behaves exactly as before; an account the directory answered for is bounded
    by what it answered. Ambiguity stays a refusal, never a guess.
    """
    store = getattr(request.app.state, "pc_device_pairing_store", None)
    if not callable(getattr(store, "links_for_owner", None)):
        return _DIRECTORY_UNUSABLE, None
    try:
        links = await store.links_for_owner(user_id=user_id)
    except Exception:
        return _DIRECTORY_UNUSABLE, None
    if not isinstance(links, list):
        return _DIRECTORY_UNUSABLE, None
    if not links:
        return "empty", None
    matches = [
        link for link in links
        if isinstance(link, dict)
        and (
            selected_device_id is None
            or link.get("mesh_node_id") == selected_device_id
        )
    ]
    if len(matches) != 1:
        return "ambiguous", None
    link = matches[0]
    node_ref = link.get("mesh_node_id")
    roots = link.get("roots")
    if (
        not isinstance(node_ref, str) or not is_pc_device_id(node_ref)
        or not isinstance(roots, list) or not roots
    ):
        # A linked PC with no approved folder cannot answer a file call, and a
        # link that is not active never reaches here.
        return "unapproved", None
    return "link", {
        "node_ref": node_ref,
        # The link's composed node identity is the canonical device identity,
        # the same rule an unpinned ownership row already follows.
        "device_id": node_ref,
        "link_id": link.get("link_id"),
        "label": link.get("label"),
        "roots": roots,
    }


async def _engine_pc_files_target(
    request: Request, *, session: Any, selected_device_id: str | None, user_id: str,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Resolve the one owner target and the folders it may read.

    The context and the dispatch use this exact resolution, so the device the
    model is told about and the device that receives the command cannot drift
    apart. A selected device only narrows the choice; it never adds one. The
    account's own PC links decide first; the deployment ownership map is the
    fallback for a deployment that has no directory to ask.
    """
    source = getattr(request.app.state, "oracle_mesh_return_source", None)
    if (
        source is None
        or getattr(source, "configured", False) is not True
        or getattr(source, "execution_mode", None) != EXECUTION_MODE_MESH
    ):
        return None, _error(503, "oracle_mesh_unconfigured")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(identity, "resolve_connector_owner_scope", None)):
        return None, _error(503, "oracle_mesh_unconfigured")
    try:
        scope = await mode_connector_read(
            identity, "owner_scope", session_id=session.session_id,
        )
    except Exception as exc:
        emit_stage_event(
            stage="mesh.files_owner_scope", outcome="error", duration_ms=0,
            code=getattr(exc, "code", None),
        )
        return None, _error(503, "oracle_mesh_device_directory_unavailable")
    account_ref = scope.get("account_ref") if isinstance(scope, dict) else None
    workspace_ref = scope.get("workspace_ref") if isinstance(scope, dict) else None
    if (
        not isinstance(account_ref, str) or not account_ref
        or not isinstance(workspace_ref, str) or not workspace_ref
    ):
        return None, _error(503, "oracle_mesh_device_directory_unavailable")

    kind, linked = await _pc_files_directory_target(
        request, user_id=user_id, selected_device_id=selected_device_id,
    )
    if kind == "link":
        node_ref = linked["node_ref"]
        # The link decides which PC and which folders. What the Mesh client is
        # run against stays the deployment's own answer: a row that names this
        # device supplies the reference it already used, so an adopted identity
        # can never become a command sent to a node nobody listens to. A PC the
        # map does not name at all keeps the node it reported for itself.
        address_of = getattr(source, "mesh_node_ref_for_device", None)
        addressed = address_of(device_id=node_ref) if callable(address_of) else None
        if addressed is not None and addressed != node_ref:
            linked = {**linked, "node_ref": addressed}
        return {
            "authorized": True,
            "target": linked,
            "roots": linked["roots"],
            "account_ref": account_ref,
            "workspace_ref": workspace_ref,
        }, None
    # No answer from the directory is NOT an error here. #5906 made "this
    # account has no linked PC" a 403, and an ordinary chat turn that only asked
    # what tools exist then read as a failure. Context answers 200 with no roots
    # and no PC tools; only a call that actually needs a PC refuses.
    # #6695 PR-3: this transitional fallback ends with the same operating
    # switch that retires the TXT map lane. ``ORACLE_MESH_LEGACY_MAP_LANE=off``
    # leaves the ownership link as the only authority here — a directory answer
    # of "no usable link" then refuses instead of falling to the map, and a
    # directory that could not answer at all fails closed. Default (unset)
    # keeps today's behaviour: the two production PCs still run link-less.
    if not getattr(request.app.state, "oracle_mesh_legacy_map_lane", True):
        if kind == _DIRECTORY_UNUSABLE:
            return None, _error(503, "oracle_mesh_device_directory_unavailable")
        return None, None
    try:
        target = source.command_target(
            account_ref=account_ref, device_id=selected_device_id,
        )
    except Exception:
        if kind == _DIRECTORY_UNUSABLE:
            return None, _error(503, "oracle_mesh_device_directory_unavailable")
        return None, None
    if target is None:
        return None, None
    roots = _pc_files_roots_of_map_row(target.get("file_path"))
    if not roots:
        return None, _error(503, "oracle_mesh_file_root_unavailable")
    # #5573: transitional fallback — the map answers only while the lane
    # switch above still allows it, and it retires with that switch once the
    # production devices carry their ownership links.
    return {
        "authorized": True,
        "target": target,
        "roots": roots,
        "account_ref": account_ref,
        "workspace_ref": workspace_ref,
    }, None


async def _engine_pc_public_output(history_store: Any, *, payload: dict, uid: str,
                                   dispatch: dict, output: str, device_id: str | None = None,
                                   force: bool = False) -> tuple[dict | None, JSONResponse | None]:
    """Project verified command text; the full original stays outside model context."""
    if len(output) <= 4096 and not force:
        return {"output": output}, None
    store = getattr(history_store, "store_pc_output", None)
    if not callable(store):
        return None, _error(503, "pc_output_store_unavailable")
    try:
        if device_id is None:
            # Legacy drive status/result requests contain no device. Read the
            # pinned row's device, never guess the owner's current/default PC.
            reader = getattr(history_store, "get_pc_output_dispatch_for_owner", None)
            if not callable(reader):
                raise ValueError("output dispatch authority unavailable")
            owned = await reader(user_id=uid, dispatch_id=dispatch["dispatch_id"])
            if not isinstance(owned, dict) or owned.get("run_id") != payload["run_id"]:
                raise ValueError("output dispatch unavailable")
            device_id = owned.get("device_id")
        if not isinstance(device_id, str) or not device_id:
            raise ValueError("output device unavailable")
        ref = await store(user_id=uid, subject_id=payload["subject_id"], run_id=payload["run_id"],
                          device_id=device_id, dispatch_id=dispatch["dispatch_id"], content=output)
        if not isinstance(ref, dict) or not isinstance(ref.get("handle"), str):
            raise ValueError("output reference unavailable")
        preview = ref.get("head", "") + ("\n...\n" if ref.get("truncated") else "") + ref.get("tail", "")
        return {"output": preview, "output_ref": ref}, None
    except Exception:
        return None, _error(503, "pc_output_store_unavailable")


def _engine_pc_job_response(response: JSONResponse, mode: str) -> JSONResponse:
    if mode != "job_start" or response.status_code != 200:
        return response
    dispatch = json.loads(response.body)["dispatch"]
    return _response({"ok": True, "result": {
        "job_id": dispatch["dispatch_id"], "state": dispatch["state"],
        "device_id": dispatch["device_id"], "kind": dispatch["kind"],
    }})


async def _engine_pc_output_call(history_store: Any, *, payload: dict, uid: str, device_id: str) -> JSONResponse:
    """Read only the current authenticated owner/run/device's opaque output."""
    mode = payload["mode"]
    owner = {"user_id": uid, "subject_id": payload["subject_id"],
             "run_id": payload["run_id"], "device_id": device_id}
    try:
        if mode == "store_output":
            if (payload.get("source") != "pc_batch" or not isinstance(payload.get("output"), str)
                or not isinstance(payload.get("tool_call_ref"), str)
                or _PC_FILES_SAFE_REF.fullmatch(payload["tool_call_ref"]) is None):
                return _error(422, "pc_output_source_invalid")
            method = getattr(history_store, "store_pc_output", None)
            if not callable(method):
                return _error(503, "pc_output_store_unavailable")
            result = await method(**owner, dispatch_id="", content=payload["output"],
                                  source="pc_batch:" + payload["tool_call_ref"])
        else:
            handle = payload.get("handle")
            if not isinstance(handle, str) or re.fullmatch(r"[0-9a-f]{64}", handle) is None:
                return _error(422, "pc_output_handle_invalid")
            if mode == "read_output":
                method = getattr(history_store, "read_pc_output", None)
                if not callable(method):
                    return _error(503, "pc_output_store_unavailable")
                result = await method(**owner, handle=handle, offset=payload["offset"], length=payload["length"])
            else:
                query = payload.get("query")
                if not isinstance(query, str) or not query:
                    return _error(422, "pc_output_query_invalid")
                method = getattr(history_store, "search_pc_output", None)
                if not callable(method):
                    return _error(503, "pc_output_store_unavailable")
                result = await method(**owner, handle=handle, query=query)
        if not isinstance(result, dict):
            raise ValueError("invalid output response")
        return _response({"ok": True, "result": result})
    except (FileNotFoundError, PermissionError, HistoryForbidden):
        return _error(404, "pc_output_unavailable")
    except Exception:
        return _error(503, "pc_output_store_unavailable")


PC_IMAGE_ENVELOPE_PREFIX = "PADIEM_IMAGE_CONTENT:"
PC_IMAGE_LONG_EDGE_MAX = 2000
PC_IMAGE_BYTE_CAP = 300_000


def _pc_image_projection(output: str) -> tuple[str, dict[str, str] | None]:
    """#7447: one image envelope becomes a bounded note + one MCP image block.

    This handler is where the MCP/file lanes read a stored PC read result, so
    the envelope the PC agent frames is projected here as well as in the
    Engine driver. Anything that does not parse returns untouched.
    """
    if not output.startswith(PC_IMAGE_ENVELOPE_PREFIX):
        return output, None
    head, _, encoded = output[len(PC_IMAGE_ENVELOPE_PREFIX):].partition(":")
    mime = head.strip()
    if mime not in ("image/png", "image/jpeg", "image/webp", "image/gif") or not encoded:
        return output, None
    import base64
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        return output, None
    note = (f"이미지 파일을 읽었습니다: {mime}, {len(raw):,}바이트. "
            "(축소 없이 원본 그대로)")
    try:
        import io
        from PIL import Image

        image = Image.open(io.BytesIO(raw))
        source_size = image.size
        long_edge = max(image.size)
        if long_edge > PC_IMAGE_LONG_EDGE_MAX:
            ratio = PC_IMAGE_LONG_EDGE_MAX / long_edge
            image = image.resize(
                (max(1, round(image.size[0] * ratio)),
                 max(1, round(image.size[1] * ratio))))
            note_extra = f" 긴 변 {long_edge}px를 {PC_IMAGE_LONG_EDGE_MAX}px로 축소."
        else:
            note_extra = ""
        fmt = "PNG" if mime == "image/png" else (
            "JPEG" if mime == "image/jpeg" else "PNG")
        buf = io.BytesIO()
        image.save(buf, format=fmt)
        if len(buf.getvalue()) > PC_IMAGE_BYTE_CAP:
            converted = image.convert("RGB")
            for quality, edge in ((80, None), (50, 1280), (35, 800)):
                buf = io.BytesIO()
                step = converted
                if edge and max(step.size) > edge:
                    ratio = edge / max(step.size)
                    step = step.resize((max(1, round(step.size[0] * ratio)),
                                        max(1, round(step.size[1] * ratio))))
                step.save(buf, format="JPEG", quality=quality)
                fmt = "JPEG"
                if len(buf.getvalue()) <= PC_IMAGE_BYTE_CAP:
                    break
            image = step
            note_extra = f" 용량 상한에 맞춰 JPEG({quality})로 재부호화.{note_extra}"
        out_mime = {"PNG": "image/png", "JPEG": "image/jpeg"}[fmt]
        data = buf.getvalue()
        note = (
            f"이미지 파일을 읽었습니다: {mime}, "
            f"{source_size[0]}x{source_size[1]} → {image.size[0]}x{image.size[1]}, "
            f"{len(data):,}바이트.{note_extra}"
        )
    except Exception:
        # Pillow unavailable or an undecodable frame: the projection still
        # carries what the PC actually read, with no downscale claim — but an
        # original above PC_IMAGE_BYTE_CAP never ships unscaled. Without
        # Pillow there is no way to meet the cap, so the caller gets the
        # bounded text only (CTO decision 2026-11-13, #7447 follow-up).
        if len(raw) > PC_IMAGE_BYTE_CAP:
            return (f"이미지 파일을 읽었습니다: {mime}, {len(raw):,}바이트. "
                    "이미지 축소를 쓸 수 없어 그림을 보내지 못했습니다."), None
        return note, {"type": "image", "mimeType": mime,
                      "data": base64.b64encode(raw).decode("ascii")}
    return note, {"type": "image", "mimeType": out_mime,
                  "data": base64.b64encode(data).decode("ascii")}


async def _engine_pc_files_call(request: Request, *, product: str) -> JSONResponse:
    """One signed Engine call for the PC file context/dispatch/status/result."""
    resp, bundle = await _engine_pc_files_call_verify(request, product=product)
    if resp is not None:
        return resp
    scope_claim = bundle["scope_claim"]
    payload = bundle["payload"]
    requested_mode = bundle["requested_mode"]
    mode = bundle["mode"]
    selected = bundle["selected"]
    uid = bundle["uid"]
    session = bundle["session"]
    history_store = bundle["history_store"]
    run_row = bundle["run_row"]
    new_mode = bundle["new_mode"]
    resolved = bundle["resolved"]
    target = bundle["target"]
    roots = bundle["roots"]
    device_id = bundle["device_id"]

    if mode in ("context", "dispatch") and scope_claim is not None:
        scope_pinner = getattr(history_store, "pin_pc_run_scope", None)
        if not callable(scope_pinner):
            return _error(503, "pc_scope_store_unavailable")
        try:
            await scope_pinner(user_id=uid, run_id=payload["run_id"], claim=scope_claim)
        except HistoryForbidden:
            return _error(403, "pc_scope_frozen")
        except Exception:
            return _error(503, "pc_scope_store_unavailable")

    if mode == "context":
        # (A): the model is shown the owner's own names for the approved
        # folders, never a real path. One folder keeps the single-folder shape
        # the tools already speak; several arrive as a label list, and a call
        # must then name which one it means.
        labels = [root["label"] for root in roots]
        return _response({
            "ok": True,
            "roots": [{"label": label} for label in labels],
            # Engine guard only. The model projection remains device/tools;
            # matching a saved absolute folder to a labeled relative tool path
            # must use these owner-verified roots, never guess a home directory.
            "delegation_roots": [{"label": root["label"], "path": root["path"]} for root in roots],
            "device": {
                "device_id": device_id,
                "status": "configured",
                "folder": {
                    "name": labels[0] if len(labels) == 1 else (target.get("label") or "PC"),
                    "relative_path": ".",
                },
                "online_verified": False,
            },
            "tools": [
                "claw.pc.list_files",
                "claw.pc.read_file",
                "claw.pc.search_files",
                "claw.pc.search_contents",
                "claw.pc.query_drives",
            ],
            "run_id": payload["run_id"],
        })

    if requested_mode in ("read_output", "search_output", "store_output"):
        return await _engine_pc_output_call(
            history_store, payload=payload, uid=uid, device_id=device_id,
        )

    # The Engine has reached a real PC step for this proof- and owner-verified
    # run, so the conversation's staged row moves pending -> running. Status
    # only: no result_summary is ever passed, so a step in flight cannot be
    # mistaken for the run's answer, and the guarded write leaves a completed
    # run untouched. A lost projection must not fail the step that is running.
    mark_running = getattr(history_store, "update_claw_run_status", None)
    if callable(mark_running):
        try:
            await mark_running(uid, payload["run_id"], "running")
        except Exception:
            pass

    resp, _bundle = await _engine_pc_files_call_dispatch(
        request, payload=payload, requested_mode=requested_mode, mode=mode,
        scope_claim=scope_claim, roots=roots, selected=selected,
        session=session, uid=uid, target=target,
    )
    if resp is not None:
        return resp

    dispatch_id = payload.get("dispatch_id")
    if not isinstance(dispatch_id, str) or not 0 < len(dispatch_id) <= 128:
        return _error(400, "claw_engine_files_invalid_body")
    reader = getattr(history_store, "get_oracle_mesh_dispatch_for_owner", None)
    if not callable(reader):
        return _error(503, "oracle_mesh_unconfigured")
    try:
        dispatch = await reader(user_id=uid, dispatch_id=dispatch_id)
    except Exception:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    kind = dispatch.get("kind") if isinstance(dispatch, dict) else None
    if (
        not isinstance(dispatch, dict)
        or dispatch.get("run_id") != payload["run_id"]
        or kind not in ("command", "read")
    ):
        return _error(404, "oracle_mesh_run_unavailable")
    if scope_claim is not None and kind == "read" and "read" not in scope_claim["ops"]:
        return _error(403, "pc_scope_denied")
    if new_mode:
        # The public row carries no device binding; the owner-scoped private
        # read is where it lives.
        private_reader = getattr(history_store, "get_pc_output_dispatch_for_owner", None)
        private = await private_reader(user_id=uid, dispatch_id=dispatch_id) if callable(private_reader) else None
        bound = private.get("device_id") if isinstance(private, dict) else dispatch.get("device_id")
        if bound != device_id:
            return _error(404, "oracle_mesh_run_unavailable")
    state = dispatch.get("state")
    if state not in {"pending", "received", "store_failed", "done", "failed"}:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    if requested_mode == "job_status":
        return _response({"ok": True, "result": {
            "job_id": dispatch_id,
            "state": "running" if state == "pending" and dispatch.get("claimed") is True else state,
            "kind": kind, "termination": dispatch.get("termination"), "exit_code": dispatch.get("exit_code"),
            **({"operation": dispatch["job_operation"]} if isinstance(dispatch.get("job_operation"), dict) else {}),
        }})
    if mode == "command_status":
        return _response({
            "ok": True,
            "dispatch": {
                "dispatch_id": dispatch["dispatch_id"],
                "run_id": payload["run_id"],
                "kind": kind,
                "state": state,
                "result_sha256": dispatch.get("result_sha256"),
                "termination": dispatch.get("termination"),
                "exit_code": dispatch.get("exit_code"),
                # The continuation leg projects the finished listing against the
                # folder it was asked about; the Engine sent this path and is the
                # only reader of this response.
                "file_path": dispatch.get("file_path"),
            },
        })
    # A command result is ready only after a clean terminal row. A read keeps
    # its verified body on a failed row too (the executor's bounded
    # PADIEM_PC_FILE_ERROR marker), so the Engine can surface the same error
    # mapping instead of losing it to an empty outcome.
    if kind == "read":
        if state not in ("done", "failed"):
            return _error(409, "oracle_mesh_result_not_ready")
    elif state != "done" and not (requested_mode == "job_output" and state == "failed"):
        return _error(409, "oracle_mesh_result_not_ready")
    termination = dispatch.get("termination")
    exit_code = dispatch.get("exit_code")
    if termination not in (
        "exited", "no_exit_code", "output_too_large", "not_executed",
        "timed_out", "cancelled", "no_reply", "bad_reply",
    ):
        return _error(503, "oracle_mesh_original_unavailable")
    if exit_code is None:
        if termination not in (
            "timed_out", "no_reply", "no_exit_code", "not_executed",
            "output_too_large", "cancelled", "bad_reply",
        ):
            return _error(503, "oracle_mesh_original_unavailable")
    elif isinstance(exit_code, bool) or not isinstance(exit_code, int):
        return _error(503, "oracle_mesh_original_unavailable")
    try:
        conversation_id = validate_conversation_id(
            (run_row or {}).get("conversation_id"),
        )
        if not conversation_id:
            return _error(404, "oracle_mesh_run_unavailable")
        message_id = result_message_id(
            conversation_id=conversation_id,
            command_id=dispatch["command_id"],
            revision_ref=dispatch["revision_ref"],
        )
        stored = await history_store.read_oracle_mesh_original(
            user_id=uid, dispatch_id=dispatch["dispatch_id"],
            conversation_id=conversation_id, message_id=message_id,
        )
    except Exception:
        return _error(503, "oracle_mesh_original_unavailable")
    if stored is None:
        return _error(404, "oracle_mesh_original_unavailable")
    content, digest = stored
    if (
        not isinstance(content, bytes)
        or hashlib.sha256(content).hexdigest() != digest
        or digest != dispatch.get("result_sha256")
    ):
        return _error(503, "oracle_mesh_original_unavailable")
    try:
        output = content.decode("utf-8")
    except UnicodeDecodeError:
        return _error(503, "oracle_mesh_original_unavailable")
    image_block = None
    if kind == "read" and output.startswith(PC_IMAGE_ENVELOPE_PREFIX):
        output, image_block = _pc_image_projection(output)
    output_ref = None
    if len(output) > 4096 or requested_mode == "job_output":
        public_output, output_error = await _engine_pc_public_output(
            history_store, payload=payload, uid=uid, dispatch=dispatch,
            output=output, device_id=device_id, force=True,
        )
        if output_error is not None:
            return output_error
        output_ref = public_output["output_ref"]
        if requested_mode == "job_output":
            page = await _engine_pc_output_call(
                history_store,
                payload={**payload, "mode": "read_output", "handle": output_ref["handle"]},
                uid=uid, device_id=device_id,
            )
            if page.status_code != 200:
                return page
            result = json.loads(page.body)["result"]
            # The projected image block rides beside the paged output: a
            # job_output re-read must answer with the same image the direct
            # result carried (#7447).
            return _response({"ok": True, "result": {
                **result, "job_id": dispatch_id, "state": state,
                "output_ref": output_ref, "termination": termination, "exit_code": exit_code,
                **({"operation": dispatch["job_operation"]} if isinstance(dispatch.get("job_operation"), dict) else {}),
                **({"_pc_image": image_block} if image_block else {}),
            }})
        output = public_output["output"]
    # #7447/#7473: only a projected image read answers with the note as
    # its body, so content length/digest must describe the note the Engine
    # validates against. The stored-output reference and the plain text
    # lane keep the stored original's values: the Engine pins
    # content_bytes to the reference size there (#7473 review).
    if image_block is not None and output_ref is None:
        content_sha256 = hashlib.sha256(output.encode("utf-8")).hexdigest()
        content_bytes = len(output.encode("utf-8"))
    else:
        content_sha256 = digest
        content_bytes = len(content)
    return _response({
        "ok": True,
        "dispatch": {
            "dispatch_id": dispatch["dispatch_id"],
            "run_id": payload["run_id"],
            "kind": kind,
            "state": state,
            "result_sha256": digest,
            # A continuation projects the finished listing against the folder it
            # was asked about; the Engine sent this path and is the only reader.
            "file_path": dispatch.get("file_path"),
            "content_sha256": content_sha256,
            "content_bytes": content_bytes,
            "output": output,
            **({"_pc_image": image_block} if image_block else {}),
            **({"output_ref": output_ref} if output_ref else {}),
            "termination": termination,
            "exit_code": exit_code,
        },
    })


async def _engine_pc_files_call_dispatch(
    request: Request, *, payload: dict, requested_mode: str, mode: str,
    scope_claim: dict | None, roots: list, selected: str | None,
    session: Any, uid: str, target: dict,
) -> tuple[JSONResponse | None, dict[str, object]]:
    """디스패치 분기 구간.

    본문은 리팩터 전 `_engine_pc_files_call`의 연속 구간을 글자 그대로 옮긴다.
    검사 순서·실패 응답·await 순서·디스패치 생성 인자를 그대로 지킨다.
    """
    if mode == "dispatch":
        op = payload.get("op")
        if op not in _PC_FILES_OPS:
            return _error(422, "oracle_mesh_file_op_invalid"), {}
        search_mode = None
        claim_op = op
        if op == "search":
            search_mode = pc_search_mode(payload.get("search_mode"))
            claim_op = _pc_files_claim_op(op, search_mode)
            if claim_op is None:
                return _error(422, "oracle_mesh_file_search_invalid"), {}
        # The independently signed ceiling is enforced before either dispatch
        # constructor. The existing owner/path/size/idempotency checks follow.
        if scope_claim is not None and claim_op not in scope_claim["ops"]:
            return _error(403, "pc_scope_denied"), {}
        search_roots = None
        if op == "search":
            # No folder named means every approved root, in order: the owner's
            # grant is the whole set, so a search never has to guess one and is
            # never refused for not naming one.
            search_roots = _pc_files_search_roots(roots, payload.get("path"))
            if search_roots is None:
                return _error(422, "oracle_mesh_file_path_invalid"), {}
            if pc_search_roots(search_roots) is None:
                return _error(503, "oracle_mesh_file_root_unavailable"), {}
            root = relative = None
        else:
            picked = _pc_files_pick_root(roots, payload.get("path"))
            if picked is None:
                return _error(422, "oracle_mesh_file_path_invalid"), {}
            root, relative = picked
            if op == "read" and not relative:
                return _error(422, "oracle_mesh_file_path_invalid"), {}
        tool_call_ref = payload.get("tool_call_ref")
        if (
            not isinstance(tool_call_ref, str)
            or _PC_FILES_SAFE_REF.fullmatch(tool_call_ref) is None
        ):
            return _error(422, "oracle_mesh_file_call_invalid"), {}
        command_workspace = await _dispatch_workspace_id(request, uid, session)
        if not command_workspace:
            return _error(503, "oracle_mesh_workspace_unavailable"), {}
        job_operation = {"op": op, "path": payload["path"]} if requested_mode == "job_start" else None
        if op in _PC_WRITE_OPS:
            # One write step, one account. The path the PC will change is built
            # the way the listing builds its folder - the root the server picked
            # plus the relative path the caller named - so a request never
            # carries an absolute target of its own.
            resolved = root.rstrip("/") + ("/" + relative if relative else "")
            content_b64 = None
            append = False
            if op == "write":
                content = payload.get("content")
                if not isinstance(content, str):
                    return _error(422, "oracle_mesh_file_content_invalid"), {}
                if "append" in payload and type(payload["append"]) is not bool:
                    return _error(422, "oracle_mesh_file_mode_invalid"), {}
                append = payload.get("append") is True
                content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
                if job_operation is not None:
                    job_operation.update(expected_bytes=len(content.encode("utf-8")),
                                         expected_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest())
                    if append:
                        job_operation["mode"] = "append"
            old_text_b64 = new_text_b64 = None
            if op == "edit":
                # #7065: the two byte sequences are carried the same way the
                # write carries its bytes, so no console code page or quoting
                # rule can change what is searched for or what is written.
                old_text, new_text = payload.get("old_text"), payload.get("new_text")
                if not isinstance(old_text, str) or not isinstance(new_text, str):
                    return _error(422, "oracle_mesh_file_edit_invalid"), {}
                if not old_text:
                    return _error(422, "oracle_mesh_file_edit_invalid"), {}
                replace_all = payload.get("replace_all")
                if replace_all is not None and not isinstance(replace_all, bool):
                    return _error(422, "oracle_mesh_file_edit_invalid"), {}
                if job_operation is not None:
                    job_operation["edit"] = True
                old_text_b64 = base64.b64encode(old_text.encode("utf-8")).decode("ascii")
                new_text_b64 = base64.b64encode(new_text.encode("utf-8")).decode("ascii")
            destination_path = None
            if op == "move":
                picked_destination = _pc_files_pick_root(roots, payload.get("destination"))
                if picked_destination is None:
                    return _error(422, "oracle_mesh_file_path_invalid"), {}
                destination_root, destination_relative = picked_destination
                if destination_root != root or not destination_relative:
                    # A move stays inside the folder this link was granted, and
                    # never onto the granted root itself: replacing a whole
                    # folder is not what moving one file means.
                    return _error(422, "oracle_mesh_file_path_invalid"), {}
                destination_path = destination_root.rstrip("/") + "/" + destination_relative
                if job_operation is not None:
                    job_operation["destination"] = payload["destination"]
            command = _pc_write_command(
                op=op,
                root=root,
                target=resolved,
                backup_dir=_pc_backup_dir(
                    root, datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                ),
                relative=relative,
                destination=destination_path,
                content_b64=content_b64,
                old_text_b64=old_text_b64,
                new_text_b64=new_text_b64,
                append=append,
                replace_all=bool(payload.get("replace_all")),
            )
            response = await dispatch_oracle_mesh_command_intent(
                request, command=command,
                wire={
                    "run_id": payload["run_id"],
                    "device_id": selected,
                    "confirmed": True,
                },
                trusted_owner=(session, uid, command_workspace),
                tool_call_ref=tool_call_ref,
                files_target=target,
                background=requested_mode == "job_start",
                job_operation=job_operation,
            )
            return _engine_pc_job_response(response, requested_mode), {}
        if op == "read":
            # #5015: the read reuses the existing kind="read" MeshCentral
            # download lane. No shell command is built for it.
            response = await dispatch_oracle_mesh_file_read_intent(
                request,
                wire={
                    "run_id": payload["run_id"],
                    "device_id": selected,
                    "confirmed": True,
                },
                trusted_owner=(session, uid, command_workspace),
                tool_call_ref=tool_call_ref,
                target=target,
                root=root,
                relative=relative,
                background=requested_mode == "job_start",
                job_operation=job_operation,
            )
            return _engine_pc_job_response(response, requested_mode), {}
        if op == "read_chunk":
            offset = pc_read_offset(payload.get("offset"))
            length = pc_read_length(payload.get("length"))
            if offset is None or length is None or not relative:
                return _error(422, "oracle_mesh_file_range_invalid"), {}
            command = pc_read_chunk_command(
                root=root, relative=relative, offset=offset, length=length,
            )
            return await dispatch_oracle_mesh_command_intent(
                request, command=share_command_prefix([root]) + command,
                wire={
                    "run_id": payload["run_id"],
                    "device_id": selected,
                    "confirmed": True,
                },
                trusted_owner=(session, uid, command_workspace),
                tool_call_ref=tool_call_ref,
                files_target=target,
                read_only=True,
                share_roots=share_roots_of([root]),
            ), {}
        if op == "search":
            query = pc_search_query(payload.get("query"))
            if query is None:
                return _error(422, "oracle_mesh_file_search_invalid"), {}
            command = pc_search_command(
                roots=search_roots, query=query, mode=search_mode,
                limit=PC_SEARCH_MAX_LIMIT,
            )
            return await dispatch_oracle_mesh_command_intent(
                request, command=share_command_prefix(search_roots) + command,
                wire={
                    "run_id": payload["run_id"],
                    "device_id": selected,
                    "confirmed": True,
                },
                trusted_owner=(session, uid, command_workspace),
                tool_call_ref=tool_call_ref,
                files_target=target,
                read_only=True,
                share_roots=share_roots_of(search_roots),
            ), {}
        depth = payload.get("depth")
        if "depth" in payload and (
            type(depth) is not int or isinstance(depth, bool) or not 1 <= depth <= 3
        ):
            return _error(422, "oracle_mesh_file_depth_invalid"), {}
        offset = payload.get("offset")
        if "offset" in payload and (
            type(offset) is not int or isinstance(offset, bool) or not 0 <= offset <= 10_000
        ):
            return _error(422, "oracle_mesh_file_offset_invalid"), {}
        if (depth or 1) > 1 and (offset or 0) != 0:
            return _error(422, "oracle_mesh_file_offset_invalid"), {}
        recursive = payload.get("recursive")
        if "recursive" in payload and type(recursive) is not bool:
            return _error(422, "oracle_mesh_file_recursive_invalid"), {}
        if recursive is True:
            # This leg carries no name fragment, and the recursive builder
            # refuses to walk without one. A recursive name search travels as
            # the search op instead, so the flag is refused here by name rather
            # than left to fail inside the builder.
            return _error(422, "oracle_mesh_file_recursive_unsupported"), {}
        command = _pc_files_command(
            op=op, root=root, relative=relative,
            depth=depth if depth is not None else 1,
            offset=offset if offset is not None else 0,
        )
        response = await dispatch_oracle_mesh_command_intent(
            request, command=share_command_prefix([root]) + command,
            wire={
                "run_id": payload["run_id"],
                "device_id": selected,
                "confirmed": True,
            },
            trusted_owner=(session, uid, command_workspace),
            tool_call_ref=tool_call_ref,
            files_target=target,
            # #7602: only a read is handed out again after a run-out lease.
            read_only=_pc_files_read_only(op),
            share_roots=share_roots_of([root]),
            background=requested_mode == "job_start",
                job_operation=job_operation,
        )
        return _engine_pc_job_response(response, requested_mode), {}
    return None, {}


async def _engine_pc_files_call_verify(
    request: Request, *, product: str,
) -> tuple[JSONResponse | None, dict[str, object]]:
    """서명·본문 파싱·모드 검증·소유자/대상 확인 구간.

    본문은 리팩터 전 `_engine_pc_files_call`의 연속 구간을 글자 그대로 옮긴다.
    검사 순서와 실패 응답, await 순서를 그대로 지킨다.
    """
    raw, proof_error = await _verify_engine_proof(request, max_body_bytes=None)
    if proof_error is not None or raw is None:
        return (proof_error if proof_error is not None else _error(
            401, "claw_engine_proof_required",
        )), {}
    scope_claim, scope_error = _engine_pc_scope_claim(request, raw, product=product)
    if scope_error is not None:
        return scope_error, {}
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return _error(400, "claw_engine_files_invalid_body"), {}
    if not isinstance(payload, dict):
        return _error(400, "claw_engine_files_invalid_body"), {}
    requested_mode = mode = payload.get("mode")
    # Only the dispatch leg has optional fields today; every other leg is exact.
    optional = set()
    if mode == "context":
        expected = {"subject_id", "run_id", "device_id", "mode"}
    elif mode == "dispatch":
        expected = {
            "subject_id", "run_id", "device_id", "op", "path",
            "tool_call_ref", "mode",
        }
        # A write names its bytes and a move names where the file lands. Nothing
        # else may add a field, and the operation itself is validated below.
        # A search names its query and which side of the file it looks at.
        extra_fields = {"write": {"content"}, "move": {"destination"},
                        "search": {"query", "search_mode"},
                        "read_chunk": {"offset", "length"}}
        # #7603: a write may name the append spelling. It is its own boolean
        # because `mode` in this body already names the transport leg.
        optional_fields = {"write": {"append"}}
        named = payload.get("op")
        if isinstance(named, str) and named in extra_fields:
            expected = expected | extra_fields[named]
        if isinstance(named, str) and named in optional_fields:
            optional = optional_fields[named]
        else:
            optional = set()
        if named == "list":
            # The widened read-only listing carries its depth and recursive
            # flag only when the caller named them; both are re-validated
            # (type and range) below before any command is built.
            for key in ("depth", "recursive"):
                if key in payload:
                    expected = expected | {key}
    elif mode == "job_start":
        expected = {"subject_id", "run_id", "device_id", "mode", "operation", "tool_call_ref"}
    elif mode == "job_status":
        expected = {"subject_id", "run_id", "device_id", "mode", "job_id"}
    elif mode == "job_output":
        expected = {"subject_id", "run_id", "device_id", "mode", "job_id", "offset", "length"}
    elif mode == "read_output":
        expected = {"subject_id", "run_id", "device_id", "mode", "handle", "offset", "length"}
    elif mode == "search_output":
        expected = {"subject_id", "run_id", "device_id", "mode", "handle", "query"}
    elif mode == "store_output":
        expected = {"subject_id", "run_id", "device_id", "mode", "output", "source", "tool_call_ref"}
    elif mode in ("command_status", "result"):
        expected = {"subject_id", "run_id", "dispatch_id", "mode"}
    else:
        return _error(400, "claw_engine_files_invalid_body"), {}
    if not (expected <= set(payload) <= expected | optional):
        return _error(400, "claw_engine_files_invalid_body"), {}
    if not all(
        isinstance(payload.get(name), str) and 0 < len(payload[name]) <= 512
        for name in ("subject_id", "run_id")
    ):
        return _error(400, "claw_engine_files_invalid_body"), {}
    if requested_mode == "job_start":
        operation = payload.get("operation")
        if not isinstance(operation, dict) or operation.get("op") not in _PC_FILES_OPS:
            return _error(422, "oracle_mesh_file_op_invalid"), {}
        op = operation["op"]
        operation_fields = ({"op", "path"}
                            | ({"content"} if op == "write" else
                               {"old_text", "new_text", "replace_all"} if op == "edit" else
                               {"destination"} if op == "move" else set()))
        operation_optional = {"mode"} if op == "write" else set()
        if not (operation_fields <= set(operation)
                <= operation_fields | operation_optional):
            return _error(400, "claw_engine_files_invalid_body"), {}
        # The operation's own `mode` is the write spelling (overwrite/append),
        # not this body's transport leg. It must never replace the leg name,
        # and an append must reach the dispatch below as the `append` boolean:
        # dropping it here would turn a requested append into an overwrite.
        operation = dict(operation)
        write_mode = operation.pop("mode", None)
        if write_mode not in (None, "overwrite", "append"):
            return _error(422, "oracle_mesh_file_mode_invalid"), {}
        payload = {**payload, **operation}
        if write_mode == "append":
            payload["append"] = True
        mode = "dispatch"
    elif requested_mode in ("job_status", "job_output"):
        payload["dispatch_id"] = payload["job_id"]
        mode = "command_status" if requested_mode == "job_status" else "result"
    new_mode = requested_mode in {"job_start", "job_status", "job_output", "read_output", "search_output", "store_output"}
    if new_mode and scope_claim is None:
        return _error(403, "pc_scope_required"), {}
    if new_mode and (not isinstance(payload.get("device_id"), str) or not payload["device_id"]):
        return _error(422, "oracle_mesh_device_invalid"), {}
    if requested_mode in ("job_output", "read_output") and (
        type(payload.get("offset")) is not int or payload["offset"] < 0
        or type(payload.get("length")) is not int or not 0 <= payload["length"] <= 65536
    ):
        return _error(422, "pc_output_range_invalid"), {}
    selected = payload.get("device_id")
    if selected is not None and (
        not isinstance(selected, str) or not 0 < len(selected) <= 128
    ):
        return _error(422, "oracle_mesh_device_invalid"), {}
    uid, session, owner_error = await _engine_pc_files_owner(
        request, product=product, subject_id=payload["subject_id"],
    )
    if owner_error is not None:
        return owner_error, {}
    history_store = getattr(request.app.state, "history_store", None)
    if history_store is None or not callable(
        getattr(history_store, "get_claw_run", None)
    ):
        return _error(503, "oracle_mesh_unconfigured"), {}
    try:
        run_row = await history_store.get_claw_run(uid, payload["run_id"])
        if run_row is None and product == "chat" and mode == "context" and scope_claim is not None:
            from .chat_pc_drive import promote_chat_pc_stream_run
            run_row = await promote_chat_pc_stream_run(
                request, uid=uid, run_id=payload["run_id"], device_id=selected,
                action="pc_files_query",
            )
    except Exception:
        return _error(503, "oracle_mesh_run_unavailable"), {}
    if (
        not isinstance(run_row, dict)
        or run_row.get("run_id") != payload["run_id"]
        or not isinstance(run_row.get("conversation_id"), str)
        or not run_row["conversation_id"]
    ):
        return _error(404, "oracle_mesh_run_unavailable"), {}

    scope_reader = getattr(history_store, "get_pc_run_scope", None)
    try:
        saved_scope = await scope_reader(user_id=uid, run_id=payload["run_id"]) if callable(scope_reader) else None
    except Exception:
        return _error(503, "pc_scope_store_unavailable"), {}
    if saved_scope is not None and scope_claim != saved_scope:
        return _error(403, "pc_scope_required" if scope_claim is None else "pc_scope_frozen"), {}

    # The status/result legs carry only the dispatch id; adding a device hint
    # is a malformed body by contract. The dispatch itself names the PC that
    # ran the step, so use that node for the target check. Re-resolving a
    # multi-link owner without it can only answer "ambiguous" and refuse a
    # step that already ran.
    if mode in ("command_status", "result") and selected is None:
        # The private owner-scoped reader is the dispatch authority that also
        # names its PC; the public read intentionally keeps the normal row's
        # shape. Neither leg accepts a device hint from the Engine.
        reader = getattr(history_store, "get_pc_output_dispatch_for_owner", None)
        if not callable(reader):
            reader = getattr(history_store, "get_oracle_mesh_dispatch_for_owner", None)
        if callable(reader) and isinstance(payload.get("dispatch_id"), str):
            try:
                status_dispatch = await reader(
                    user_id=uid, dispatch_id=payload["dispatch_id"],
                )
            except Exception:
                status_dispatch = None
            if isinstance(status_dispatch, dict):
                hint = status_dispatch.get("node_ref") or status_dispatch.get("device_id")
                if isinstance(hint, str) and hint:
                    selected = hint

    resolved, target_error = await _engine_pc_files_target(
        request, session=session, selected_device_id=selected, user_id=uid,
    )
    if target_error is not None:
        return target_error, {}
    if resolved is None:
        # No PC for this account: tool discovery answers honestly instead of
        # failing the turn, and only a call that needs a device is refused.
        if mode == "context":
            return _response({
                "ok": True,
                "roots": [],
                "device": {"device_id": selected, "status": "not_connected",
                           "online_verified": False},
                "tools": [],
                "run_id": payload["run_id"],
            }), {}
        return _error(403, "oracle_mesh_device_unverified"), {}
    target = resolved["target"]
    roots = resolved["roots"]
    device_id = target.get("device_id") or target["node_ref"]
    return None, {
        "scope_claim": scope_claim,
        "payload": payload,
        "requested_mode": requested_mode,
        "mode": mode,
        "selected": selected,
        "uid": uid,
        "session": session,
        "history_store": history_store,
        "run_row": run_row,
        "new_mode": new_mode,
        "resolved": resolved,
        "target": target,
        "roots": roots,
        "device_id": device_id,
    }


async def oracle_mesh_engine_claw_files_call(request: Request) -> JSONResponse:
    return await _engine_pc_files_call(request, product="claw")


@chat_pc_dispatch_ttl
async def oracle_mesh_engine_chat_files_call(request: Request) -> JSONResponse:
    return await _engine_pc_files_call(request, product="chat")


async def oracle_mesh_engine_desktop_call(request: Request) -> JSONResponse:
    """Engine-only authenticated desktop dispatch; browser cookies never act as proof.

    A signed call carries only an owner session reference and existing run id.
    Control Plane must resolve the current session independently before the
    existing owner-scoped desktop dispatch may run.
    """
    # #6460 step 3: a loop step may carry a typed value up to the one-shot
    # store's bound, so this lane's proof envelope is sized for it; every
    # field is still parsed and bounded below.
    raw, proof_error = await _verify_engine_proof(request, max_body_bytes=_MAX_DESKTOP_ENGINE_BODY_BYTES)
    if proof_error is not None or raw is None:
        return proof_error if proof_error is not None else _error(401, "claw_engine_proof_required")
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return _error(400, "claw_engine_desktop_invalid_body")
    status_query = isinstance(payload, dict) and payload.get("mode") in ("status", "image", "result", "command_status")
    run_query = isinstance(payload, dict) and payload.get("mode") == "run_status"
    command_dispatch = isinstance(payload, dict) and payload.get("mode") == "dispatch"
    desktop_dispatch = not status_query and not run_query and not command_dispatch
    expected_keys = (
        {"subject_id", "run_id", "dispatch_id", "mode"} if status_query
        else {"subject_id", "run_id", "mode"} if run_query
        else {"subject_id", "run_id", "device_id", "command", "mode"} if command_dispatch
        else {"subject_id", "run_id", "device_id", "desktop_op"}
    )
    # A loop step adds its own dispatch scope, and an Engine-chosen typed value
    # travels beside the op so it never enters the row. Both are optional, so
    # the single-action body stays byte-for-byte what it was.
    optional_keys = (frozenset({"call_ref", "desktop_text"})
                     if desktop_dispatch else frozenset())
    if (not isinstance(payload, dict)
        or not (expected_keys <= set(payload) <= expected_keys | optional_keys)
        or not all(
            isinstance(payload[k], str) and 0 < len(payload[k]) <= 512
            for k in ("subject_id", "run_id")
        )
        or (status_query and (not isinstance(payload["dispatch_id"], str)
            or not 0 < len(payload["dispatch_id"]) <= 128))
        or (command_dispatch and (
            payload.get("device_id") is not None and not isinstance(payload.get("device_id"), str)
            or not isinstance(payload.get("command"), str)
            or payload.get("command") != "Get-PSDrive -PSProvider FileSystem | Select-Object Name,Root,Used,Free | ConvertTo-Json"
        ))
        or (desktop_dispatch and (
            not isinstance(payload["desktop_op"], str)
            or not 0 < len(payload["desktop_op"]) <= 512
            or (payload["device_id"] is not None and (
                not isinstance(payload["device_id"], str)
                or not 0 < len(payload["device_id"]) <= 128))
            or ("call_ref" in payload and (
                not isinstance(payload["call_ref"], str)
                or not 0 < len(payload["call_ref"]) <= 120
                or any(ord(ch) < 33 or ord(ch) > 126 for ch in payload["call_ref"])))
            or ("desktop_text" in payload and (
                not isinstance(payload["desktop_text"], str)
                or not 0 < len(payload["desktop_text"]) <= _MAX_TYPED_TEXT_CHARS))))):
        return _error(400, "claw_engine_desktop_invalid_body")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(identity, "resolve_product_user_for_subject", None)):
        return _error(503, "claw_engine_identity_unavailable")
    # #5015: reuse the existing shared login/session bridge. The owner signs in
    # to the Chat product; the canonical B54 session is resolved from that same
    # server-known product user, so the Claw lane never requires a second,
    # separately active B54 login surface. The product is pinned inside the
    # Control Plane bridge and no browser/session value is accepted here.
    from padiem_control_plane.b54_identity_bridge import (
        resolve_current_b54_canonical_session as resolve_b54_session,
    )
    try:
        uid = await identity.resolve_product_user_for_subject(
            product_id="b62",
            canonical_subject_id=payload["subject_id"],
        )
    except Exception as exc:
        # #5015: bounded stage identifiers only, never identity values.
        print(_identity_bridge_failure_log_line("product_user"), flush=True)
        return _error(401, "canonical_session_required")
    try:
        bridged = await resolve_b54_session(identity, uid)
    except Exception as exc:
        print(_identity_bridge_failure_log_line("b54_session"), flush=True)
        return _error(401, "canonical_session_required")
    if (bridged is None
        or bridged.auth_session.subject.subject_id != payload["subject_id"]
        or not bridged.auth_session.tenant_id):
        print("claw_engine_bridge_mismatch", flush=True)
        return _error(401, "canonical_session_required")
    session = bridged.auth_session
    if run_query:
        # #6460 step 3 — the loop asks one question between steps: did the
        # owner stop this run? Only the owner's own run row answers, and the
        # read writes nothing.
        history_store = getattr(request.app.state, "history_store", None)
        reader = getattr(history_store, "get_claw_run", None)
        if not callable(reader):
            return _error(503, "oracle_mesh_unconfigured")
        try:
            run = await reader(uid, payload["run_id"])
        except Exception:
            return _error(503, "oracle_mesh_run_unavailable")
        if not isinstance(run, dict) or run.get("run_id") != payload["run_id"]:
            return _error(404, "oracle_mesh_run_unavailable")
        return _response({
            "ok": True,
            "run": {
                "run_id": run["run_id"],
                "state": run.get("status"),
                "updated_at": run.get("updated_at"),
            },
        })
    if status_query:
        history_store = getattr(request.app.state, "history_store", None)
        reader = getattr(history_store, "get_oracle_mesh_dispatch_for_owner", None)
        if not callable(reader):
            return _error(503, "oracle_mesh_unconfigured")
        try:
            dispatch = await reader(
                user_id=uid, dispatch_id=payload["dispatch_id"],
            )
        except Exception:
            return _error(503, "oracle_mesh_dispatch_unavailable")
        expected_kind = "command" if payload.get("mode") in ("result", "command_status") else "desktop"
        if (not isinstance(dispatch, dict)
            or dispatch.get("run_id") != payload["run_id"]
            or dispatch.get("kind") != expected_kind):
            return _error(404, "oracle_mesh_run_unavailable")
        state = dispatch.get("state")
        if payload["mode"] == "image":
            if state != "done" or not isinstance(dispatch.get("result_sha256"), str):
                return _error(409, "oracle_mesh_capture_not_ready")
            try:
                run = await history_store.get_claw_run(uid, payload["run_id"])
                conversation_id = validate_conversation_id(
                    (run or {}).get("conversation_id")
                )
                if not conversation_id:
                    return _error(404, "oracle_mesh_run_unavailable")
                message_id = result_message_id(
                    conversation_id=conversation_id,
                    command_id=dispatch["command_id"],
                    revision_ref=dispatch["revision_ref"],
                )
                stored = await history_store.read_oracle_mesh_original(
                    user_id=uid, dispatch_id=dispatch["dispatch_id"],
                    conversation_id=conversation_id, message_id=message_id,
                )
            except Exception:
                return _error(503, "oracle_mesh_original_unavailable")
            if stored is None:
                return _error(404, "oracle_mesh_original_unavailable")
            raw, digest = stored
            if (not isinstance(raw, bytes) or not raw.startswith(b"\xff\xd8\xff")
                or digest != dispatch["result_sha256"]):
                return _error(503, "oracle_mesh_original_unavailable")
            return Response(
                raw, media_type="image/jpeg",
                headers={**_NO_STORE, "X-Oracle-Mesh-Content-SHA256": digest},
            )
        if payload["mode"] == "result":
            if state != "done" or dispatch.get("kind") != "command":
                return _error(409, "oracle_mesh_result_not_ready")
            termination = dispatch.get("termination")
            exit_code = dispatch.get("exit_code")
            if termination not in (
                "exited", "no_exit_code", "output_too_large", "not_executed",
                "timed_out", "cancelled", "no_reply", "bad_reply",
            ):
                return _error(503, "oracle_mesh_original_unavailable")
            if exit_code is None:
                if termination not in (
                    "timed_out", "no_reply", "no_exit_code", "not_executed",
                    "output_too_large", "cancelled", "bad_reply",
                ):
                    return _error(503, "oracle_mesh_original_unavailable")
            elif isinstance(exit_code, bool) or not isinstance(exit_code, int):
                return _error(503, "oracle_mesh_original_unavailable")
            try:
                run = await history_store.get_claw_run(uid, payload["run_id"])
                conversation_id = validate_conversation_id(
                    (run or {}).get("conversation_id")
                )
                if not conversation_id:
                    return _error(404, "oracle_mesh_run_unavailable")
                message_id = result_message_id(
                    conversation_id=conversation_id,
                    command_id=dispatch["command_id"],
                    revision_ref=dispatch["revision_ref"],
                )
                stored = await history_store.read_oracle_mesh_original(
                    user_id=uid, dispatch_id=dispatch["dispatch_id"],
                    conversation_id=conversation_id, message_id=message_id,
                )
            except Exception:
                return _error(503, "oracle_mesh_original_unavailable")
            if stored is None:
                return _error(404, "oracle_mesh_original_unavailable")
            raw, digest = stored
            if (not isinstance(raw, bytes)
                or hashlib.sha256(raw).hexdigest() != digest
                or digest != dispatch.get("result_sha256")):
                return _error(503, "oracle_mesh_original_unavailable")
            public_output, output_error = await _engine_pc_public_output(
                history_store, payload=payload, uid=uid, dispatch=dispatch,
                output=raw.decode("utf-8", errors="replace"),
            )
            if output_error is not None:
                return output_error
            return _response({
                "ok": True,
                "dispatch": {
                    "dispatch_id": dispatch["dispatch_id"],
                    "run_id": payload["run_id"],
                    "kind": "command",
                    "state": "done",
                    "result_sha256": digest,
                    **public_output,
                    **({"content_sha256": digest, "content_bytes": len(raw)}
                       if "output_ref" in public_output else {}),
                    "termination": termination,
                    "exit_code": exit_code,
                },
            })
        if state not in {"pending", "received", "store_failed", "done", "failed"}:
            return _error(503, "oracle_mesh_dispatch_unavailable")
        return _response({
            "ok": True,
            "dispatch": {
                "dispatch_id": dispatch["dispatch_id"],
                "run_id": payload["run_id"],
                "kind": "command" if payload.get("mode") == "command_status" else "desktop",
                "state": state,
                "result_sha256": dispatch.get("result_sha256"),
                "termination": dispatch.get("termination"),
                "exit_code": dispatch.get("exit_code"),
            },
        })
    if command_dispatch:
        command_workspace = await _dispatch_workspace_id(request, uid, session)
        if not command_workspace:
            return _error(503, "oracle_mesh_workspace_unavailable")
        return await dispatch_oracle_mesh_command_intent(
            request, command=payload["command"],
            wire={"run_id": payload["run_id"], "device_id": payload["device_id"], "confirmed": True},
            trusted_owner=(session, uid, command_workspace),
        )
    desktop_op = payload["desktop_op"]
    # #7561: a loop step is held to the owner's own standard. Input runs only
    # inside a run the owner's sentence staged as a desktop task, and a typed
    # value passes the same exception and size checks as the owner's sentence.
    from .claw_desktop_intent import loop_step_refusal
    run_reader = getattr(getattr(request.app.state, "history_store", None), "get_claw_run", None)
    if not callable(run_reader):
        return _error(503, "oracle_mesh_unconfigured")
    try:
        owner_run = await run_reader(uid, payload["run_id"])
    except Exception:
        return _error(503, "oracle_mesh_run_unavailable")
    refusal = loop_step_refusal(owner_run, desktop_op, payload.get("desktop_text"))
    if refusal is not None:
        return _error(403, refusal)
    if "desktop_text" in payload:
        # #6460 step 3 — the model-driven loop types a value it chose from the
        # screen. The value goes to the one-shot store and the row names it only
        # by length, digest prefix and reference; the value itself is never
        # written into any dispatch row of this run.
        if desktop_op != "desktop:type" or not text_is_deliverable(payload["desktop_text"]):
            return _error(422, "oracle_mesh_desktop_op_invalid")
        text_ref = await deposit_typed_text(
            getattr(request.app.state, "queue_client", None),
            payload["desktop_text"],
        )
        if text_ref is None:
            return _error(503, "desktop_text_unavailable")
        desktop_op = type_marker_op(payload["desktop_text"], text_ref)
    return await dispatch_oracle_mesh_desktop_intent(
        request, desktop_op=desktop_op,
        wire={"run_id": payload["run_id"], "device_id": payload["device_id"], "confirmed": True},
        trusted_owner=(session, uid, session.tenant_id),
        tool_call_ref=payload.get("call_ref"),
    )


@chat_pc_dispatch_ttl
async def oracle_chat_engine_pc_drive_call(request: Request) -> JSONResponse:
    """Engine-only Chat product PC drive lane; browser cookies never act as proof.

    #5015 review: the b62 Chat product reaches the SAME shared Mesh command
    contract (same pinned command, ownership grant, executor channel,
    verification, pin/store and status/result vocabulary) under its own
    product identity (``b62``), user, workspace and staged run. No Claw
    product, run or authority is borrowed: the Control Plane resolves the
    current b62 session independently, the Chat lane stages its own
    ``chat_pcq_`` run row, and only command modes exist here (no desktop).
    """
    from .chat_pc_drive import CHAT_PC_DRIVE_COMMAND

    raw, proof_error = await _verify_engine_proof(request)
    if proof_error is not None or raw is None:
        return proof_error if proof_error is not None else _error(401, "claw_engine_proof_required")
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return _error(400, "claw_engine_desktop_invalid_body")
    status_query = isinstance(payload, dict) and payload.get("mode") in ("result", "command_status")
    command_dispatch = isinstance(payload, dict) and payload.get("mode") == "dispatch"
    expected_keys = (
        {"subject_id", "run_id", "dispatch_id", "mode"} if status_query
        else {"subject_id", "run_id", "device_id", "command", "mode"} if command_dispatch
        else set()
    )
    if (not isinstance(payload, dict)
        or not expected_keys
        or set(payload) != expected_keys
        or not all(
            isinstance(payload[k], str) and 0 < len(payload[k]) <= 512
            for k in ("subject_id", "run_id")
        )
        or (status_query and (not isinstance(payload["dispatch_id"], str)
            or not 0 < len(payload["dispatch_id"]) <= 128))
        or (command_dispatch and (
            payload.get("device_id") is not None and not isinstance(payload.get("device_id"), str)
            or not isinstance(payload.get("command"), str)
            or payload.get("command") != CHAT_PC_DRIVE_COMMAND
        ))):
        return _error(400, "claw_engine_desktop_invalid_body")
    # Reuse the file lane's product/connector identity boundary: verify the
    # B62 caller, then resolve the shared B54 connector session independently.
    # A B62 session identifies the Chat turn; it is not connector authority.
    uid, session, owner_error = await _engine_pc_files_owner(
        request, product="chat", subject_id=payload["subject_id"],
    )
    if owner_error is not None:
        return owner_error
    history_store = getattr(request.app.state, "history_store", None)
    if history_store is None:
        return _error(503, "oracle_mesh_unconfigured")
    if status_query:
        reader = getattr(history_store, "get_oracle_mesh_dispatch_for_owner", None)
        if not callable(reader):
            return _error(503, "oracle_mesh_unconfigured")
        try:
            dispatch = await reader(
                user_id=uid, dispatch_id=payload["dispatch_id"],
            )
        except Exception:
            return _error(503, "oracle_mesh_dispatch_unavailable")
        if (not isinstance(dispatch, dict)
            or dispatch.get("run_id") != payload["run_id"]
            or dispatch.get("kind") != "command"):
            return _error(404, "oracle_mesh_run_unavailable")
        state = dispatch.get("state")
        if payload["mode"] == "result":
            if state != "done" or dispatch.get("kind") != "command":
                return _error(409, "oracle_mesh_result_not_ready")
            termination = dispatch.get("termination")
            exit_code = dispatch.get("exit_code")
            if termination not in (
                "exited", "no_exit_code", "output_too_large", "not_executed",
                "timed_out", "cancelled", "no_reply", "bad_reply",
            ):
                return _error(503, "oracle_mesh_original_unavailable")
            if exit_code is None:
                if termination not in (
                    "timed_out", "no_reply", "no_exit_code", "not_executed",
                    "output_too_large", "cancelled", "bad_reply",
                ):
                    return _error(503, "oracle_mesh_original_unavailable")
            elif isinstance(exit_code, bool) or not isinstance(exit_code, int):
                return _error(503, "oracle_mesh_original_unavailable")
            try:
                run = await history_store.get_claw_run(uid, payload["run_id"])
                conversation_id = validate_conversation_id(
                    (run or {}).get("conversation_id")
                )
                if not conversation_id:
                    return _error(404, "oracle_mesh_run_unavailable")
                message_id = result_message_id(
                    conversation_id=conversation_id,
                    command_id=dispatch["command_id"],
                    revision_ref=dispatch["revision_ref"],
                )
                stored = await history_store.read_oracle_mesh_original(
                    user_id=uid, dispatch_id=dispatch["dispatch_id"],
                    conversation_id=conversation_id, message_id=message_id,
                )
            except Exception:
                return _error(503, "oracle_mesh_original_unavailable")
            if stored is None:
                return _error(404, "oracle_mesh_original_unavailable")
            content, digest = stored
            if (not isinstance(content, bytes)
                or hashlib.sha256(content).hexdigest() != digest
                or digest != dispatch.get("result_sha256")):
                return _error(503, "oracle_mesh_original_unavailable")
            public_output, output_error = await _engine_pc_public_output(
                history_store, payload=payload, uid=uid, dispatch=dispatch,
                output=content.decode("utf-8", errors="replace"),
            )
            if output_error is not None:
                return output_error
            return _response({
                "ok": True,
                "dispatch": {
                    "dispatch_id": dispatch["dispatch_id"],
                    "run_id": payload["run_id"],
                    "kind": "command",
                    "state": "done",
                    "result_sha256": digest,
                    **public_output,
                    **({"content_sha256": digest, "content_bytes": len(content)}
                       if "output_ref" in public_output else {}),
                    "termination": termination,
                    "exit_code": exit_code,
                },
            })
        if state not in {"pending", "received", "store_failed", "done", "failed"}:
            return _error(503, "oracle_mesh_dispatch_unavailable")
        return _response({
            "ok": True,
            "dispatch": {
                "dispatch_id": dispatch["dispatch_id"],
                "run_id": payload["run_id"],
                "kind": "command",
                "state": state,
                "result_sha256": dispatch.get("result_sha256"),
                "termination": dispatch.get("termination"),
                "exit_code": dispatch.get("exit_code"),
            },
        })
    command_workspace = await _dispatch_workspace_id(request, uid, session)
    if not command_workspace:
        return _error(503, "oracle_mesh_workspace_unavailable")
    try:
        store = getattr(request.app.state, "history_store", None)
        if await store.get_claw_run(uid, payload["run_id"]) is None:
            from .chat_pc_drive import promote_chat_pc_stream_run
            await promote_chat_pc_stream_run(
                request, uid=uid, run_id=payload["run_id"],
                device_id=payload["device_id"], action="pc_drive_query",
            )
    except Exception:
        return _error(503, "oracle_mesh_run_unavailable")
    return await dispatch_oracle_mesh_command_intent(
        request, command=payload["command"],
        wire={"run_id": payload["run_id"], "device_id": payload["device_id"], "confirmed": True},
        trusted_owner=(session, uid, command_workspace),
    )
