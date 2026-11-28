"""B54 Claw general: validated user message, attachment and direct custom intake (#7809 7/13).

The definitions below were relocated verbatim. The public entry module
re-exports every name, preserving error and branch behavior.
"""

from __future__ import annotations

import json
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from kagent.p01_run_flow import create_claw_run

from .auth_routes import auth_ready, current_user_id
from .binary_attachment_frame import decode_binary_attachment_frame
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .byok_client import CustomProviderError, complete_owner_custom
from .byok_credentials import CustomProviderSelectionError
from .claw_attachment_context import (
    CLAW_IMAGE_ATTACHMENT_UNSUPPORTED,
    AttachmentValidationError,
    parse_claw_turn_attachments_async,
)
from .claw_general_contract import (
    CLAW_LIVE_REQUEST_HEADER, CLAW_LIVE_REQUEST_MARKER,
    MAX_CLAW_GENERAL_BODY_BYTES,
)
from .claw_general_conversation import _owner_claw_context, _record_completed_claw_result
from .claw_general_pc_intent import (
    _requested_desktop_task,
    _requested_local_command,
    _requested_local_desktop,
    _requested_local_txt_path,
    _requested_natural_pc_files,
    _requested_natural_pc_query,
    _requested_read_only_screen_view,
)
from .claw_general_response import _claw_general_sse
from .claw_routes import _error, _resolve_intake_session_reference
from .file_lane import file_resolver
from .history import HistoryContextIncomplete
from .request_contract import BrowserRequestError, parse_custom_selection


_CLAW_GENERAL_ROLES = frozenset({"user", "assistant"})


def _claw_general_user_text(data: dict[str, Any]) -> tuple[str | None, JSONResponse | None]:
    """Validate shared chat messages and preserve latest user text verbatim.

    P01 model-only Claw receives the latest user turn, not the browser-provided
    previous turns. Malformed shapes fail before quota or provider dispatch.
    """
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        return None, _error(400, "invalid_messages", "메시지를 입력해 주세요.")
    last_user: str | None = None
    for item in messages:
        if not isinstance(item, dict):
            return None, _error(400, "invalid_messages", "메시지 형식이 올바르지 않습니다.")
        role = item.get("role")
        content = item.get("content")
        if role not in _CLAW_GENERAL_ROLES or not isinstance(content, str):
            return None, _error(400, "invalid_messages", "메시지 형식이 올바르지 않습니다.")
        if role == "user":
            last_user = content
    text = (last_user or "").strip()
    if not text:
        return None, _error(400, "invalid_messages", "메시지를 입력해 주세요.")
    return text, None


async def _claw_custom_direct(
    request: Request,
    *,
    uid: str,
    custom: Any,
    data: dict[str, Any],
    user_text: str,
) -> JSONResponse | Response:
    """One owner-key text turn without Engine, B14, quota or tool dispatch."""
    conversation_id, conversation_error = await _resolve_intake_session_reference(
        request, data,
    )
    if conversation_error is not None:
        return conversation_error
    try:
        model_user_text = await _owner_claw_context(request, conversation_id, user_text)
    except HistoryContextIncomplete:
        return _error(
            409,
            "conversation_context_incomplete",
            "이전 대화 원문을 복원할 수 없습니다. 새 대화를 시작하거나 원문을 다시 입력해 주세요.",
        )
    except Exception:
        return _error(
            503,
            "conversation_authority_unavailable",
            "대화 문맥을 안전하게 확인할 수 없습니다.",
        )
    try:
        result = await complete_owner_custom(
            request.app.state,
            uid=uid,
            selection=custom,
            messages=[{"role": "user", "content": model_user_text}],
            conversation_id=conversation_id,
            raw_ip=request.headers.get("cf-connecting-ip"),
        )
    except CustomProviderSelectionError as exc:
        return _error(422, "custom_provider_unsupported", str(exc))
    except CustomProviderError as exc:
        return _error(exc.status_code, exc.code, exc.user_message)
    answer = result.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return _error(
            502,
            "malformed_custom_provider_response",
            "PADIEM Custom 공급사 응답 형식을 확인할 수 없습니다. 다시 시도해 주세요.",
        )
    run = create_claw_run("padiem-chat", user_text, model_only_text=True)
    saved_conversation_id = await _record_completed_claw_result(
        request,
        run_id=run.run_id,
        conversation_id=conversation_id,
        user_text=user_text,
        answer=answer,
        authorized_workspace_id=None,
    )
    return _claw_general_sse(
        answer, None, conversation_id=saved_conversation_id or conversation_id,
    )


