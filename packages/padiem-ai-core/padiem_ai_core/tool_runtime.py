from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
import json
import math
import re
import time
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping, Protocol

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError, ValidationError
except ModuleNotFoundError:
    Draft202012Validator = None  # type: ignore[assignment]
    SchemaError = Exception  # type: ignore[assignment,misc]
    ValidationError = Exception  # type: ignore[assignment,misc]

from .contracts import (
    AgentProfile,
    ApprovalPolicy,
    ErrorClass,
    RunStatus,
    ToolEvent,
    ToolSpec,
)

MAX_TOOL_ARGUMENT_BYTES = 65_536
MAX_TOOL_OUTPUT_BYTES = 262_144
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{name} must be a non-empty safe identifier")
    return value


def _identifier_tuple(name: str, values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a sequence of safe identifiers")
    normalized = tuple(_identifier(name, value) for value in tuple(values))
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must not contain duplicates")
    return normalized


def _normalize_json(value: Any, *, path: str = "value") -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must not contain NaN or Infinity")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            result[key] = _normalize_json(item, path=f"{path}.{key}")
        return result
    if isinstance(value, list):
        return [_normalize_json(item, path=f"{path}[]") for item in value]
    raise ValueError(f"{path} must contain JSON-compatible values only")


def _json_size(value: Any) -> int:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be JSON-compatible") from exc
    return len(encoded)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _bounded_json(value: Any, *, name: str, max_bytes: int, require_object: bool) -> Any:
    normalized = _normalize_json(value, path=name)
    if require_object and not isinstance(normalized, dict):
        raise ValueError(f"{name} must be a JSON object")
    if _json_size(normalized) > max_bytes:
        raise ValueError(f"{name} exceeds the configured size limit")
    return _freeze_json(normalized)


@dataclass(frozen=True, slots=True)
class ToolAuthorizationContext:
    app_id: str
    agent_id: str
    granted_auth_scopes: tuple[str, ...] = ()
    user_confirmed_tools: tuple[str, ...] = ()
    externally_authorized_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "app_id", _identifier("app_id", self.app_id))
        object.__setattr__(self, "agent_id", _identifier("agent_id", self.agent_id))
        object.__setattr__(
            self,
            "granted_auth_scopes",
            _identifier_tuple("granted_auth_scopes", self.granted_auth_scopes),
        )
        object.__setattr__(
            self,
            "user_confirmed_tools",
            _identifier_tuple("user_confirmed_tools", self.user_confirmed_tools),
        )
        object.__setattr__(
            self,
            "externally_authorized_tools",
            _identifier_tuple("externally_authorized_tools", self.externally_authorized_tools),
        )


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    tool_id: str
    arguments: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_id", _identifier("tool_id", self.tool_id))
        frozen = _bounded_json(
            self.arguments,
            name="arguments",
            max_bytes=MAX_TOOL_ARGUMENT_BYTES,
            require_object=True,
        )
        object.__setattr__(self, "arguments", frozen)

    def arguments_copy(self) -> dict[str, Any]:
        return _thaw_json(self.arguments)


class ToolHandler(Protocol):
    async def __call__(self, arguments: dict[str, Any]) -> Any: ...


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    tool_id: str
    output: Any
    event: ToolEvent

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_id", _identifier("tool_id", self.tool_id))
        frozen = _bounded_json(
            self.output,
            name="output",
            max_bytes=MAX_TOOL_OUTPUT_BYTES,
            require_object=False,
        )
        object.__setattr__(self, "output", frozen)
        if not isinstance(self.event, ToolEvent):
            raise ValueError("event must be ToolEvent")
        if self.event.tool_id != self.tool_id:
            raise ValueError("event.tool_id must match tool_id")

    def output_copy(self) -> Any:
        return _thaw_json(self.output)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "output": self.output_copy(),
            "event": self.event.to_public_dict(),
        }


class ToolRuntimeError(RuntimeError):
    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        event: ToolEvent | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.event = event

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.safe_message,
            "event": self.event.to_public_dict() if self.event is not None else None,
        }


@dataclass(frozen=True, slots=True)
class _RegisteredTool:
    spec: ToolSpec
    handler: Callable[[dict[str, Any]], Awaitable[Any]]
    validator: Draft202012Validator


