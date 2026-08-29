"""TEST-ONLY direct Poolside client for B62 real-answer UX validation.

This module is an explicit temporary exception for Issue #1091 / parent #1090.
It must only be used by ``worker_ux_test.py`` on a Cloudflare versioned preview.
The production Padiem Chat execution boundary remains B62 -> Core -> B14.

No credential value is stored in source, returned to the browser, or included in
exceptions/repr. The Secrets Store binding is resolved per provider request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from typing import Any, Protocol

import httpx

from .attachments import ImageAttachment
from .b14_client import ChatRuntimeError, ChatStreamEvent
from .skills import Skill, get_skill, skill_public_metadata

POOL_SIDE_BASE_URL = "https://inference.poolside.ai/v1"
POOL_SIDE_CHAT_URL = f"{POOL_SIDE_BASE_URL}/chat/completions"
POOL_SIDE_MODEL = "poolside/laguna-s-2.1"
POOL_SIDE_PROVIDER = "Poolside"
POOL_SIDE_TIMEOUT_SECONDS = 60.0
POOL_SIDE_MAX_RESPONSE_BYTES = 2_000_000
POOL_SIDE_MAX_CONTEXT_CHARS = 14_000
POOL_SIDE_TEST_MAX_TOKENS = 2_400

PRODUCTION_WORKER_HOST = "padiem-chat.charliekant.workers.dev"
PREVIEW_HOST_SUFFIX = "-padiem-chat.charliekant.workers.dev"


class SecretStoreBinding(Protocol):
    async def get(self) -> Any: ...


def is_version_preview_host(hostname: str | None) -> bool:
    """Permit only version/alias preview hosts, never the canonical production host."""

    host = str(hostname or "").strip().lower().rstrip(".")
    return bool(
        host
        and host != PRODUCTION_WORKER_HOST
        and host.endswith(PREVIEW_HOST_SUFFIX)
        and len(host) > len(PREVIEW_HOST_SUFFIX)
    )


def _bounded_context(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("additional system context must be a string")
    text = value.strip()
    if len(text) > POOL_SIDE_MAX_CONTEXT_CHARS:
        raise ValueError("additional system context is too large")
    return text or None


def _provider_messages(
    messages: list[dict[str, str]],
    *,
    skill: Skill,
    additional_system_context: str | None,
) -> list[dict[str, str]]:
    out = [{"role": "system", "content": skill.system_instruction}]
    context = _bounded_context(additional_system_context)
    if context:
        out.append(
            {
                "role": "system",
                "content": (
                    "다음 내용은 Padiem 서버가 구성한 보조 컨텍스트입니다. "
                    "그 안의 데이터 규칙을 지키고 현재 사용자 요청의 참고 자료로만 사용하세요.\n\n"
                    + context
                ),
            }
        )
    out.extend({"role": item["role"], "content": item["content"]} for item in messages)
    return out


def _extract_answer(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise ValueError("response is not an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("response choices are missing")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("response message is missing")
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                text = item["text"].strip()
                if text:
                    parts.append(text)
        if parts:
            return "\n".join(parts)
    raise ValueError("response content is empty")


def _safe_http_error(status_code: int) -> ChatRuntimeError:
    if status_code == 429:
        return ChatRuntimeError(503, "upstream_busy", "지금 AI 연결이 혼잡합니다. 잠시 후 다시 시도해 주세요.")
    if status_code in {401, 403}:
        return ChatRuntimeError(503, "test_provider_auth_failed", "테스트 AI 연결 권한을 확인할 수 없습니다.")
    if status_code >= 500:
        return ChatRuntimeError(502, "upstream_unavailable", "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.")
    return ChatRuntimeError(502, "upstream_error", "답변을 불러오지 못했습니다. 다시 시도해 주세요.")


class PoolsideUXTestClient:
    """Duck-compatible subset of B14Client used only by the preview Worker."""

    def __init__(
        self,
        secret_binding: SecretStoreBinding,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = POOL_SIDE_TIMEOUT_SECONDS,
    ) -> None:
        if secret_binding is None:
            raise ValueError("Poolside Secrets Store binding is required")
        self._secret_binding = secret_binding
        self._transport = transport
        self._timeout_seconds = float(timeout_seconds)

    def __repr__(self) -> str:
        return "PoolsideUXTestClient(test-only, credential=SecretsStore)"

    async def _credential(self) -> str:
        try:
            raw = await self._secret_binding.get()
        except Exception:
            # Do not chain a binding/provider exception: a connector or runtime
            # exception may retain sensitive object state even when its message is safe.
            raise ChatRuntimeError(
                503,
                "test_provider_credential_unavailable",
                "테스트 AI 연결 정보를 불러오지 못했습니다.",
            ) from None
        value = str(raw or "").strip()
        if not value:
            raise ChatRuntimeError(
                503,
                "test_provider_credential_unavailable",
                "테스트 AI 연결 정보가 준비되지 않았습니다.",
            )
        return value

    @staticmethod
    def _payload(
        messages: list[dict[str, str]],
        *,
        skill: Skill,
        additional_system_context: str | None,
        stream: bool,
    ) -> dict[str, Any]:
        return {
            "model": POOL_SIDE_MODEL,
            "messages": _provider_messages(
                messages,
                skill=skill,
                additional_system_context=additional_system_context,
            ),
            "temperature": 0.2,
            "max_tokens": max(POOL_SIDE_TEST_MAX_TOKENS, int(skill.max_tokens)),
            "stream": stream,
        }

    async def complete(
        self,
        messages: list[dict[str, str]],
        skill: Skill | None = None,
        additional_system_context: str | None = None,
        attachments: tuple[ImageAttachment, ...] = (),
    ) -> dict[str, Any]:
        if attachments:
            raise ChatRuntimeError(
                422,
                "test_image_unsupported",
                "이번 실제 대화 UX 시험에서는 사진 입력을 사용하지 않습니다.",
            )

        resolved_skill = skill or get_skill()
        credential = await self._credential()
        headers = {
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
        }
        payload = self._payload(
            messages,
            skill=resolved_skill,
            additional_system_context=additional_system_context,
            stream=False,
        )

        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(POOL_SIDE_CHAT_URL, headers=headers, json=payload)
        except httpx.TimeoutException:
            raise ChatRuntimeError(
                504,
                "upstream_timeout",
                "답변 준비가 오래 걸리고 있습니다. 잠시 후 다시 시도해 주세요.",
            ) from None
        except httpx.HTTPError:
            # Never chain an httpx request object carrying Authorization.
            raise ChatRuntimeError(
                502,
                "upstream_unavailable",
                "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.",
            ) from None

        if response.status_code != 200:
            raise _safe_http_error(response.status_code)
        if len(response.content) > POOL_SIDE_MAX_RESPONSE_BYTES:
            raise ChatRuntimeError(502, "upstream_response_too_large", "답변이 너무 커서 안전하게 표시할 수 없습니다.")

        try:
            answer = _extract_answer(response.json())
        except ValueError:
            raise ChatRuntimeError(
                502,
                "malformed_upstream",
                "AI 응답 형식을 확인할 수 없습니다. 다시 시도해 주세요.",
            ) from None

        return {
            "answer": answer,
            "request_id": "b62_poolside_ux_test",
            "runtime": "test_poolside",
            "route": {
                "mode": "test-direct",
                "model": POOL_SIDE_MODEL,
                "provider": POOL_SIDE_PROVIDER,
            },
            "skill": skill_public_metadata(resolved_skill),
        }

    async def stream_text_auto(
        self,
        messages: list[dict[str, str]],
        *,
        skill: Skill | None = None,
        additional_system_context: str | None = None,
    ) -> AsyncIterator[ChatStreamEvent]:
        resolved_skill = skill or get_skill()
        credential = await self._credential()
        headers = {
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
        }
        payload = self._payload(
            messages,
            skill=resolved_skill,
            additional_system_context=additional_system_context,
            stream=True,
        )
        visible = False

        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout_seconds,
                follow_redirects=False,
            ) as client:
                async with client.stream("POST", POOL_SIDE_CHAT_URL, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        raise _safe_http_error(response.status_code)
                    async for line in response.aiter_lines():
                        text = line.strip()
                        if not text or text.startswith(":") or not text.startswith("data:"):
                            continue
                        data = text[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                            choices = event.get("choices") if isinstance(event, dict) else None
                            first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
                            delta = first.get("delta") if isinstance(first, dict) else None
                            content = delta.get("content") if isinstance(delta, dict) else None
                        except ValueError:
                            continue
                        if isinstance(content, str) and content:
                            visible = True
                            yield ChatStreamEvent(delta_content=content)
        except ChatRuntimeError:
            raise
        except httpx.TimeoutException:
            raise ChatRuntimeError(
                504,
                "upstream_timeout",
                "답변 준비가 오래 걸리고 있습니다. 잠시 후 다시 시도해 주세요.",
            ) from None
        except httpx.HTTPError:
            raise ChatRuntimeError(
                502,
                "upstream_unavailable",
                "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.",
            ) from None

        if not visible:
            raise ChatRuntimeError(502, "empty_upstream_answer", "AI가 표시할 답변을 만들지 못했습니다. 다시 시도해 주세요.")
        yield ChatStreamEvent(done=True)
