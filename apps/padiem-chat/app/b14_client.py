from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

# Core completion transports use real httpx's type family, also on Workers.
# Worker execution still uses the existing Service Binding transport.
import httpx as execution_httpx

from . import httpx_compat as httpx

from padiem_ai_core import (
    AgentProfile,
    B14PostJSONTransport,
    B14ExecutionClient,
    B14ExecutionConfig,
    B14StreamingClient,
    B14TransportResponse,
    ExecutionRequest,
    ExecutionRuntime,
    ExecutionRuntimeError,
    MultimodalExecutionRequest,
    MultimodalExecutionRuntime,
    StreamingExecutionRuntime,
    MAX_B14_RESPONSE_BYTES,
)

from .attachments import ImageAttachment
from .config import Settings
from .model_policy import ModelPolicyError, model_supports, resolve_request_model_policy
from .task_modes import TaskMode, get_task_mode, task_mode_public_metadata

MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS = 14_000

# Product identity policy. Padiem Chat is a general Korean-first assistant;
# upstream model/provider identities are not part of the user-facing product.
# The instruction is a branding policy, not an answer-style or length cap.
PADIEM_IDENTITY_INSTRUCTION = (
    "당신은 파디엠(Padiem)이 제공하는 AI 어시스턴트입니다. "
    "자신의 모델 이름, 제조사, 버전, 아키텍처를 밝히지 마세요. "
    "모델이나 제조사를 묻는 질문에는 '파디엠이 제공하는 AI 어시스턴트입니다'라고만 답하세요."
)


class B14ServiceTransport(Protocol):
    async def post_json(self, url: str, payload: dict[str, Any]) -> tuple[int, bytes]: ...


def _native_model_parameter_contract_present() -> bool:
    """Measure whether the INSTALLED shared Core can carry the #3977 fields.

    `supports_native_model_parameters` is a claim about the code that will
    actually build this request, so it is probed rather than asserted: a Core
    build that rejects or ignores ``model_parameters`` reports False, and B66
    then refuses an explicit reasoning level before dispatch instead of quietly
    dropping the customer's choice. This never infers capability from a model
    name; which served model accepts which value stays B14 authority.
    """
    try:
        from padiem_ai_core.b14_execution import B14ChatRequest

        probe = B14ChatRequest(
            messages=({"role": "user", "content": "capability probe"},),
            model="native-parameter-contract-probe",
            model_parameters={"reasoning_effort": "low"},
        )
        payload = probe.to_payload()
    except Exception:
        return False
    return payload.get("reasoning_effort") == "low" and "model_parameters" not in payload


@lru_cache(maxsize=1)
def _native_model_parameter_transport() -> bool:
    """The installed Core is fixed for the process, so the probe is cached once."""
    return _native_model_parameter_contract_present()


class _CoreTransportAdapter:
    """Adapt the existing B62 Service Binding transport to Core without Cloudflare types."""

    def __init__(
        self,
        transport: B14ServiceTransport,
        *,
        before_dispatch: Callable[[], Awaitable[None]] | None = None,
    ):
        self._transport = transport
        self._before_dispatch = before_dispatch

    async def post_json(self, url: str, payload: dict[str, Any]) -> B14TransportResponse:
        if self._before_dispatch is not None:
            await self._before_dispatch()
        status_code, body = await self._transport.post_json(url, payload)
        if self._before_dispatch is not None and status_code == 504:
            # B66 keeps the bounded timeout category through Core's existing
            # timeout translation; no provider body is inspected or relayed.
            raise TimeoutError("B14 quote execution timed out")
        return B14TransportResponse(status_code=status_code, body=body)