class ToolRuntime:
    def __init__(self) -> None:
        self._registry: dict[str, _RegisteredTool] = {}

    @property
    def registered_tool_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._registry))

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if not isinstance(spec, ToolSpec):
            raise ValueError("spec must be ToolSpec")
        if spec.id in self._registry:
            raise ToolRuntimeError(
                "duplicate_tool_registration",
                "A tool with this identifier is already registered.",
            )
        if not callable(handler):
            raise ValueError("handler must be an async callable")
        call_target = handler if inspect.iscoroutinefunction(handler) else getattr(handler, "__call__", None)
        if call_target is None or not inspect.iscoroutinefunction(call_target):
            raise ValueError("handler must be an async callable")

        schema = _thaw_json(spec.input_schema)
        if Draft202012Validator is None:
            raise ImportError(
                "Tool Runtime requires the optional 'tools' dependency: "
                "install padiem-ai-core[tools]."
            )
        try:
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)
        except SchemaError as exc:
            raise ToolRuntimeError(
                "invalid_tool_schema",
                "The registered tool input schema is invalid.",
            ) from exc

        self._registry[spec.id] = _RegisteredTool(
            spec=spec,
            handler=handler,
            validator=validator,
        )

    def _error(
        self,
        tool_id: str,
        code: str,
        message: str,
        *,
        status: RunStatus,
        error_class: ErrorClass,
        duration_ms: int | None = None,
    ) -> ToolRuntimeError:
        return ToolRuntimeError(
            code,
            message,
            event=ToolEvent(
                tool_id=tool_id,
                status=status,
                duration_ms=duration_ms,
                error_class=error_class,
            ),
        )

    async def execute(
        self,
        invocation: ToolInvocation,
        agent_profile: AgentProfile,
        authorization: ToolAuthorizationContext,
    ) -> ToolExecutionResult:
        if not isinstance(invocation, ToolInvocation):
            raise ValueError("invocation must be ToolInvocation")
        if not isinstance(agent_profile, AgentProfile):
            raise ValueError("agent_profile must be AgentProfile")
        if not isinstance(authorization, ToolAuthorizationContext):
            raise ValueError("authorization must be ToolAuthorizationContext")

        registered = self._registry.get(invocation.tool_id)
        if registered is None:
            raise self._error(
                invocation.tool_id,
                "tool_not_registered",
                "The requested tool is not registered.",
                status=RunStatus.POLICY_BLOCKED,
                error_class=ErrorClass.POLICY_BLOCKED,
            )

        if authorization.agent_id != agent_profile.id:
            raise self._error(
                invocation.tool_id,
                "tool_agent_mismatch",
                "The authorization context does not match the active agent.",
                status=RunStatus.POLICY_BLOCKED,
                error_class=ErrorClass.POLICY_BLOCKED,
            )

        if invocation.tool_id not in agent_profile.allowed_tools:
            raise self._error(
                invocation.tool_id,
                "tool_not_allowed",
                "The active agent is not allowed to use this tool.",
                status=RunStatus.POLICY_BLOCKED,
                error_class=ErrorClass.POLICY_BLOCKED,
            )

        spec = registered.spec
        if spec.owner != "core" and spec.owner != authorization.app_id:
            raise self._error(
                invocation.tool_id,
                "tool_owner_mismatch",
                "The tool is not owned by this application boundary.",
                status=RunStatus.POLICY_BLOCKED,
                error_class=ErrorClass.POLICY_BLOCKED,
            )

        granted = frozenset(authorization.granted_auth_scopes)
        if any(scope not in granted for scope in spec.auth_scope):
            raise self._error(
                invocation.tool_id,
                "tool_auth_scope_missing",
                "The required authorization scope is not granted.",
                status=RunStatus.POLICY_BLOCKED,
                error_class=ErrorClass.POLICY_BLOCKED,
            )

        if (
            spec.approval_policy is ApprovalPolicy.USER_CONFIRMATION
            and invocation.tool_id not in authorization.user_confirmed_tools
        ):
            raise self._error(
                invocation.tool_id,
                "tool_user_confirmation_required",
                "This tool requires explicit user confirmation.",
                status=RunStatus.POLICY_BLOCKED,
                error_class=ErrorClass.POLICY_BLOCKED,
            )

        if (
            spec.approval_policy is ApprovalPolicy.EXTERNAL_AUTHORIZATION
            and invocation.tool_id not in authorization.externally_authorized_tools
        ):
            raise self._error(
                invocation.tool_id,
                "tool_external_authorization_required",
                "This tool requires external authorization.",
                status=RunStatus.POLICY_BLOCKED,
                error_class=ErrorClass.POLICY_BLOCKED,
            )

        arguments = invocation.arguments_copy()
        try:
            registered.validator.validate(arguments)
        except ValidationError as exc:
            raise self._error(
                invocation.tool_id,
                "invalid_tool_arguments",
                "Tool arguments did not match the registered input schema.",
                status=RunStatus.REJECTED,
                error_class=ErrorClass.TOOL_VALIDATION_ERROR,
            ) from exc

        started = time.monotonic()
        try:
            raw_output = await asyncio.wait_for(
                registered.handler(arguments),
                timeout=float(spec.timeout_seconds),
            )
        except asyncio.TimeoutError as exc:
            duration_ms = max(0, int((time.monotonic() - started) * 1000))
            raise self._error(
                invocation.tool_id,
                "tool_timeout",
                "The tool did not finish before its configured timeout.",
                status=RunStatus.TIMEOUT,
                error_class=ErrorClass.TOOL_RUNTIME_ERROR,
                duration_ms=duration_ms,
            ) from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            duration_ms = max(0, int((time.monotonic() - started) * 1000))
            raise self._error(
                invocation.tool_id,
                "tool_execution_failed",
                "The tool execution failed.",
                status=RunStatus.FAILED,
                error_class=ErrorClass.TOOL_RUNTIME_ERROR,
                duration_ms=duration_ms,
            ) from exc

        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        try:
            result = ToolExecutionResult(
                tool_id=invocation.tool_id,
                output=raw_output,
                event=ToolEvent(
                    tool_id=invocation.tool_id,
                    status=RunStatus.COMPLETED,
                    duration_ms=duration_ms,
                ),
            )
        except (TypeError, ValueError) as exc:
            raise self._error(
                invocation.tool_id,
                "invalid_tool_output",
                "The tool returned an invalid or oversized output.",
                status=RunStatus.FAILED,
                error_class=ErrorClass.TOOL_RUNTIME_ERROR,
                duration_ms=duration_ms,
            ) from exc
        return result
