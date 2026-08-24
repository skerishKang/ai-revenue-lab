from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings

MAX_B14_RESPONSE_BYTES = 1_048_576


@dataclass
class ChatRuntimeError(Exception):
    status_code: int
    code: str
    user_message: str

    def __str__(self) -> str:
        return self.user_message


class B14Client:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    async def complete(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if self.settings.runtime_mode == "mock":
            prompt = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
            answer = (
                "모의 실행 상태입니다. 실제 모델을 호출하지 않았습니다. "
                f"입력하신 질문은 ‘{prompt[:120]}’입니다. "
                "B14 연결 모드에서는 같은 화면에서 자동 추천 경로로 실제 답변을 받습니다."
            )
            return {
                "answer": answer,
                "request_id": "mock_b62",
                "runtime": "mock",
                "route": {"mode": "auto", "model": None, "provider": None},
            }

        assert self.settings.b14_base_url is not None
        url = self.settings.b14_base_url.rstrip("/") + "/api/pilot/v1/chat/completions"
        payload = {
            "model": "b14/auto",
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 700,
            "business14": {
                "task_type": "general",
                "optimize_for": "korean",
                "allow_external_fallback": True,
                "max_attempts": 3,
            },
        }

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
                                502, "upstream_response_too_large",
                                "답변이 너무 커서 안전하게 표시할 수 없습니다.",
                            )
                        raw.extend(chunk)
                    status_code = response.status_code
        except ChatRuntimeError:
            raise
        except httpx.TimeoutException as exc:
            raise ChatRuntimeError(
                504, "upstream_timeout",
                "답변 준비가 오래 걸리고 있습니다. 잠시 후 다시 시도해 주세요.",
            ) from exc
        except httpx.HTTPError as exc:
            raise ChatRuntimeError(
                502, "upstream_unavailable",
                "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.",
            ) from exc

        if status_code < 200 or status_code >= 300:
            if status_code == 429:
                raise ChatRuntimeError(
                    503, "upstream_busy",
                    "지금 사용자가 많습니다. 잠시 후 다시 시도해 주세요.",
                )
            raise ChatRuntimeError(
                502, "upstream_error",
                "답변을 불러오지 못했습니다. 다시 시도해 주세요.",
            )

        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ChatRuntimeError(
                502, "malformed_upstream",
                "AI 응답 형식을 확인할 수 없습니다. 다시 시도해 주세요.",
            ) from exc

        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ChatRuntimeError(
                502, "malformed_upstream",
                "AI 응답 형식을 확인할 수 없습니다. 다시 시도해 주세요.",
            ) from exc

        if not isinstance(answer, str) or not answer.strip():
            raise ChatRuntimeError(
                502, "empty_upstream_answer",
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

        return {
            "answer": answer.strip(),
            "request_id": request_id,
            "runtime": "b14",
            "route": {
                "mode": route_mode if isinstance(route_mode, str) else "auto",
                "model": selected_model if isinstance(selected_model, str) else None,
                "provider": selected_provider if isinstance(selected_provider, str) else None,
            },
        }