class _BeforeDispatchHTTPTransport(execution_httpx.AsyncBaseTransport):
    """Mark B66 direct-HTTP dispatch after Core/HTTP request serialization."""

    def __init__(
        self,
        transport: execution_httpx.AsyncBaseTransport,
        before_dispatch: Callable[[], Awaitable[None]],
    ):
        self._transport = transport
        self._before_dispatch = before_dispatch

    async def handle_async_request(
        self, request: execution_httpx.Request
    ) -> execution_httpx.Response:
        await self._before_dispatch()
        response = await self._transport.handle_async_request(request)
        if response.status_code == 504:
            await response.aclose()
            raise execution_httpx.ReadTimeout("B14 quote execution timed out", request=request)
        return response

    async def aclose(self) -> None:
        await self._transport.aclose()


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
    upstream_class: str | None = None

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


def _chat_error(
    code: str,
    *,
    upstream_class: str | None = None,
) -> ChatRuntimeError:
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
            upstream_class=upstream_class,
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
    if code == "upstream_auth_error":
        return ChatRuntimeError(
            502,
            "provider_auth_error",
            "AI 서비스 인증 확인에 실패했습니다. 잠시 후 다시 시도해 주세요.",
        )
    if code == "upstream_request_error":
        return ChatRuntimeError(
            502,
            "provider_route_error",
            "현재 AI 모델이 요청을 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        )
    if code == "upstream_server_error":
        return ChatRuntimeError(
            502,
            "provider_server_error",
            "AI 모델 제공자 측에서 일시적 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
        )
    if code == "execution_failed":
        return ChatRuntimeError(
            502,
            "upstream_execution_failed",
            "답변을 불러오지 못했습니다. 다시 시도해 주세요.",
        )
    return ChatRuntimeError(
        502,
        "upstream_error",
        "답변을 불러오지 못했습니다. 다시 시도해 주세요.",
    )


def _translate_execution_error(exc: ExecutionRuntimeError) -> ChatRuntimeError:
    """Translate the product-neutral Core runtime error into B62 Korean UX copy."""

    return _chat_error(exc.code, upstream_class=exc.diagnostic_class)


def _resolve_b62_policy(
    messages: list[dict[str, str]],
    *,
    require_executable: bool = True,
):
    try:
        return resolve_request_model_policy(
            messages,
            require_executable=require_executable,
        )
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
    skill: TaskMode,
    model: str,
    required_capabilities: tuple[str, ...],
    max_retries: int | None = None,
    model_parameters: Mapping[str, Any] | None = None,
) -> AgentProfile:
    """Convert B62-owned TaskMode/model policy into the locked Core contract."""

    skill_instruction = skill.system_instruction
    if skill_instruction:
        system_instruction = f"{PADIEM_IDENTITY_INSTRUCTION} {skill_instruction}"
    else:
        system_instruction = PADIEM_IDENTITY_INSTRUCTION

    return AgentProfile(
        id=f"b62-{skill.id}",
        title=skill.title,
        description=skill.short_description or skill.title,
        system_instruction=system_instruction,
        task_type=skill.task_type,
        optimize_for=skill.optimize_for,
        max_tokens=skill.max_tokens,
        required_capabilities=required_capabilities,
        model_policy={
            "model": model,
            # Keep unchosen sampling absent: B14 honours provider native defaults.
            "allow_external_fallback": False,
            "max_attempts": 1,
            **({"max_retries": max_retries} if max_retries is not None else {}),
            # Only an explicitly requested native parameter enters the policy.
            # Nothing here synthesizes a level the caller never asked for, and an
            # absent choice leaves the request exactly as it was before (#3977).
            **(
                {"model_parameters": dict(model_parameters)}
                if model_parameters
                else {}
            ),
        },
    )


def _execution_request(
    messages: list[dict[str, str]],
    *,
    skill: TaskMode,
    model: str,
    required_capabilities: tuple[str, ...],
    additional_system_context: str | None,
    max_retries: int | None = None,
    model_parameters: Mapping[str, Any] | None = None,
) -> ExecutionRequest:
    return ExecutionRequest(
        agent=_agent_profile(
            skill=skill,
            model=model,
            required_capabilities=required_capabilities,
            max_retries=max_retries,
            model_parameters=model_parameters,
        ),
        messages=tuple(dict(message) for message in messages),
        additional_system_context=_bounded_context(additional_system_context),
    )


