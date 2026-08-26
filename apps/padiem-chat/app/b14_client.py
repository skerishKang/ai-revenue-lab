from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .attachments import ImageAttachment
from .config import Settings
from .skills import Skill, get_skill, skill_public_metadata

MAX_B14_RESPONSE_BYTES = 1_048_576
MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS = 14_000


class B14ServiceTransport(Protocol):
    async def post_json(self, url: str, payload: dict[str, Any]) -> tuple[int, bytes]: ...


@dataclass
class ChatRuntimeError(Exception):
    status_code: int
    code: str
    user_message: str

    def __str__(self) -> str:
        return self.user_message


def _messages_with_attachment(
    messages: list[dict[str, str]],
    attachment: ImageAttachment,
) -> list[dict[str, Any]]:
    latest_user_index = None
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            latest_user_index = index
            break
    if latest_user_index is None:
        raise ValueError("image attachment requires a user message")

    out: list[dict[str, Any]] = [dict(message) for message in messages]
    text = out[latest_user_index]["content"]
    out[latest_user_index] = {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {
                "type": "image_url",
                "image_url": {"url": attachment.data_url},
            },
        ],
    }
    return out


class B14Client:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        service_transport: B14ServiceTransport | None = None,
        require_service_binding: bool = False,
    ):
        self.settings = settings
        self.transport = transport
        self.service_transport = service_transport
        self.require_service_binding = require_service_binding

    async def complete(
        self,
        messages: list[dict[str, str]],
        skill: Skill | None = None,
        additional_system_context: str | None = None,
        attachments: tuple[ImageAttachment, ...] = (),
    ) -> dict[str, Any]:
        if len(attachments) > 1:
            raise ValueError("only one image attachment is supported")

        resolved_skill = skill or get_skill()
        system_content = resolved_skill.system_instruction
        if additional_system_context is not None:
            if not isinstance(additional_system_context, str):
                raise ValueError("additional system context must be a string")
            extra = additional_system_context.strip()
            if len(extra) > MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS:
                raise ValueError("additional system context is too large")
            if extra:
                system_content = f"{system_content}\n\n{extra}"

        attachment = attachments[0] if attachments else None

        if self.settings.runtime_mode == "mock":
            prompt = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
            if attachment is None:
                answer = (
                    "모의 실행 상태입니다. 실제 모델을 호출하지 않았습니다. "
                    f"현재 작업 모드는 ‘{resolved_skill.title}’이고, 입력하신 질문은 ‘{prompt[:120]}’입니다. "
                    "B14 연결 모드에서는 같은 작업 방식으로 자동 추천 경로의 실제 답변을 받습니다."
                )
            else:
                answer = (
                    "모의 실행 상태입니다. 사진 1장을 첨부받았지만 실제 모델 호출이나 이미지 분석은 하지 않았습니다. "
                    f"현재 작업 모드는 ‘{resolved_skill.title}’이고, 질문은 ‘{prompt[:120]}’입니다. "
                    "B14 연결 모드에서는 이미지 입력을 지원하는 모델 경로로 분석합니다."
                )
            result: dict[str, Any] = {
                "answer": answer,
                "request_id": "mock_b62",
                "runtime": "mock",
                "route": {"mode": "auto", "model": None, "provider": None},
                "skill": skill_public_metadata(resolved_skill),
            }
            if attachment is not None:
                result["attachments"] = [attachment.public_dict()]
            return result

        if attachment is None:
            user_messages: list[dict[str, Any]] = [dict(message) for message in messages]
        else:
            user_messages = _messages_with_attachment(messages, attachment)

        upstream_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_content},
            *user_messages,
        ]

        assert self.settings.b14_base_url is not None
        url = self.settings.b14_base_url.rstrip("/") + "/api/pilot/v1/chat/completions"
        required_capabilities = ["free"]
        if attachment is not None:
            required_capabilities.append("image")
        business14: dict[str, Any] = {
            "task_type": resolved_skill.task_type,
            "optimize_for": resolved_skill.optimize_for,
            "allow_external_fallback": True,
            "max_attempts": 3,
            "required_capabilities": required_capabilities,
        }

        payload = {
            "model": "b14/auto",
            "messages": upstream_messages,
            "temperature": 0.2,
            "max_tokens": resolved_skill.max_tokens,
            "business14": business14,
        }

        if self.service_transport is not None:
            try:
                status_code, service_raw = await self.service_transport.post_json(url, payload)
            except ChatRuntimeError:
                raise
            except Exception as exc:
                raise ChatRuntimeError(
                    502,
                    "upstream_unavailable",
                    "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.",
                ) from exc
            if not isinstance(service_raw, (bytes, bytearray)):
                raise ChatRuntimeError(
                    502,
                    "malformed_upstream",
                    "AI 응답 형식을 확인할 수 없습니다. 다시 시도해 주세요.",
                )
            if len(service_raw) > MAX_B14_RESPONSE_BYTES:
                raise ChatRuntimeError(
                    502,
                    "upstream_response_too_large",
                    "답변이 너무 커서 안전하게 표시할 수 없습니다.",
                )
            raw = bytearray(service_raw)
        elif self.require_service_binding:
            raise ChatRuntimeError(
                503,
                "upstream_binding_unavailable",
                "AI 내부 연결이 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.",
            )
        else:
            timeout = httpx.Timeout(
                connect=min(self.settings.timeout_seconds, 10.0),
                read=self.settings.timeout_seconds,
                write=min(self.settings.timeout_seconds, 10.0),
                pool=min(self.settings.timeout_seconds, 10.0),
            )
            try:
                async with httpx.AsyncClient(
                    transport=self.transport,
                    timeout=timeout,
                    follow_redirects=False,
                ) as client:
                    async with client.stream("POST", url, json=payload) as response:
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(raw) + len(chunk) > MAX_B14_RESPONSE_BYTES:
                                raise ChatRuntimeError(
                                    502,
                                    "upstream_response_too_large",
                                    "답변이 너무 커서 안전하게 표시할 수 없습니다.",
                                )
                            raw.extend(chunk)
                        status_code = response.status_code
            except ChatRuntimeError:
                raise
            except httpx.TimeoutException as exc:
                raise ChatRuntimeError(
                    504,
                    "upstream_timeout",
                    "답변 준비가 오래 걸리고 있습니다. 잠시 후 다시 시도해 주세요.",
                ) from exc
            except httpx.HTTPError as exc:
                raise ChatRuntimeError(
                    502,
                    "upstream_unavailable",
                    "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.",
                ) from exc

        if status_code < 200 or status_code >= 300:
            if status_code == 429:
                raise ChatRuntimeError(
                    503,
                    "upstream_busy",
                    "지금 사용자가 많습니다. 잠시 후 다시 시도해 주세요.",
                )
            raise ChatRuntimeError(
                502,
                "upstream_error",
                "답변을 불러오지 못했습니다. 다시 시도해 주세요.",
            )

        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ChatRuntimeError(
                502,
                "malformed_upstream",
                "AI 응답 형식을 확인할 수 없습니다. 다시 시도해 주세요.",
            ) from exc

        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ChatRuntimeError(
                502,
                "malformed_upstream",
                "AI 응답 형식을 확인할 수 없습니다. 다시 시도해 주세요.",
            ) from exc

        if not isinstance(answer, str) or not answer.strip():
            raise ChatRuntimeError(
                502,
                "empty_upstream_answer",
                "AI가 빈 답변을 반환했습니다. 다시 시도해 주세요.",
            )

        meta = data.get("business14")
        if not isinstance(meta, dict):
            meta = {}

        request_id = meta.get("request_id")
        if not isinstance(request_id, str):
            request_id = None

        selected_model = meta.get("selected_model")
        selected_provider = meta.get("selected_provider")
        route_mode = meta.get("route_mode", "auto")

        result = {
            "answer": answer.strip(),
            "request_id": request_id,
            "runtime": "b14",
            "route": {
                "mode": route_mode if isinstance(route_mode, str) else "auto",
                "model": selected_model if isinstance(selected_model, str) else None,
                "provider": selected_provider if isinstance(selected_provider, str) else None,
            },
            "skill": skill_public_metadata(resolved_skill),
        }
        if attachment is not None:
            result["attachments"] = [attachment.public_dict()]
        return result
