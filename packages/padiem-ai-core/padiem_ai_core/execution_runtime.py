from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import re
import time
from types import MappingProxyType
from typing import Any, Protocol
import uuid

from .thought_filter import strip_thought_blocks

from .b14_execution import (
    B14ChatRequest,
    B14ExecutionError,
    B14ExecutionResult,
    B14RouteMetadata,
    B14RoutingOptions,
    NATIVE_MODEL_PARAMETER_FIELDS,
    _normalize_model_parameters,
)
from .contracts import (
    AgentProfile,
    ErrorClass,
    RunMetadata,
    RunStatus,
    UsageMetadata,
)
from .tool_channel import (
    TOOL_COMPLETED_STATUS,
    ToolCall,
    ToolDefinition,
    ToolResult,
    normalize_execution_event,
    normalize_tool_choice,
    normalize_tool_definitions,
    normalize_tool_results,
    normalize_turn_signature,
    parse_tool_calls,
    tool_result_messages,
)
from .dispatch_preinstruction import (
    render_dispatch_preinstruction,
    server_wall_clock,
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MESSAGE_ROLES = frozenset({"user", "assistant", "tool"})
_MODEL_POLICY_FIELDS = frozenset(
    {
        "model",
        "temperature",
        "max_retries",
        "product_tier",  # trusted product-side grade carried through Core to B14
        # #3977: explicitly requested provider-native overrides. Absent means
        # no such field is sent; there is no synthesized value in this layer.
        "model_parameters",
    }
)


class B14Executor(Protocol):
    async def execute(self, request: B14ChatRequest) -> B14ExecutionResult: ...


def _safe_identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{name} must be a non-empty safe identifier")
    return value


def _normalize_messages(
    messages: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    if isinstance(messages, (str, bytes)):
        raise ValueError("messages must be a sequence of message objects")
    items = tuple(messages)
    if not items:
        raise ValueError("messages must contain at least one item")

    normalized: list[Mapping[str, Any]] = []
    for index, message in enumerate(items):
        if not isinstance(message, Mapping):
            raise ValueError(f"messages[{index}] must be a mapping")
        role = message.get("role")
        if role not in _MESSAGE_ROLES:
            raise ValueError(
                f"messages[{index}].role must be user, assistant or tool"
            )
        fields = set(message)

        if role == "user":
            if fields != {"role", "content"}:
                raise ValueError(
                    f"messages[{index}] must contain only role and content"
                )
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError(
                    f"messages[{index}].content must be a non-empty string"
                )
            normalized.append(
                MappingProxyType({"role": role, "content": content.strip()})
            )
            continue

        if role == "assistant":
            # #5536: an assistant turn may carry the tool calls the model
            # requested, so the round trip can be replayed to the model.
            extra = fields - {"role", "content", "tool_calls", "signature"}
            if extra:
                raise ValueError(
                    f"messages[{index}] has unexpected fields: "
                    f"{', '.join(sorted(extra))}"
                )
            content = message.get("content")
            if content is not None and (
                not isinstance(content, str) or not content.strip()
            ):
                raise ValueError(
                    f"messages[{index}].content must be a non-empty string"
                )
            # #4727: the token a provider attached to this turn's answer text.
            signature = message.get("signature")
            if signature is not None:
                if content is None:
                    raise ValueError(
                        f"messages[{index}] signature needs the answer text it belongs to"
                    )
                signature = normalize_turn_signature(signature)
            turn: dict[str, Any] = {"role": "assistant"}
            if content is not None:
                turn["content"] = content.strip()
            if signature is not None:
                turn["signature"] = signature
            if "tool_calls" in message:
                calls = parse_tool_calls(message.get("tool_calls"))
                if not calls:
                    raise ValueError(
                        f"messages[{index}].tool_calls must not be empty"
                    )
                turn["tool_calls"] = [
                    call.to_provider_payload() for call in calls
                ]
            elif content is None:
                raise ValueError(
                    f"messages[{index}] must carry content or tool calls"
                )
            normalized.append(MappingProxyType(turn))
            continue

        # role == "tool": the result of one earlier tool call.
        extra = fields - {"role", "content", "tool_call_id", "name", "execution"}
        if extra:
            raise ValueError(
                f"messages[{index}] has unexpected fields: "
                f"{', '.join(sorted(extra))}"
            )
        call_id = message.get("tool_call_id")
        if not isinstance(call_id, str) or not call_id.strip():
            raise ValueError(
                f"messages[{index}].tool_call_id must be a non-empty string"
            )
        # #4727: the executor's own outcome travels with its result.
        execution = message.get("execution")
        if execution is not None:
            execution = dict(normalize_execution_event(execution))
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError(f"messages[{index}].content must be a string")
        if not content.strip() and (
            execution is None or execution["status"] == TOOL_COMPLETED_STATUS
        ):
            raise ValueError(
                f"messages[{index}].content must be a non-empty string"
            )
        result_message: dict[str, Any] = {
            "role": "tool",
            "tool_call_id": call_id.strip(),
            "content": content.strip(),
        }
        name = message.get("name")
        if isinstance(name, str) and name.strip():
            result_message["name"] = name.strip()
        if execution is not None:
            result_message["execution"] = execution
        normalized.append(MappingProxyType(result_message))
    return tuple(normalized)


def _normalize_additional_system_context(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("additional_system_context must be a string or None")
    text = value.strip()
    if not text:
        return None
    # #4379: the additional system context is not refused for its size.
    return text


def _compose_system_instruction(request: "ExecutionRequest") -> str | None:
    # #4465/#4468: every model call carries the one trusted per-dispatch server
    # clock, so "오늘/최신" is resolved from the executing server rather than the
    # model's training cutoff or a browser clock. The product's own instruction
    # is preserved and still follows it. The context is sampled exactly once
    # here, which is the single dispatch point for this runtime.
    parts: list[str] = [render_dispatch_preinstruction(server_wall_clock())]
    if request.agent.system_instruction is not None:
        parts.append(request.agent.system_instruction)
    if request.additional_system_context is not None:
        parts.append(request.additional_system_context)
    content = "\n\n".join(parts)
    # #4379: the composed system instruction carries no PADIEM byte total.
    return content


def _normalize_model_policy(
    agent: AgentProfile,
) -> tuple[str, float | None, B14RoutingOptions]:
    policy = agent.model_policy
    unknown = set(policy) - _MODEL_POLICY_FIELDS
    if unknown:
        raise ValueError(
            "unsupported model_policy fields: " + ", ".join(sorted(unknown))
        )

    # #2101: omitted model must fail closed. There is no implicit default in
    # any product-facing contract, and no automatic route exists at all.
    model = policy.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError(
            "model_policy.model is required and must be an explicit non-empty model route"
        )

    # No implied 0.2: omitted policy delegates to the selected provider.
    temperature = policy.get("temperature")
    if temperature is not None and (
        isinstance(temperature, bool) or not isinstance(temperature, (int, float))
    ):
        raise ValueError("model_policy.temperature must be numeric")

    max_retries = policy.get("max_retries")
    if max_retries is not None and (
        isinstance(max_retries, bool) or not isinstance(max_retries, int)
    ):
        raise ValueError("model_policy.max_retries must be an integer or None")

    routing = B14RoutingOptions(
        required_capabilities=(
            agent.required_capabilities if agent.required_capabilities else None
        ),
        max_retries=max_retries,
        product_tier=policy.get("product_tier"),
    )
    return model.strip(), (float(temperature) if temperature is not None else None), routing


def _native_model_parameters(agent: AgentProfile) -> Mapping[str, Any]:
    """Return the caller's explicit provider-native overrides, validated.

    #3977: this layer checks the closed wire vocabulary only. Whether the
    exact served model accepts a value is B14 capability authority and is
    re-validated on the request body at the gateway, so a value can never be
    invented, widened or quietly discarded here. An omitted policy key yields an
    empty mapping, which contributes nothing to the request.
    """
    raw = agent.model_policy.get("model_parameters")
    if raw is None:
        return MappingProxyType({})
    if not isinstance(raw, Mapping):
        raise ValueError("model_policy.model_parameters must be a mapping")
    unknown = {key for key in raw if key not in NATIVE_MODEL_PARAMETER_FIELDS}
    if unknown:
        raise ValueError(
            "unsupported model_policy.model_parameters fields: "
            + ", ".join(sorted(map(str, unknown)))
        )
    return _normalize_model_parameters(raw)


def _error_class_for_b14(code: str) -> ErrorClass:
    if code == "upstream_timeout":
        return ErrorClass.PROVIDER_TIMEOUT
    if code == "upstream_rate_limited":
        return ErrorClass.PROVIDER_RATE_LIMIT
    if code == "upstream_auth_error":
        return ErrorClass.AUTH_ERROR
    if code in {
        "malformed_upstream",
        "empty_upstream_answer",
        "upstream_response_too_large",
    }:
        return ErrorClass.PROVIDER_BAD_RESPONSE
    if code == "upstream_request_error":
        return ErrorClass.INPUT_ERROR
    return ErrorClass.INTERNAL_ERROR


def _safe_message_for_b14(code: str) -> str:
    messages = {
        "upstream_timeout": "Model execution timed out.",
        "upstream_rate_limited": "Model execution is temporarily rate limited.",
        "upstream_auth_error": "Model execution authorization failed.",
        "upstream_request_error": "Model execution request was rejected.",
        "upstream_server_error": "Model execution service failed.",
        "upstream_unavailable": "Model execution service is unavailable.",
        "upstream_response_too_large": "Model execution response exceeded the safety limit.",
        "malformed_upstream": "Model execution returned an invalid response.",
        "empty_upstream_answer": "Model execution returned no usable answer.",
    }
    return messages.get(code, "Model execution failed.")


def _selected_model(route: B14RouteMetadata) -> str | None:
    return route.actual_response_model or route.selected_model


def _selected_provider(route: B14RouteMetadata) -> str | None:
    provider = route.selected_provider
    if provider is None or not _IDENTIFIER_RE.fullmatch(provider):
        return None
    return provider


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    agent: AgentProfile
    messages: tuple[Mapping[str, Any], ...]
    session_id: str | None = None
    additional_system_context: str | None = None
    trace_id: str | None = None
    # #5536: the model-native tool channel. The declaration is empty for a
    # caller that does not use the channel, and then the request keeps its
    # exact pre-#5536 shape.
    tools: tuple[ToolDefinition, ...] = ()
    tool_choice: Mapping[str, Any] | str | None = None
    # The results of the tool calls the model requested in an earlier turn.
    # They travel back to the model as tool messages, so the model can answer
    # from the tool's outcome instead of from the call alone.
    tool_results: tuple[ToolResult, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.agent, AgentProfile):
            raise ValueError("agent must be AgentProfile")
        object.__setattr__(self, "messages", _normalize_messages(self.messages))
        if self.session_id is not None:
            object.__setattr__(
                self,
                "session_id",
                _safe_identifier("session_id", self.session_id),
            )
        object.__setattr__(
            self,
            "additional_system_context",
            _normalize_additional_system_context(self.additional_system_context),
        )
        if self.trace_id is not None:
            object.__setattr__(
                self,
                "trace_id",
                _safe_identifier("trace_id", self.trace_id),
            )
        # #5536: the tool declaration and the tool choice are normalized before
        # anything is written to the wire.
        tools = normalize_tool_definitions(self.tools)
        object.__setattr__(self, "tools", tools)
        if self.tool_choice is not None and not tools:
            raise ValueError("tool_choice requires a declared tool")
        object.__setattr__(
            self,
            "tool_choice",
            normalize_tool_choice(self.tool_choice, declared=tools),
        )
        tool_results = normalize_tool_results(self.tool_results)
        object.__setattr__(self, "tool_results", tool_results)
        # A tool result is an answer to one specific call. A result whose call
        # is not in this conversation would leave the model with a result it
        # cannot read, so it is refused here rather than at the provider.
        declared_names = {tool.name for tool in tools}
        call_ids: set[str] = set()
        called_names: set[str] = set()
        carried_results: set[str] = set()
        for message in self.messages:
            if message.get("role") == "assistant":
                for call in message.get("tool_calls", ()):
                    call_ids.add(call["id"])
                    called_names.add(call["function"]["name"])
            elif message.get("role") == "tool":
                carried_results.add(str(message.get("tool_call_id")))
                call_ids.add(str(message.get("tool_call_id")))
        if called_names and not declared_names:
            raise ValueError(
                "messages carry a tool call but no tool was declared"
            )
        undeclared = sorted(called_names - declared_names)
        if undeclared:
            raise ValueError(
                f"messages carry a tool call for an undeclared tool: {undeclared[0]}"
            )
        for result in tool_results:
            if result.tool_call_id in carried_results:
                raise ValueError(
                    "tool_results duplicate a tool result carried in messages"
                )
            if result.tool_call_id not in call_ids:
                raise ValueError(
                    "tool_results must answer a tool call carried in messages"
                )


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    answer: str
    route: B14RouteMetadata
    metadata: RunMetadata
    # #5536: the tool calls the model requested. When this is non-empty the
    # model answered with a call rather than with prose, so ``answer`` may be
    # empty. The empty tuple is the unchanged pre-#5536 result.
    tool_calls: tuple[ToolCall, ...] = ()

    def __post_init__(self) -> None:
        tool_calls = tuple(self.tool_calls or ())
        for call in tool_calls:
            if not isinstance(call, ToolCall):
                raise ValueError("tool_calls must carry ToolCall items")
        object.__setattr__(self, "tool_calls", tool_calls)
        if not isinstance(self.answer, str):
            raise ValueError("answer must be a non-empty string")
        # #5536: a tool call is a complete answer of its own, so the text may
        # be empty when the model answered with a call.
        if not strip_thought_blocks(self.answer).strip() and not tool_calls:
            raise ValueError("answer must be a non-empty string")
        object.__setattr__(self, "answer", strip_thought_blocks(self.answer).strip())
        if not isinstance(self.route, B14RouteMetadata):
            raise ValueError("route must be B14RouteMetadata")
        if not isinstance(self.metadata, RunMetadata):
            raise ValueError("metadata must be RunMetadata")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "route": self.route.to_public_dict(),
            "metadata": self.metadata.to_public_dict(),
            "tool_calls": [call.to_public_dict() for call in self.tool_calls],
        }


def _normalize_upstream_status_code(value: Any) -> int | None:
    # A malformed status may never replace the failure it describes: this is
    # reached from an ``except`` path, so raising here would mask the original
    # B14 error. Anything that is not an in-range HTTP status degrades to None.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not 100 <= value <= 599:
        return None
    return value


class ExecutionRuntimeError(RuntimeError):
    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        metadata: RunMetadata,
        retryable: bool = False,
        upstream_status_code: int | None = None,
        diagnostic_class: str | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = _safe_identifier("error code", code)
        self.safe_message = safe_message
        self.metadata = metadata
        self.retryable = bool(retryable)
        self.upstream_status_code = _normalize_upstream_status_code(
            upstream_status_code
        )
        self.diagnostic_class = (
            _safe_identifier("diagnostic class", diagnostic_class)
            if diagnostic_class is not None
            else None
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.safe_message,
            "retryable": self.retryable,
            "metadata": self.metadata.to_public_dict(),
        }


class ExecutionRuntime:
    def __init__(
        self,
        *,
        app_id: str,
        b14_client: B14Executor,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._app_id = _safe_identifier("app_id", app_id)
        execute = getattr(b14_client, "execute", None)
        if not callable(execute):
            raise ValueError("b14_client must expose async execute(request)")
        if not callable(clock):
            raise ValueError("clock must be callable")
        self._b14_client = b14_client
        self._clock = clock

    @property
    def app_id(self) -> str:
        return self._app_id

    def _trace_id(self, request: ExecutionRequest) -> str:
        return request.trace_id or f"run_{uuid.uuid4().hex[:24]}"

    def _duration_ms(self, started_at: float) -> int:
        elapsed = self._clock() - started_at
        return max(0, int(round(elapsed * 1000)))

    def _metadata(
        self,
        *,
        request: ExecutionRequest,
        trace_id: str,
        status: RunStatus,
        duration_ms: int,
        result: B14ExecutionResult | None = None,
        error_class: ErrorClass | None = None,
    ) -> RunMetadata:
        route = result.route if result is not None else B14RouteMetadata()
        return RunMetadata(
            trace_id=trace_id,
            app_id=self._app_id,
            agent_id=request.agent.id,
            session_id=request.session_id,
            status=status,
            provider=_selected_provider(route),
            model=_selected_model(route),
            duration_ms=duration_ms,
            usage=result.usage if result is not None else UsageMetadata(),
            error_class=error_class,
        )

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        if not isinstance(request, ExecutionRequest):
            raise ValueError("request must be ExecutionRequest")

        started_at = self._clock()
        trace_id = self._trace_id(request)

        if request.agent.allowed_tools and not request.tools:
            # #5536: the tool channel is now available. An agent profile that
            # still declares tools while the request declares none is asking
            # for native tool execution this contract cannot serve, so it is
            # refused before B14 is called.
            metadata = self._metadata(
                request=request,
                trace_id=trace_id,
                status=RunStatus.POLICY_BLOCKED,
                duration_ms=self._duration_ms(started_at),
                error_class=ErrorClass.POLICY_BLOCKED,
            )
            raise ExecutionRuntimeError(
                "native_tools_unsupported",
                "Model-native tool execution is not available in the current B14 contract.",
                metadata=metadata,
            )

        if request.agent.allowed_tools and request.tools:
            # A declared agent allowlist narrows what the model may be told to
            # call. A tool outside it is refused before B14 is called.
            allowed = set(request.agent.allowed_tools)
            outside = sorted(
                tool.name for tool in request.tools if tool.name not in allowed
            )
            if outside:
                metadata = self._metadata(
                    request=request,
                    trace_id=trace_id,
                    status=RunStatus.POLICY_BLOCKED,
                    duration_ms=self._duration_ms(started_at),
                    error_class=ErrorClass.POLICY_BLOCKED,
                )
                raise ExecutionRuntimeError(
                    "tool_not_allowed",
                    "A declared tool is outside the agent tool allowlist.",
                    metadata=metadata,
                )

        try:
            system_instruction = _compose_system_instruction(request)
            model, temperature, routing = _normalize_model_policy(request.agent)
            model_parameters = _native_model_parameters(request.agent)
            messages = request.messages
            if system_instruction is not None:
                messages = (
                    {"role": "system", "content": system_instruction},
                    *messages,
                )
            # #5536: the tool results travel back to the model as tool
            # messages, so the model's next answer can read the tool's
            # outcome instead of the call alone.
            if request.tool_results:
                messages = (*messages, *tool_result_messages(request.tool_results))
            b14_request = B14ChatRequest(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=request.agent.max_tokens,
                routing=routing,
                model_parameters=model_parameters,
                tools=request.tools,
                tool_choice=request.tool_choice,
            )
        except ValueError:
            metadata = self._metadata(
                request=request,
                trace_id=trace_id,
                status=RunStatus.REJECTED,
                duration_ms=self._duration_ms(started_at),
                error_class=ErrorClass.INPUT_ERROR,
            )
            raise ExecutionRuntimeError(
                "invalid_execution_request",
                "Execution request or agent model policy is invalid.",
                metadata=metadata,
            ) from None

        try:
            result = await self._b14_client.execute(b14_request)
        except B14ExecutionError as exc:
            error_class = _error_class_for_b14(exc.code)
            status = (
                RunStatus.TIMEOUT
                if error_class is ErrorClass.PROVIDER_TIMEOUT
                else RunStatus.FAILED
            )
            metadata = self._metadata(
                request=request,
                trace_id=trace_id,
                status=status,
                duration_ms=self._duration_ms(started_at),
                error_class=error_class,
            )
            raise ExecutionRuntimeError(
                exc.code,
                _safe_message_for_b14(exc.code),
                metadata=metadata,
                retryable=exc.retryable,
                upstream_status_code=exc.upstream_status_code,
                diagnostic_class=exc.diagnostic_class,
            ) from None
        except Exception:
            metadata = self._metadata(
                request=request,
                trace_id=trace_id,
                status=RunStatus.FAILED,
                duration_ms=self._duration_ms(started_at),
                error_class=ErrorClass.INTERNAL_ERROR,
            )
            raise ExecutionRuntimeError(
                "execution_failed",
                "Model execution failed.",
                metadata=metadata,
            ) from None

        if not isinstance(result, B14ExecutionResult):
            metadata = self._metadata(
                request=request,
                trace_id=trace_id,
                status=RunStatus.FAILED,
                duration_ms=self._duration_ms(started_at),
                error_class=ErrorClass.INTERNAL_ERROR,
            )
            raise ExecutionRuntimeError(
                "invalid_execution_result",
                "Model execution returned an invalid result contract.",
                metadata=metadata,
            ) from None

        metadata = self._metadata(
            request=request,
            trace_id=trace_id,
            status=RunStatus.COMPLETED,
            duration_ms=self._duration_ms(started_at),
            result=result,
        )
        return ExecutionResult(
            answer=result.answer,
            route=result.route,
            metadata=metadata,
            # #5536: a tool call is carried to the caller, which runs the tool
            # and returns its result through the same channel.
            tool_calls=result.tool_calls,
        )