def _multimodal_execution_request(
    messages: list[dict[str, Any]],
    *,
    skill: TaskMode,
    model: str,
    additional_system_context: str | None,
) -> MultimodalExecutionRequest:
    return MultimodalExecutionRequest(
        agent=_agent_profile(
            skill=skill,
            model=model,
            required_capabilities=("chat", "image"),
        ),
        messages=tuple(messages),
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

    def _config(self, timeout_seconds: float | None = None) -> B14ExecutionConfig:
        assert self.settings.b14_base_url is not None
        return B14ExecutionConfig(
            base_url=self.settings.b14_base_url,
            timeout_seconds=(
                self.settings.timeout_seconds
                if timeout_seconds is None
                else timeout_seconds
            ),
            max_response_bytes=MAX_B14_RESPONSE_BYTES,
        )

    def _completion_config(self) -> B14ExecutionConfig:
        return self._config(self.settings.completed_timeout_seconds)

    def _completion_transport(
        self, *, before_dispatch: Callable[[], Awaitable[None]] | None = None
    ):
        execution_transport = self.transport
        if self.service_transport is not None:
            execution_transport = B14PostJSONTransport(
                _CoreTransportAdapter(
                    self.service_transport, before_dispatch=before_dispatch
                ),
                timeout_seconds=self.settings.completed_timeout_seconds,
            )
        elif before_dispatch is not None:
            execution_transport = _BeforeDispatchHTTPTransport(
                execution_transport or execution_httpx.AsyncHTTPTransport(),
                before_dispatch,
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
        skill: TaskMode | None = None,
        additional_system_context: str | None = None,
    ) -> AsyncIterator[ChatStreamEvent]:
        """Yield a private text stream through the product-neutral Core runtime."""

        if not isinstance(model, str) or not model.strip() or model.strip() == "b14/auto":
            raise ValueError("private streaming requires an explicit manual model")
        resolved_model = model.strip()
        resolved_skill = skill or get_task_mode()
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
        skill: TaskMode | None = None,
        additional_system_context: str | None = None,
    ) -> AsyncIterator[ChatStreamEvent]:
        """Compatibility entrypoint for B62's simple default UX.

        Despite the historical method name, B62 does not invoke B14's `b14/auto`
        router here. It resolves the B62-owned product profile first, then hands a
        product-neutral ExecutionRequest to Core.
        """

        policy = _resolve_b62_policy(
            messages,
            require_executable=self.settings.runtime_mode != "mock",
        )
        resolved_skill = skill or get_task_mode()
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
        skill: TaskMode,
        model: str,
        additional_system_context: str | None,
        max_retries: int | None = None,
        before_dispatch: Callable[[], Awaitable[None]] | None = None,
        model_parameters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = _execution_request(
            messages,
            skill=skill,
            model=model,
            required_capabilities=("chat",),
            additional_system_context=additional_system_context,
            max_retries=max_retries,
            model_parameters=model_parameters,
        )
        core_client = B14ExecutionClient(
            self._completion_config(),
            transport=self._completion_transport(before_dispatch=before_dispatch),
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
            "skill": task_mode_public_metadata(skill),
        }

    async def _complete_image(
        self,
        messages: list[dict[str, str]],
        *,
        skill: TaskMode,
        model: str,
        attachment: ImageAttachment,
        additional_system_context: str | None,
    ) -> dict[str, Any]:
        """Run the existing single-image product path through the shared Core facade."""

        if not model_supports(model, "image"):
            raise ChatRuntimeError(
                503,
                "image_model_unavailable",
                "현재 선택된 AI 모델은 사진 입력을 지원하지 않습니다. 사진 지원 모델이 준비되면 다시 이용해 주세요.",
            )

        request = _multimodal_execution_request(
            _messages_with_attachment(messages, attachment),
            skill=skill,
            model=model,
            additional_system_context=additional_system_context,
        )
        core_client = B14ExecutionClient(
            self._completion_config(),
            transport=self._completion_transport(),
        )
        runtime = MultimodalExecutionRuntime(
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
            "skill": task_mode_public_metadata(skill),
            "attachments": [attachment.public_dict()],
        }

    @property
    def supports_native_model_parameters(self) -> bool:
        """Whether validated #3977 native parameters reach the wire from here.

        Read by the B66 boundary before it commits a customer's explicit
        reasoning level. It reflects the installed Core contract, measured once,
        and is never inferred from a model name or forced True.
        """
        return _native_model_parameter_transport()

    def ensure_registered_quote_runtime_available(self) -> None:
        """Check the B66 live boundary without selecting or contacting a model."""
        if (
            self.settings.runtime_mode != "b14"
            or self.settings.live_enabled is not True
            or self.settings.b14_base_url is None
        ):
            raise ChatRuntimeError(
                503, "quote_runtime_unavailable",
                "견적 AI 해석 기능이 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.",
            )
        if self.require_service_binding and self.service_transport is None:
            raise ChatRuntimeError(
                503, "upstream_binding_unavailable",
                "AI 내부 연결이 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.",
            )

    async def _prepare_registered_quote_dispatch(self) -> None:
        """Dispatch-aware clients consume their reservation at this last boundary."""

    async def complete_registered_quote_model(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        additional_system_context: str | None = None,
        model_parameters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """B66 trusted exact route -> common Core/B14, NOT B62 tier policy.

        The internal caller must first obtain an owner-policy-authorized route
        from B14 registration authority. B14 validates the actual executable
        model and credential; this method NEVER chooses a model or a fallback.
        """
        self.ensure_registered_quote_runtime_available()
        if (
            not isinstance(model, str)
            or not model.strip()
            or model == "b14/auto"
            or model.startswith("padiem-profile/")
            or not all(c.isascii() and (c.isalnum() or c in "._:/-") for c in model)
            or len(model) > 256
        ):
            raise ChatRuntimeError(
                422, "model_route_unavailable", "견적 AI 모델 경로를 확인할 수 없습니다."
            )
        if (
            not isinstance(messages, list)
            or len(messages) != 1
            or not isinstance(messages[0], dict)
            or set(messages[0]) != {"role", "content"}
            or messages[0].get("role") != "user"
            or not isinstance(messages[0].get("content"), str)
            or not messages[0]["content"].strip()
        ):
            raise ChatRuntimeError(422, "invalid_request", "견적 입력 형식을 확인해 주세요.")
        if model_parameters is not None and not isinstance(model_parameters, Mapping):
            raise ChatRuntimeError(
                422, "invalid_request", "견적 모델 파라미터 형식을 확인해 주세요."
            )
        quote_task = TaskMode(
            id="b66_quote_extract_v1",
            title="B66 quote extraction",
            short_description="Structured quotation fields",
            system_instruction=None,
            task_type="document",
            optimize_for="korean",
            max_tokens=None,
        )
        bounded_context = _bounded_context(additional_system_context)
        # An omitted parameter set stays the exact pre-#3906 call, so every
        # existing quote caller keeps its shape. Only a customer's explicit
        # choice adds a hop; field spelling is validated by the shared Core and
        # per-model capability by B14, never guessed here (#3977).
        native_kwargs: dict[str, Any] = (
            {"model_parameters": dict(model_parameters)} if model_parameters else {}
        )
        return await self._complete_text(
            [dict(messages[0])],
            skill=quote_task,
            model=model,
            additional_system_context=bounded_context,
            max_retries=0,
            before_dispatch=self._prepare_registered_quote_dispatch,
            **native_kwargs,
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        skill: TaskMode | None = None,
        additional_system_context: str | None = None,
        attachments: tuple[ImageAttachment, ...] = (),
    ) -> dict[str, Any]:
        if len(attachments) > 1:
            raise ValueError("only one image attachment is supported")

        policy = _resolve_b62_policy(
            messages,
            require_executable=self.settings.runtime_mode != "mock",
        )
        resolved_skill = skill or get_task_mode()
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
                "skill": task_mode_public_metadata(resolved_skill),
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
