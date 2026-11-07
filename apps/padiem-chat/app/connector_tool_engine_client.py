"""Chat -> Engine private ToolRuntime client for the connector READ tools.

The same trusted pattern as the existing web-XLSX P01 client
(``web_xlsx_p01_engine_client``): one fixed private endpoint, caller identity
from the pre-existing P01 caller surface, bounded body and response, no
retries, no browser-selected origin or tool. The tool identity comes only from
``chat_connector_tools.CONNECTOR_TOOL_BINDINGS`` (Core canonical ids); the
model's arguments travel as data and every authority decision stays
Engine-side.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from padiem_ai_engine_client import ENGINE_INTERNAL_ORIGIN

from .chat_connector_tools import connector_tool_request
from .service_binding_response import (
    ServiceBindingResponseError,
    ServiceBindingResponseTooLarge,
    read_bounded_service_binding_body,
)

_ENDPOINT = "/internal/v1/tools/execute"
#: The same private path under the public name the host composition allowlists.
TOOL_EXECUTE_ENDPOINT = _ENDPOINT
_MAX_BODY_BYTES = 8192
_MAX_RESPONSE_BYTES = 65_536
_CREDENTIAL_CHARS = re.compile(r"^[^\x00-\x1f\x7f]{1,512}$")
_CALLER_CHARS = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:@+-]{0,127}$")


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

    async def execute(self, *, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Execute one declared connector READ tool; return the Engine tool body.

        The payload is closed: app/agent/tool ids from the bindings table, the
        model's JSON arguments as data. The Engine owns every authority
        decision — an undeclared tool, an unknown id or a refused grant fails
        closed here without a retry.
        """

        try:
            data = connector_tool_request(tool_name, arguments)
        except ValueError as exc:
            raise ConnectorToolEngineError(
                "connector_tool_unsupported",
                "요청한 커넥터 도구를 실행할 수 없습니다.",
                status_code=422,
            ) from exc
        try:
            encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
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
            f"{ENGINE_INTERNAL_ORIGIN}{_ENDPOINT}",
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
        tool = body.get("tool") if isinstance(body, dict) else None
        if (
            status != 200
            or not isinstance(body, dict)
            or body.get("ok") is not True
            or not isinstance(tool, dict)
            or tool.get("status") != "completed"
        ):
            # The Engine's own refusal is the authority answer; it is never
            # retried and its raw text never reaches the product response.
            raise ConnectorToolEngineError(
                "connector_tool_refused",
                "커넥터 도구 실행이 거부되었습니다.",
            )
        return tool
