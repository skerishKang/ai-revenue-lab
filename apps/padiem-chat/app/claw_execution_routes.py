"""Authenticated web route for real B54 Claw P01 execution (#2215).

The existing preview route remains deterministic and provider-free.  This
explicit execute route never silently falls back to preview.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
import uuid

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from kagent.manual_intake import (
    ContractError,
    ManualIntakeAction,
    ManualIntakeChannel,
    ManualIntakeRequest,
)
from kagent.manual_intake_p01 import ManualIntakeP01Error
from kagent.p01_adapter import P01AdapterError

from .auth_routes import auth_ready, current_user_id


MAX_EXECUTION_BODY_BYTES = 64 * 1024
MAX_CONTENT_CHARS = 4_000
MAX_SENDER_CHARS = 120
CLAW_EXECUTION_TIMEOUT_SECONDS = 25.0

_ALLOWED_KEYS = frozenset({"content", "channel", "action", "sender_hint"})
_ACTION_MAP: dict[str, ManualIntakeAction] = {
    "quote": ManualIntakeAction.QUOTE_DRAFT,
    "order": ManualIntakeAction.ORDER_DRAFT,
    "reply": ManualIntakeAction.REPLY_DRAFT,
    "summary": ManualIntakeAction.SUMMARIZE_REQUEST,
}
_CHANNEL_MAP: dict[str, ManualIntakeChannel] = {
    "kakao": ManualIntakeChannel.KAKAO,
    "sms": ManualIntakeChannel.SMS,
    "email": ManualIntakeChannel.EMAIL,
    "telegram": ManualIntakeChannel.TELEGRAM,
    "discord": ManualIntakeChannel.DISCORD,
    "other": ManualIntakeChannel.OTHER,
}
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class ClawExecutionRouteError(ValueError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
    )


def _bridge(request: Request) -> Any | None:
    bridge = getattr(request.app.state, "claw_execution_bridge", None)
    return bridge if callable(getattr(bridge, "execute", None)) else None


async def _parse_request(request: Request) -> ManualIntakeRequest:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise ClawExecutionRouteError(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")
    raw_body = await request.body()
    if not raw_body:
        raise ClawExecutionRouteError(400, "empty_request_body", "요청 본문이 비어 있습니다.")
    if len(raw_body) > MAX_EXECUTION_BODY_BYTES:
        raise ClawExecutionRouteError(413, "request_too_large", "요청 크기가 너무 큽니다.")
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ClawExecutionRouteError(400, "invalid_json", "유효한 JSON 형식이 아닙니다.") from None
    if not isinstance(data, dict) or not set(data) <= _ALLOWED_KEYS:
        raise ClawExecutionRouteError(
            400,
            "invalid_payload",
            "Claw 실행 요청에는 content, channel, action, sender_hint만 허용됩니다.",
        )

    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ClawExecutionRouteError(400, "invalid_content", "요청 원문을 입력해 주세요.")
    content_clean = content.strip()
    if len(content_clean) > MAX_CONTENT_CHARS:
        raise ClawExecutionRouteError(
            400,
            "content_too_long",
            f"요청 원문은 {MAX_CONTENT_CHARS}자 이하로 입력해 주세요.",
        )

    raw_channel = str(data.get("channel") or "other").strip().lower()
    channel = _CHANNEL_MAP.get(raw_channel)
    if channel is None:
        raise ClawExecutionRouteError(400, "invalid_channel", "지원되지 않는 채널입니다.")

    raw_action = str(data.get("action") or "quote").strip().lower()
    action = _ACTION_MAP.get(raw_action)
    if action is None:
        raise ClawExecutionRouteError(400, "invalid_action", "지원되지 않는 작업입니다.")

    sender_hint: str | None = None
    if "sender_hint" in data and data["sender_hint"] is not None:
        raw_sender = data["sender_hint"]
        if not isinstance(raw_sender, str):
            raise ClawExecutionRouteError(400, "invalid_sender_hint", "발신자 힌트 형식이 올바르지 않습니다.")
        sender = raw_sender.strip()
        if len(sender) > MAX_SENDER_CHARS:
            raise ClawExecutionRouteError(
                400,
                "sender_hint_too_long",
                f"발신자 힌트는 {MAX_SENDER_CHARS}자 이하로 입력해 주세요.",
            )
        sender_hint = sender or None

    try:
        return ManualIntakeRequest(
            request_id=f"exec_{uuid.uuid4().hex[:12]}",
            workspace_id="web_ephemeral_workspace",
            channel=channel,
            action=action,
            raw_content=content_clean,
            sender_hint=sender_hint,
            requested_format="md",
        )
    except ContractError:
        raise ClawExecutionRouteError(400, "contract_violation", "Claw 실행 요청이 허용 범위를 벗어났습니다.") from None


async def claw_manual_intake_execute(request: Request) -> JSONResponse:
    if not auth_ready(request) or current_user_id(request) is None:
        return _error(401, "unauthorized", "실제 Claw 실행은 로그인 후 사용할 수 있습니다.")
    bridge = _bridge(request)
    if bridge is None:
        return _error(503, "claw_execution_unavailable", "Claw AI 실행을 현재 사용할 수 없습니다.")

    try:
        intake = await _parse_request(request)
        result = await asyncio.wait_for(
            bridge.execute(intake),
            timeout=CLAW_EXECUTION_TIMEOUT_SECONDS,
        )
    except ClawExecutionRouteError as exc:
        return _error(exc.status_code, exc.code, exc.message)
    except asyncio.TimeoutError:
        return _error(504, "claw_execution_timeout", "Claw AI 실행 시간이 초과되었습니다. 다시 시도해 주세요.")
    except (ManualIntakeP01Error, P01AdapterError):
        return _error(503, "claw_execution_failed", "Claw AI 실행을 안전하게 완료하지 못했습니다.")
    except Exception:
        return _error(503, "claw_execution_failed", "Claw AI 실행을 안전하게 완료하지 못했습니다.")

    if not isinstance(result, dict) or not isinstance(result.get("answer"), str) or not result["answer"].strip():
        return _error(503, "claw_execution_invalid_result", "Claw AI 결과를 안전하게 확인하지 못했습니다.")

    return JSONResponse(
        {"ok": True, "execution": result},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


def install_claw_execution_route(app: Any, bridge: Any | None) -> None:
    """Install ahead of the static catch-all only in Worker composition."""
    app.state.claw_execution_bridge = bridge
    app.router.routes.insert(
        0,
        Route(
            "/api/claw/manual-intake/execute",
            claw_manual_intake_execute,
            methods=["POST"],
        ),
    )


__all__ = [
    "CLAW_EXECUTION_TIMEOUT_SECONDS",
    "claw_manual_intake_execute",
    "install_claw_execution_route",
]
