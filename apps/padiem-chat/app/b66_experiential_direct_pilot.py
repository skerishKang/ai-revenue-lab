"""B66-only Experiential Qwen3.8 Flash Next Uncensored direct experiment.

B14 remains the read-only registered-model/owner authority. Only the already
authorized exact Experiential model bypasses its *completion executor*; Chat and Claw
remain untouched. Credential and URL cannot be supplied by the browser.
"""
from __future__ import annotations

import inspect
import json
from typing import Any

import httpx

from .b14_client import ChatRuntimeError
from .b66_registered_model_boundary import (
    B14AuthorizedModelRoute,
    B66ModelRouteError,
    B66QuoteTaskRequirements,
)

EXPERIENTIAL_B66_MODEL_ID = "experiential/qwen3.8-flash-next-uncensored"
_EXPERIENTIAL_UPSTREAM_MODEL = "qwen3.8-flash-next-uncensored"
_EXPERIENTIAL_URL = "https://api.experientiallabs.ai/v1/chat/completions"
_MAX_RESPONSE_BYTES = 1024 * 1024


class B66ExperientialPilotExecutor:
    """Experiential-only delegation with explicit zero-fallback semantics."""

    def __init__(
        self,
        *,
        original_executor: Any,
        credential_binding: Any,
        transport: httpx.AsyncBaseTransport,
    ) -> None:
        self._original = original_executor
        self._credential = credential_binding
        self._transport = transport

    @property
    def supports_native_parameters(self) -> bool:
        return bool(getattr(self._original, "supports_native_parameters", False))

    def ensure_runtime_available(self) -> None:
        # Preserve existing B66 production/live and B14 registry admission.
        self._original.ensure_runtime_available()

    async def _key(self) -> str:
        getter = getattr(self._credential, "get", None)
        if not callable(getter):
            raise ChatRuntimeError(503, "upstream_binding_unavailable", "견적 AI 공급사 연결을 확인할 수 없습니다.")
        try:
            result = getter()
            if not inspect.isawaitable(result):
                raise TypeError("not an async secret capability")
            key = await result
        except Exception:
            raise ChatRuntimeError(503, "upstream_binding_unavailable", "견적 AI 공급사 연결을 확인할 수 없습니다.") from None
        if not isinstance(key, str) or not key.strip():
            raise ChatRuntimeError(503, "upstream_binding_unavailable", "견적 AI 공급사 연결을 확인할 수 없습니다.")
        return key.strip()

    async def execute_quote_text(
        self,
        *,
        route: B14AuthorizedModelRoute,
        messages: list[dict[str, str]],
        additional_system_context: str | None,
        requirements: B66QuoteTaskRequirements,
        model_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if route.model_id != EXPERIENTIAL_B66_MODEL_ID:
            # Every other provider/model retains the exact original B14 route.
            return await self._original.execute_quote_text(
                route=route,
                messages=messages,
                additional_system_context=additional_system_context,
                requirements=requirements,
                model_parameters=model_parameters,
            )
        if (
            requirements.selected_model_id != EXPERIENTIAL_B66_MODEL_ID
            or requirements.max_attempts != 1
            or requirements.max_retries != 0
            or requirements.allow_external_fallback is not False
            or route.route_id != EXPERIENTIAL_B66_MODEL_ID
            or route.registered is not True
            or route.enabled is not True
            or route.authorized is not True
            or route.credential_ready is not True
            or "chat" not in route.capabilities
            or len(messages) != 1
            or messages[0].get("role") != "user"
            or not isinstance(messages[0].get("content"), str)
            or model_parameters is not None
        ):
            raise B66ModelRouteError("model_identity_invalid")
        key = await self._key()
        payload: dict[str, Any] = {
            "model": _EXPERIENTIAL_UPSTREAM_MODEL,
            "messages": [
                *([{"role": "system", "content": additional_system_context}]
                  if additional_system_context else []),
                {"role": "user", "content": messages[0]["content"]},
            ],
            "stream": False,
        }
        # No client-side rate/size/token ceilings beyond the fixed memory guard.
        # The provider alone decides its maximum input and output sizes.
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(75.0),
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "POST",
                    _EXPERIENTIAL_URL,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                ) as response:
                    status = response.status_code
                    if status != 200:
                        if status in (401, 403):
                            raise ChatRuntimeError(502, "provider_auth_error", "AI 공급사 인증에 실패했습니다.")
                        if status == 429:
                            raise ChatRuntimeError(502, "upstream_busy", "AI 공급사의 요청 제한에 도달했습니다.")
                        if status >= 500:
                            raise ChatRuntimeError(502, "provider_server_error", "AI 공급사 서버 오류입니다.")
                        raise ChatRuntimeError(502, "provider_route_error", "AI 공급사 요청이 거부됐습니다.")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > _MAX_RESPONSE_BYTES:
                            raise ChatRuntimeError(502, "upstream_response_too_large", "AI 공급사 응답이 너무 큽니다.")
                        chunks.append(chunk)
        except ChatRuntimeError:
            raise
        except httpx.TimeoutException:
            raise ChatRuntimeError(504, "upstream_timeout", "AI 공급사의 응답 시간이 초과됐습니다.") from None
        except httpx.RequestError:
            raise ChatRuntimeError(502, "upstream_unavailable", "AI 공급사에 연결할 수 없습니다.") from None
        try:
            data = json.loads(b"".join(chunks))
            choice = data["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty non-text answer")
        except (ValueError, KeyError, IndexError, TypeError):
            raise ChatRuntimeError(502, "malformed_upstream", "AI 공급사 응답 형식이 올바르지 않습니다.") from None
        return {
            "answer": content,
            "route": {"mode": "manual", "model": EXPERIENTIAL_B66_MODEL_ID},
        }