async def _claw_general_intake(request: Request) -> tuple[JSONResponse | Response | None, dict[str, object] | None]:
    """입력 검증·권한 구간: 로그인부터 첨부 충돌까지, 분기 진입 전까지."""
    if getattr(getattr(request.app.state, "settings", None), "runtime_mode", None) != "mock":
        uid = current_user_id(request) if auth_ready(request) else None
        if uid is None:
            return _error(401, "login_required", "Claw를 사용하려면 로그인이 필요합니다."), None
    turn_started = time.perf_counter()
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    # #2505: an attached binary document travels in the same frame the Chat lane
    # already accepts, so the Claw lane reads it with the same decoder.
    binary_frame = content_type == "application/octet-stream"
    if content_type not in ("application/json", "application/octet-stream"):
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다."), None

    try:
        raw_body = await read_bounded_request_body(
            request,
            max_bytes=MAX_CLAW_GENERAL_BODY_BYTES,
        )
    except RequestBodyTooLarge:
        return _error(413, "request_too_large", "요청 크기가 너무 큽니다."), None
    if not raw_body:
        return _error(400, "empty_request_body", "요청 본문이 비어 있습니다."), None

    try:
        data = (
            decode_binary_attachment_frame(raw_body)
            if binary_frame else json.loads(raw_body.decode("utf-8"))
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다."), None
    except ValueError:
        return _error(400, "invalid_attachment_frame", "첨부 파일 요청 형식이 올바르지 않습니다."), None

    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다."), None

    user_text, text_error = _claw_general_user_text(data)
    if text_error is not None:
        return text_error, None

    # #2505: an attached file is read with the SAME Chat attachment contract, and
    # a document becomes the same untrusted reference context Chat builds. It
    # travels on the existing `additional_system_context` seam below, so the
    # Claw lane gains no second parser, storage row or Engine argument. Both
    # refusals happen before quota, first-turn claim, Engine dispatch and any
    # provider call.
    try:
        document_context, image_attachments = await parse_claw_turn_attachments_async(
            data.get("attachments"), file_resolver=file_resolver(request)
        )
    except AttachmentValidationError as exc:
        return _error(422, "invalid_attachment", str(exc)), None
    if image_attachments:
        return _error(
            422, "claw_image_attachment_unsupported",
            CLAW_IMAGE_ATTACHMENT_UNSUPPORTED,
        ), None
    # A document is model reference data for the answer lane. A lane that runs a
    # PC tool, a desktop op or the owner's direct provider never reads it, so a
    # mixed request is refused instead of silently dropping the file.
    attachment_conflict = (
        _error(
            422, "attachment_lane_unsupported",
            "첨부한 문서는 일반 AI 답변 요청에만 사용할 수 있습니다. 문서 없이 다시 요청해 주세요.",
        )
        if document_context is not None else None
    )
    return None, {
        "turn_started": turn_started,
        "data": data,
        "user_text": user_text,
        "document_context": document_context,
        "attachment_conflict": attachment_conflict,
    }


async def _claw_general_session_custom(request: Request, data: dict, user_text: str, document_context: object, attachment_conflict: object) -> tuple[JSONResponse | Response | None, dict[str, object]]:
    """세션 소유자 턴·Custom 구간(PC 밖)."""
    from .chat_pc_session import handle_owner_turn, claw_response
    session_response = await handle_owner_turn(request, user_text=user_text,
        conversation_id=data.get("conversation_id"), selected_device=data.get("device_id"),
        owner_turn=data["messages"][-1].get("role") == "user",
        has_attachments=bool(document_context is not None or "custom" in data))
    if session_response is not None:
        return claw_response(session_response), None

    # PADIEM Custom is a direct text completion: it cannot drive a PC tool,
    # desktop op or local file lane. When custom is present it takes precedence;
    # any accompanying tier is ignored (the BYOK exception to grade-only UI).
    custom = None
    if "custom" in data:
        try:
            custom = parse_custom_selection(data.get("custom"))
        except BrowserRequestError as exc:
            return _error(422, "custom_provider_invalid", str(exc)), None
        if (
            request.headers.get(CLAW_LIVE_REQUEST_HEADER, "").strip()
            == CLAW_LIVE_REQUEST_MARKER
        ):
            return _error(
                422,
                "custom_live_unsupported",
                "PADIEM Custom은 Claw 실시간 실행 스트림과 함께 사용할 수 없습니다.",
            ), None
        if (
            _requested_local_desktop(user_text)[0]
            or _requested_read_only_screen_view(user_text)
            or _requested_desktop_task(user_text)
            or _requested_local_command(user_text)[0]
            or _requested_natural_pc_files(user_text)
            or _requested_natural_pc_query(user_text)[0]
            or _requested_local_txt_path(user_text)[0]
        ):
            return _error(
                422,
                "custom_tool_unsupported",
                "PADIEM Custom은 현재 PC 실행·파일 도구 요청에 사용할 수 없습니다.",
            ), None
        if attachment_conflict is not None:
            # Same contract as the Chat lane: PADIEM Custom is a text-only
            # direct completion and never mixes with an attachment.
            return _error(422, "attachment_lane_unsupported",
                          "PADIEM Custom은 현재 텍스트 대화만 지원합니다."), None
        uid = current_user_id(request) if auth_ready(request) else None
        if not isinstance(uid, str) or not uid:
            return _error(401, "unauthorized", "로그인이 필요합니다."), None
        return await _claw_custom_direct(
            request, uid=uid, custom=custom, data=data, user_text=user_text,
        ), None
    return None, {}
