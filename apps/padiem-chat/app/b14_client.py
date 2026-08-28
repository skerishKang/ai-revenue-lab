from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from padiem_ai_core import (
    AgentProfile,
    B14MultimodalChatRequest,
    B14PostJSONTransport,
    B14ExecutionClient,
    B14ExecutionConfig,
    B14ExecutionError,
    B14RoutingOptions,
    B14StreamingClient,
    B14TransportResponse,
    ExecutionRequest,
    ExecutionRuntime,
    ExecutionRuntimeError,
    StreamingExecutionRuntime,
    MAX_B14_RESPONSE_BYTES,
)

from .attachments import ImageAttachment
from .config import Settings
from .model_policy import ModelPolicyError, model_supports, resolve_model_policy
from .skills import Skill, get_skill, skill_public_metadata

MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS = 14_000


class B14ServiceTransport(Protocol):
    async def post_json(self, url: str, payload: dict[str, Any]) -> tuple[int, bytes]: ...


class _CoreTransportAdapter:
    """Adapt the existing B62 Service Binding transport to Core without Cloudflare types."""

    def __init__(self, transport: B14ServiceTransport):
        self._transport = transport

    async def post_json(self, url: str, payload: dict[str, Any]) -> B14TransportResponse:
        status_code, body = await self._transport.post_json(url, payload)
        return B14TransportResponse(status_code=status_code, body=body)


@dataclass(frozen=True, slots=True)
class ChatStreamEvent:
    """Minimal B62 server-side stream event projected from Core execution."""

    delta_content: str | None = None
    done: bool = False


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


def _chat_error(code: str) -> ChatRuntimeError:
    if code == "upstream_timeout":
        return ChatRuntimeError(
            504,
            "upstream_timeout",
            "답변 준비가 오래 걸리고 있습니다. 잠시 후 다시 시도해 주세요.",
        )
    if code == "upstream_rate_limited":
        return ChatRuntimeError(
            503,
            "upstream_busy",
            "지금 사용자가 많습니다. 잠시 후 다시 시도해 주세요.",
        )
    if code == "upstream_response_too_large":
        return ChatRuntimeError(
            502,
            "upstream_response_too_large",
            "답변이 너무 커서 안전하게 표시할 수 없습니다.",
        )
    if code in {"malformed_upstream", "empty_upstream_answer"}:
        return ChatRuntimeError(
            502,
            "malformed_upstream",
            "AI 응답 형식을 확인할 수 없습니다. 다시 시도해 주세요.",
        )
    if code == "upstream_unavailable":
        return ChatRuntimeError(
            502,
            "upstream_unavailable",
            "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.",
        )
    if code == "invalid_execution_request":
        return ChatRuntimeError(
            422,
            "invalid_request",
            "AI 요청 형식을 확인할 수 없습니다.",
        )
    return ChatRuntimeError(
        502,
        "upstream_error",
        "답변을 불러오지 못했습니다. 다시 시도해 주세요.",
    )


def _translate_core_error(exc: B14ExecutionError) -> ChatRuntimeError:
    """Translate the preserved image-path B14 transport error into product copy."""

    return _chat_error(exc.code)


def _translate_execution_error(exc: ExecutionRuntimeError) -> ChatRuntimeError:
    """Translate the product-neutral Core runtime error into B62 Korean UX copy."""

    return _chat_error(exc.code)


def _resolve_b62_policy(messages: list[dict[str, str]]):
    try:
        return resolve_model_policy(messages)
    except ModelPolicyError as exc:
        raise ChatRuntimeError(422, exc.code, exc.message) from exc


