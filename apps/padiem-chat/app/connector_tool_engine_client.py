"""Chat -> Engine private ToolRuntime client for connector tools (#7088).

The same trusted pattern as the existing web-XLSX P01 client
(``web_xlsx_p01_engine_client``): fixed private endpoints, caller identity
from the pre-existing P01 caller surface, bounded body and response, no
retries, no browser-selected origin or tool. The tool identity comes only from
``chat_connector_tools.CONNECTOR_TOOL_BINDINGS`` (Core canonical ids); the
model's arguments travel as data and every authority decision — including
``202 paused`` user confirmation and single-use resume/cancel — stays
Engine-side.
"""

from __future__ import annotations

from datetime import datetime
import json
import re
from collections.abc import Mapping
from typing import Any

from padiem_ai_engine_client import ENGINE_INTERNAL_ORIGIN

from .chat_connector_tools import (
    CONNECTOR_TOOL_BINDINGS,
    GMAIL_REFERENCE_APP_ID,
    connector_tool_request,
    is_confirmation_connector_tool_name,
)
from .service_binding_response import (
    ServiceBindingResponseError,
    ServiceBindingResponseTooLarge,
    read_bounded_service_binding_body,
)

_ENDPOINT = "/internal/v1/tools/execute"
#: The fixed private paths under the public names the host composition allowlists.
TOOL_EXECUTE_ENDPOINT = _ENDPOINT
TOOL_RESUME_ENDPOINT = "/internal/v1/tools/resume"
TOOL_CANCEL_ENDPOINT = "/internal/v1/tools/cancel"
CONNECTOR_TOOL_ENDPOINTS = (
    TOOL_EXECUTE_ENDPOINT,
    TOOL_RESUME_ENDPOINT,
    TOOL_CANCEL_ENDPOINT,
)

_MAX_BODY_BYTES = 65_536
_MAX_RESPONSE_BYTES = 65_536
_CREDENTIAL_CHARS = re.compile(r"^[^\x00-\x1f\x7f]{1,512}$")
_CALLER_CHARS = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:@+-]{0,127}$")
_CONTINUATION_RE = re.compile(r"^cont_[A-Za-z0-9_-]{8,123}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_DECISION_KEYS = frozenset(
    {"decision_id", "pause_id", "outcome", "authority_ref", "evidence_ref", "decided_at"}
)
_ENGINE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RESUME_ERROR_MESSAGES: dict[str, str] = {
    "continuation_expired": "확인 가능한 시간이 지나 작업을 이어갈 수 없습니다.",
    "approval_decision_expired": "확인 가능한 시간이 지나 작업을 이어갈 수 없습니다.",
    "continuation_identity_mismatch": "이전 작업과 현재 확인 요청이 일치하지 않습니다.",
    "approval_decision_mismatch": "이전 작업과 현재 확인 요청이 일치하지 않습니다.",
    "continuation_not_found": "이 작업은 더 이상 이어갈 수 없습니다.",
    "continuation_already_consumed": "이미 처리된 확인 요청입니다.",
    "tool_auth_scope_missing": "Gmail 초안 권한이 연결되어 있지 않습니다. 연결을 다시 동의해 주세요.",
}