def _bounded_context(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("additional system context must be a string")
    extra = value.strip()
    if len(extra) > MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS:
        raise ValueError("additional system context is too large")
    return extra or None


def _agent_profile(
    *,
    skill: Skill,
    model: str,
    required_capabilities: tuple[str, ...],
) -> AgentProfile:
    """Convert B62-owned Skill/model policy into the locked Core contract."""

    return AgentProfile(
        id=f"b62-{skill.id}",
        title=skill.title,
        description=skill.short_description or skill.title,
        system_instruction=skill.system_instruction,
        task_type=skill.task_type,
        optimize_for=skill.optimize_for,
        max_tokens=skill.max_tokens,
        required_capabilities=required_capabilities,
        model_policy={
            "model": model,
            "temperature": 0.2,
            "allow_external_fallback": False,
            "max_attempts": 1,
        },
    )


def _execution_request(
    messages: list[dict[str, str]],
    *,
    skill: Skill,
    model: str,
    required_capabilities: tuple[str, ...],
    additional_system_context: str | None,
) -> ExecutionRequest:
    return ExecutionRequest(
        agent=_agent_profile(
            skill=skill,
            model=model,
            required_capabilities=required_capabilities,
        ),
        messages=tuple(dict(message) for message in messages),
        additional_system_context=_bounded_context(additional_system_context),
    )


class B14Client:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        service_transport: B14ServiceTransport | None = None,
        stream_transport: httpx.AsyncBaseTransport | None = None,
        require_service_binding: bool = False,
    ):
        self.settings = settings
        self.transport = transport
        self.service_transport = service_transport
        self.stream_transport = stream_transport
        self.require_service_binding = require_service_binding

    def _config(self) -> B14ExecutionConfig:
        assert self.settings.b14_base_url is not None
        return B14ExecutionConfig(
            base_url=self.settings.b14_base_url,
            timeout_seconds=self.settings.timeout_seconds,
            max_response_bytes=MAX_B14_RESPONSE_BYTES,
        )

    def _completion_transport(self):
        execution_transport = self.transport
        if self.service_transport is not None:
            execution_transport = B14PostJSONTransport(
                _CoreTransportAdapter(self.service_transport),
                timeout_seconds=self.settings.timeout_seconds,
            )
        return execution_transport

    async def _stream_core(
        self,
        request: ExecutionRequest,
    ) -> AsyncIterator[ChatStreamEvent]:
        core_client = B14StreamingClient(
            self._config(),
            transport=self.stream_transport or self.transport,
        )
        runtime = StreamingExecutionRuntime(
            app_id="padiem-chat",
            b14_stream_client=core_client,
        )
        core_stream = runtime.stream(request)
        try:
            async for event in core_stream:
                if event.delta_content:
                    yield ChatStreamEvent(delta_content=event.delta_content)
                if event.done:
                    yield ChatStreamEvent(done=True)
        except ExecutionRuntimeError as exc:
            raise _translate_execution_error(exc) from exc
        finally:
            try:
                await core_stream.aclose()
            except Exception:
                # Cleanup is best-effort and must not replace the bounded stream
                # result/error with raw transport details.
                pass

    async def stream_text_preview(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        skill: Skill | None = None,
        additional_system_context: str | None = None,
    ) -> AsyncIterator[ChatStreamEvent]:
        """Yield a private text stream through the product-neutral Core runtime."""

        if not isinstance(model, str) or not model.strip() or model.strip() == "b14/auto":
            raise ValueError("private streaming requires an explicit manual model")
        resolved_model = model.strip()
        resolved_skill = skill or get_skill()
        bounded_context = _bounded_context(additional_system_context)

        if self.settings.runtime_mode == "mock":
            prompt = next(
                (m["content"] for m in reversed(messages) if m.get("role") == "user"),
                "",
            )
            yield ChatStreamEvent(
                delta_content=(
                    "지금은 미리보기 환경입니다. "
                    f"입력하신 질문은 ‘{prompt[:120]}’입니다."
                )
            )
            yield ChatStreamEvent(done=True)
            return

        if self.require_service_binding and self.stream_transport is None:
            raise ChatRuntimeError(
                503,
                "upstream_binding_unavailable",
                "AI 내부 스트리밍 연결이 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.",
            )

        request = _execution_request(
            messages,
            skill=resolved_skill,
            model=resolved_model,
            required_capabilities=("free",),
            additional_system_context=bounded_context,
        )
        inner_stream = self._stream_core(request)
        try:
            async for event in inner_stream:
                yield event
        finally:
            try:
                await inner_stream.aclose()
            except Exception:
                pass

    async def stream_text_auto(
        self,
        messages: list[dict[str, str]],
        *,
        skill: Skill | None = None,
        additional_system_context: str | None = None,
    ) -> AsyncIterator[ChatStreamEvent]:
        """Compatibility entrypoint for B62's simple default UX.

        Despite the historical method name, B62 does not invoke B14's `b14/auto`
        router here. It resolves the B62-owned product profile first, then hands a
        product-neutral ExecutionRequest to Core.
        """

        policy = _resolve_b62_policy(messages)
        resolved_skill = skill or get_skill()
        bounded_context = _bounded_context(additional_system_context)

        if self.settings.runtime_mode == "mock":
            prompt = next(
                (m["content"] for m in reversed(policy.messages) if m.get("role") == "user"),
                "",
            )
            yield ChatStreamEvent(
                delta_content=(
                    "지금은 미리보기 환경입니다. "
                    f"입력하신 질문은 ‘{prompt[:120]}’입니다."
                )
            )
            yield ChatStreamEvent(done=True)
            return

        if self.require_service_binding and self.stream_transport is None:
            raise ChatRuntimeError(
                503,
                "upstream_binding_unavailable",
                "AI 내부 스트리밍 연결이 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.",
            )

        request = _execution_request(
            policy.messages,
            skill=resolved_skill,
            model=policy.model_id,
            required_capabilities=("chat",),
            additional_system_context=bounded_context,
        )
        inner_stream = self._stream_core(request)
        try:
            async for event in inner_stream:
                yield event
        finally:
            try:
                await inner_stream.aclose()
            except Exception:
                pass

    async def _complete_text(
        self,
        messages: list[dict[str, str]],
        *,
        skill: Skill,
        model: str,
        additional_system_context: str | None,
    ) -> dict[str, Any]:
        request = _execution_request(
            messages,
            skill=skill,
            model=model,
            required_capabilities=("chat",),
            additional_system_context=additional_system_context,
        )
        core_client = B14ExecutionClient(
            self._config(),
            transport=self._completion_transport(),
        )
        runtime = ExecutionRuntime(
            app_id="padiem-chat",
            b14_client=core_client,
        )
        try:
            execution = await runtime.run(request)
        except ExecutionRuntimeError as exc:
            raise _translate_execution_error(exc) from exc

        route_mode = execution.route.route_mode or "manual"
        return {
            "answer": execution.answer,
            "request_id": execution.route.request_id,
            "runtime": "b14",
            "route": {
                "mode": route_mode,
                "model": execution.route.selected_model,
                "provider": execution.route.selected_provider,
            },
            "skill": skill_public_metadata(skill),
        }

    async def _complete_image(
        self,
        messages: list[dict[str, str]],
        *,
        skill: Skill,
        model: str,
        attachment: ImageAttachment,
        additional_system_context: str | None,
    ) -> dict[str, Any]:
        """Preserved bounded multimodal exception until a shared Core facade exists."""

        if not model_supports(model, "image"):
            raise ChatRuntimeError(
                503,
                "image_model_unavailable",
                "현재 선택된 AI 모델은 사진 입력을 지원하지 않습니다. 사진 지원 모델이 준비되면 다시 이용해 주세요.",
            )

        user_messages = _messages_with_attachment(messages, attachment)
        system_content = skill.system_instruction
        extra = _bounded_context(additional_system_context)
        if extra:
            system_content = f"{system_content}\n\n{extra}"

        upstream_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_content},
            *user_messages,
        ]

        request = B14MultimodalChatRequest(
            messages=tuple(upstream_messages),
            model=model,
            temperature=0.2,
            max_tokens=skill.max_tokens,
            routing=B14RoutingOptions(
                task_type=skill.task_type,
                optimize_for=skill.optimize_for,
                allow_external_fallback=False,
                max_attempts=1,
                required_capabilities=("chat", "image"),
            ),
        )
        core_client = B14ExecutionClient(
            self._config(),
            transport=self._completion_transport(),
        )
        try:
            execution = await core_client.execute(request)
        except B14ExecutionError as exc:
            raise _translate_core_error(exc) from exc

        route_mode = execution.route.route_mode or "manual"
        return {
            "answer": execution.answer,
            "request_id": execution.route.request_id,
            "runtime": "b14",
            "route": {
                "mode": route_mode,
                "model": execution.route.selected_model,
                "provider": execution.route.selected_provider,
            },
            "skill": skill_public_metadata(skill),
            "attachments": [attachment.public_dict()],
        }

    async def complete(
        self,
        messages: list[dict[str, str]],
        skill: Skill | None = None,
        additional_system_context: str | None = None,
        attachments: tuple[ImageAttachment, ...] = (),
    ) -> dict[str, Any]:
        if len(attachments) > 1:
            raise ValueError("only one image attachment is supported")

        policy = _resolve_b62_policy(messages)
        resolved_skill = skill or get_skill()
        bounded_context = _bounded_context(additional_system_context)
        attachment = attachments[0] if attachments else None

        if self.settings.runtime_mode == "mock":
            prompt = next(
                (m["content"] for m in reversed(policy.messages) if m["role"] == "user"),
                "",
            )
            if attachment is None:
                answer = (
                    "지금은 미리보기 환경입니다. "
                    f"입력하신 질문은 ‘{prompt[:120]}’입니다. "
                    "정식 답변 기능은 준비가 끝난 뒤 이용할 수 있습니다."
                )
            else:
                answer = (
                    "지금은 미리보기 환경입니다. 사진 1장을 첨부받았지만 사진 내용은 아직 분석하지 않습니다. "
                    f"질문은 ‘{prompt[:120]}’입니다."
                )
            result: dict[str, Any] = {
                "answer": answer,
                "request_id": "mock_b62",
                "runtime": "mock",
                "route": {"mode": "manual", "model": policy.model_id, "provider": None},
                "skill": skill_public_metadata(resolved_skill),
            }
            if attachment is not None:
                result["attachments"] = [attachment.public_dict()]
            return result

        if self.require_service_binding and self.service_transport is None:
            raise ChatRuntimeError(
                503,
                "upstream_binding_unavailable",
                "AI 내부 연결이 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.",
            )

        if attachment is not None:
            return await self._complete_image(
                policy.messages,
                skill=resolved_skill,
                model=policy.model_id,
                attachment=attachment,
                additional_system_context=bounded_context,
            )

        return await self._complete_text(
            policy.messages,
            skill=resolved_skill,
            model=policy.model_id,
            additional_system_context=bounded_context,
        )