def _valid_aware_iso(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


class ConnectorToolEngineError(Exception):
    """A bounded refusal from the private Engine connector-tool path."""

    def __init__(self, code: str, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class CloudflareConnectorToolEngineClient:
    """Fixed private Engine ToolRuntime path over the existing caller surface."""

    def __init__(
        self, service_binding: Any, *,
        caller_id: str, credential: str, request_factory: Any,
    ) -> None:
        if service_binding is None or not callable(getattr(service_binding, "fetch", None)):
            raise ValueError("existing Engine Service Binding required")
        if not callable(request_factory):
            raise ValueError("native Request constructor required")
        if not isinstance(caller_id, str) or not _CALLER_CHARS.fullmatch(caller_id):
            raise ValueError("existing Engine caller identity required")
        if not isinstance(credential, str) or not _CREDENTIAL_CHARS.fullmatch(credential):
            raise ValueError("existing Engine credential required")
        self._binding = service_binding
        self._caller_id = caller_id
        self._credential = credential
        self._request_factory = request_factory

    async def _post_json(
        self, endpoint: str, data: Mapping[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        if endpoint not in CONNECTOR_TOOL_ENDPOINTS:
            raise ConnectorToolEngineError(
                "connector_tool_unsupported",
                "요청한 커넥터 도구 경로를 사용할 수 없습니다.",
                status_code=422,
            )
        try:
            encoded = json.dumps(dict(data), ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ConnectorToolEngineError(
                "connector_tool_arguments_invalid",
                "커넥터 도구 요청 형식이 올바르지 않습니다.",
                status_code=422,
            ) from exc
        if len(encoded.encode("utf-8")) > _MAX_BODY_BYTES:
            raise ConnectorToolEngineError(
                "connector_tool_arguments_invalid",
                "커넥터 도구 요청이 너무 큽니다.",
                status_code=422,
            )
        req = self._request_factory(
            f"{ENGINE_INTERNAL_ORIGIN}{endpoint}",
            method="POST",
            headers={
                "content-type": "application/json",
                "accept": "application/json",
                "x-padiem-engine-caller": self._caller_id,
                "x-padiem-engine-credential": self._credential,
            },
            body=encoded,
        )
        try:
            response = await self._binding.fetch(req.js_object)
            raw = await read_bounded_service_binding_body(
                response, max_bytes=_MAX_RESPONSE_BYTES,
            )
        except (ServiceBindingResponseError, ServiceBindingResponseTooLarge,
                TypeError, ValueError) as exc:
            raise ConnectorToolEngineError(
                "connector_tool_unavailable",
                "커넥터 도구 실행에 연결할 수 없습니다.",
            ) from exc
        try:
            status = int(response.status)
            body = json.loads(raw.decode("utf-8"))
        except (TypeError, ValueError, UnicodeDecodeError, AttributeError) as exc:
            raise ConnectorToolEngineError(
                "connector_tool_unavailable",
                "커넥터 도구 응답을 확인할 수 없습니다.",
            ) from exc
        if not isinstance(body, dict):
            raise ConnectorToolEngineError(
                "connector_tool_unavailable",
                "커넥터 도구 응답을 확인할 수 없습니다.",
            )
        return status, body

    async def execute(self, *, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Execute one declared connector tool; return completed or paused tool body."""

        try:
            data = connector_tool_request(tool_name, arguments)
        except ValueError as exc:
            raise ConnectorToolEngineError(
                "connector_tool_unsupported",
                "요청한 커넥터 도구를 실행할 수 없습니다.",
                status_code=422,
            ) from exc
        status, body = await self._post_json(TOOL_EXECUTE_ENDPOINT, data)
        tool = body.get("tool")
        if (
            status == 200
            and body.get("ok") is True
            and isinstance(tool, dict)
            and tool.get("status") == "completed"
        ):
            return tool
        if (
            status == 202
            and body.get("ok") is True
            and isinstance(tool, dict)
            and tool.get("status") == "paused"
            and is_confirmation_connector_tool_name(tool_name)
        ):
            expected_canonical = CONNECTOR_TOOL_BINDINGS[tool_name][0]
            ref = tool.get("continuation_ref")
            pause = tool.get("approval_pause")
            if (
                tool.get("canonical_tool_id") != expected_canonical
                or not isinstance(ref, str)
                or not _CONTINUATION_RE.fullmatch(ref)
                or not isinstance(pause, Mapping)
                or pause.get("status") != "paused"
                or pause.get("requirement") != "user_confirmation"
                or not isinstance(pause.get("continuation_id"), str)
                or not _SAFE_ID_RE.fullmatch(pause["continuation_id"])
                or not _valid_aware_iso(pause.get("expires_at"))
            ):
                raise ConnectorToolEngineError(
                    "connector_tool_unavailable",
                    "사용자 확인 대기 응답 형식을 확인할 수 없습니다.",
                )
            return tool
        raise ConnectorToolEngineError(
            "connector_tool_refused",
            "커넥터 도구 실행이 거부되었습니다.",
        )

    async def resume(
        self,
        *,
        app_id: str,
        continuation_ref: str,
        decision: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Resume one paused confirmation-gated connector tool via /internal/v1/tools/resume."""

        if (
            app_id != GMAIL_REFERENCE_APP_ID
            or not isinstance(continuation_ref, str)
            or not _CONTINUATION_RE.fullmatch(continuation_ref)
            or not isinstance(decision, Mapping)
            or set(decision) != _DECISION_KEYS
            or decision.get("outcome") not in ("approved", "denied")
            or not isinstance(decision.get("pause_id"), str)
            or not _SAFE_ID_RE.fullmatch(decision["pause_id"])
            or not _valid_aware_iso(decision.get("decided_at"))
        ):
            raise ConnectorToolEngineError(
                "connector_tool_arguments_invalid",
                "확인 결정 형식이 올바르지 않습니다.",
                status_code=422,
            )
        status, body = await self._post_json(
            TOOL_RESUME_ENDPOINT,
            {
                "app_id": app_id,
                "continuation_ref": continuation_ref,
                "decision": dict(decision),
            },
        )
        if (
            decision["outcome"] == "denied"
            and status == 409
            and body.get("ok") is False
            and isinstance(body.get("error"), Mapping)
            and body["error"].get("code") == "approval_denied"
        ):
            return {"status": "denied"}
        tool = body.get("tool")
        if (
            decision["outcome"] == "approved"
            and status == 200
            and body.get("ok") is True
            and isinstance(tool, Mapping)
            and tool.get("status") == "completed"
            and tool.get("continuation_ref") == continuation_ref
            and isinstance(tool.get("output"), Mapping)
        ):
            return {"status": "completed", "tool": dict(tool)}
        raw_error = body.get("error")
        raw_code = raw_error.get("code") if isinstance(raw_error, Mapping) else None
        code = (
            raw_code
            if isinstance(raw_code, str) and _ENGINE_CODE_RE.fullmatch(raw_code)
            else "connector_tool_refused"
        )
        mapped_status = status if 400 <= status <= 599 else 502
        raise ConnectorToolEngineError(
            code,
            _RESUME_ERROR_MESSAGES.get(code, "확인 후 커넥터 도구 실행이 거부되었습니다."),
            status_code=mapped_status,
        )

    async def cancel(
        self,
        *,
        app_id: str,
        continuation_ref: str,
        reason: str = "user_cancelled",
    ) -> dict[str, Any]:
        """Cancel one paused confirmation-gated connector tool via /internal/v1/tools/cancel."""

        if (
            app_id != GMAIL_REFERENCE_APP_ID
            or not isinstance(continuation_ref, str)
            or not _CONTINUATION_RE.fullmatch(continuation_ref)
            or not isinstance(reason, str)
            or not 1 <= len(reason) <= 64
        ):
            raise ConnectorToolEngineError(
                "connector_tool_arguments_invalid",
                "취소 요청 형식이 올바르지 않습니다.",
                status_code=422,
            )
        status, body = await self._post_json(
            TOOL_CANCEL_ENDPOINT,
            {
                "app_id": app_id,
                "continuation_ref": continuation_ref,
                "reason": reason,
            },
        )
        if status == 200 and body.get("ok") is True and body.get("status") == "cancelled":
            return {"status": "cancelled", "continuation_ref": continuation_ref}
        raw_error = body.get("error")
        raw_code = raw_error.get("code") if isinstance(raw_error, Mapping) else None
        code = (
            raw_code
            if isinstance(raw_code, str) and _ENGINE_CODE_RE.fullmatch(raw_code)
            else "connector_tool_refused"
        )
        mapped_status = status if 400 <= status <= 599 else 502
        raise ConnectorToolEngineError(
            code,
            "취소 요청을 처리하지 못했습니다.",
            status_code=mapped_status,
        )
