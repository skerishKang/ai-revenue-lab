"""The single Engine-safe Tool runtime projection for trusted cross-runtime products.

Core owns every Tool semantic: execution, authorization, registry identity,
schema validation, approval blocking, timeout, cancellation, resource bounds
and lifecycle event shape (``padiem_ai_core.tool_runtime``,
``padiem_ai_core.tool_registry``, ``padiem_ai_core.tool_resource_policy``,
``padiem_ai_core.tool_lifecycle``, ``padiem_ai_core.agent_approval``).
The Engine owns only this bounded transport projection:

* tool authority is minted exclusively from trusted server-side bindings
  (:class:`EngineToolBinding`); caller JSON can never create or widen a
  ``ToolAuthorizationContext``, a registry entry or an approval grant;
* execution always goes through the existing Core ``ToolRuntime.execute()``;
  the Engine never registers a handler and never defines a second registry or
  runtime (``ENGINE_SECOND_TOOL_RUNTIME = NO``);
* only bounded/redacted Product-safe fields cross the Engine boundary; private
  tool arguments are never echoed and secret-shaped output values are redacted;
* lifecycle events can only be constructed from a genuine Core ``ToolEvent``
  produced by ``ToolRuntime`` — never from model or provider output;
* provider function-calling wire vocabulary (``tool_calls``, ``function_call``,
  ``parameters`` schemas, provider tool ids) is rejected at the Engine edge and
  stays behind Core/B14 ownership.

``execute``/``stream`` model paths are unchanged by design: Core's
``ExecutionRuntime``/``StreamingExecutionRuntime`` fail closed on
``native_tools_unsupported`` and the Engine strips ``allowed_tools`` from every
caller-supplied agent, so model output can never become tool authority here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import re
from typing import Any

from padiem_ai_core.agent_definition import BoundedAgentDefinition
from padiem_ai_core.agent_profile_adapter import CompiledAgentProfile
from padiem_ai_core.contracts import RunStatus, ToolEvent
from padiem_ai_core.tool_lifecycle import ToolLifecycleEvent, ToolLifecycleKind
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistryError, ToolRegistrySnapshot
from padiem_ai_core.tool_resource_policy import (
    EffectiveToolResources,
    ToolResourcePolicy,
    resolve_tool_resources,
)
from padiem_ai_core.tool_runtime import (
    MAX_TOOL_ARGUMENT_BYTES,
    ToolAuthorizationContext,
    ToolRuntime,
)

TOOL_EXECUTE_PATH = "/internal/v1/tools/execute"
TOOL_RESUME_PATH = "/internal/v1/tools/resume"
TOOL_CANCEL_PATH = "/internal/v1/tools/cancel"

ENGINE_TOOL_CONTRACT_FAMILY = "padiem.engine.tools"
ENGINE_TOOL_CONTRACT_MAJOR = 1
ENGINE_TOOL_CONTRACT_VERSION = f"{ENGINE_TOOL_CONTRACT_FAMILY}/{ENGINE_TOOL_CONTRACT_MAJOR}.0"

MAX_PUBLIC_TOOL_OUTPUT_BYTES = 32_768
MAX_PUBLIC_OUTPUT_STRING_CHARS = 2_048
MAX_PUBLIC_OUTPUT_NODES = 512
MAX_PUBLIC_OUTPUT_LIST_ITEMS = 64
MAX_BOUND_TOOL_AGENTS = 64
MAX_WIRE_TOOL_ARGUMENTS_BYTES = 64 * 1024
MAX_PENDING_TOOL_CONTINUATIONS = 256

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CANONICAL_AGENT_ID_RE = re.compile(
    r"^agent:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$"
)
_CANONICAL_TOOL_ID_RE = re.compile(
    r"^tool:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$"
)

# Provider function-calling wire vocabulary is not Engine authority. These keys
# are rejected explicitly (not just by "unsupported field") so the leak test is
# unambiguous: PROVIDER_FUNCTION_CALL_WIRE_IN_ENGINE = NO.
_PROVIDER_WIRE_KEYS = frozenset(
    {
        "tool_calls",
        "toolCalls",
        "tool_call",
        "function_call",
        "functionCall",
        "functions",
        "tools",
        "parameters",
        "allowed_tools",
        "tool_choice",
        "native_tools",
    }
)

# Caller JSON can never describe tool authority, authorization or approval
# state. These keys are rejected explicitly at the Engine edge so a caller
# cannot even attempt to mint or widen authority through the request body.
_AUTHORITY_MINTING_KEYS = frozenset(
    {
        "tool_authorization",
        "authorization",
        "granted_auth_scopes",
        "user_confirmed_tools",
        "externally_authorized_tools",
        "approved",
        "approval_grant",
        "self_approved",
        "registry",
    }
)

_SECRET_KEY_RE = re.compile(
    r"(?i)(api[-_]?key|access[-_]?key|client[-_]?secret|secret|token|pass(word|wd)"
    r"|credential|authorization|cookie|private[-_]?(key|data)|session[-_]?id"
    r"|signature|otp|pin)"
)
REDACTED_TOOL_VALUE = "[redacted]"

_EXECUTE_ALLOWED = _AUTHORITY_MINTING_KEYS | _PROVIDER_WIRE_KEYS | frozenset(
    {"app_id", "agent_id", "tool_id", "arguments"}
)


class EngineToolProjectionError(ValueError):
    """Fail-closed Engine tool projection error carrying safe, bounded info."""

    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("tool projection error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


def _require_identifier(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise EngineToolProjectionError(
            "invalid_tool_request",
            f"{name} must be a bounded safe identifier.",
        )
    return value


def json_size(value: Any) -> int:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EngineToolProjectionError(
            "invalid_tool_arguments",
            "Tool arguments must contain JSON-compatible values only.",
        ) from exc
    return len(encoded)


@dataclass(frozen=True, slots=True)
class TrustedToolAuthority:
    """Server-resolved authority for one canonical Agent inside one app."""

    canonical_agent_id: str
    definition: BoundedAgentDefinition
    compiled: CompiledAgentProfile
    authorization: ToolAuthorizationContext

    def __post_init__(self) -> None:
        if not isinstance(self.definition, BoundedAgentDefinition):
            raise EngineToolProjectionError(
                "invalid_tool_binding",
                "Trusted authority requires a Core BoundedAgentDefinition.",
                status_code=503,
            )
        if not isinstance(self.compiled, CompiledAgentProfile):
            raise EngineToolProjectionError(
                "invalid_tool_binding",
                "Trusted authority requires a Core CompiledAgentProfile.",
                status_code=503,
            )
        if not isinstance(self.authorization, ToolAuthorizationContext):
            raise EngineToolProjectionError(
                "tool_authorization_mismatch",
                "Trusted authority requires a Core ToolAuthorizationContext.",
                status_code=403,
            )


@dataclass(frozen=True, slots=True)
class EngineToolBinding:
    """Trusted, server-provisioned binding of Core ToolRuntime to one app.

    Every field is server-owned deployment state. The Engine constructs the
    binding value, never the caller. ``authorization_provider`` is the only
    minting point for ``ToolAuthorizationContext`` and it may read server
    grant state (control-plane decisions included); it must never be bound to
    request JSON.
    """

    app_id: str
    tool_runtime: ToolRuntime
    registry: ToolRegistrySnapshot
    authorities: Mapping[str, TrustedToolAuthority]
    authorization_provider: Callable[[str], ToolAuthorizationContext] | None = None
    resource_policy: ToolResourcePolicy | None = None

    def __post_init__(self) -> None:
        _require_identifier("app_id", self.app_id)
        # Identity gate: the runtime must be the existing Core ToolRuntime.
        # The Engine must not wrap, subclass or replace it with a second
        # runtime implementation.
        if type(self.tool_runtime) is not ToolRuntime:
            raise EngineToolProjectionError(
                "invalid_tool_binding",
                "Engine tool binding must reuse the Core ToolRuntime instance.",
                status_code=503,
            )
        if not isinstance(self.registry, ToolRegistrySnapshot):
            raise EngineToolProjectionError(
                "invalid_tool_binding",
                "Engine tool binding must reuse the Core ToolRegistrySnapshot.",
                status_code=503,
            )
        if not isinstance(self.authorities, Mapping) or isinstance(self.authorities, (str, bytes)):
            raise EngineToolProjectionError(
                "invalid_tool_binding",
                "Engine tool binding authorities must be a mapping.",
                status_code=503,
            )
        if len(self.authorities) > MAX_BOUND_TOOL_AGENTS:
            raise EngineToolProjectionError(
                "invalid_tool_binding",
                "Engine tool binding exceeds the bounded agent authority count.",
                status_code=503,
            )
        for key, authority in dict(self.authorities).items():
            if not isinstance(key, str) or not _CANONICAL_AGENT_ID_RE.fullmatch(key):
                raise EngineToolProjectionError(
                    "invalid_tool_binding",
                    "Authority keys must be canonical versioned Agent ids.",
                    status_code=503,
                )
            if not isinstance(authority, TrustedToolAuthority):
                raise EngineToolProjectionError(
                    "invalid_tool_binding",
                    "Authority values must be TrustedToolAuthority values.",
                    status_code=503,
                )
            if authority.canonical_agent_id != key:
                raise EngineToolProjectionError(
                    "invalid_tool_binding",
                    "Authority canonical agent id does not match its binding key.",
                    status_code=503,
                )
            if authority.definition.agent_id != key:
                raise EngineToolProjectionError(
                    "invalid_tool_binding",
                    "Trusted definition does not belong to the bound Agent.",
                    status_code=503,
                )
            if authority.compiled.canonical_agent_id != key:
                raise EngineToolProjectionError(
                    "invalid_tool_binding",
                    "Compiled profile does not belong to the bound Agent.",
                    status_code=503,
                )
            if self.app_id != authority.authorization.app_id:
                raise EngineToolProjectionError(
                    "invalid_tool_binding",
                    "Authority application id does not match the binding app.",
                    status_code=503,
                )
            if authority.compiled.runtime_profile.id != authority.authorization.agent_id:
                raise EngineToolProjectionError(
                    "tool_authorization_mismatch",
                    "Authorization agent id does not match the compiled profile.",
                    status_code=403,
                )
        if self.authorization_provider is not None and not callable(self.authorization_provider):
            raise EngineToolProjectionError(
                "invalid_tool_binding",
                "authorization_provider must be callable.",
                status_code=503,
            )
        if self.resource_policy is not None and not isinstance(
            self.resource_policy, ToolResourcePolicy
        ):
            raise EngineToolProjectionError(
                "invalid_tool_binding",
                "resource_policy must be a Core ToolResourcePolicy.",
                status_code=503,
            )

    def resolve_authority(self, canonical_agent_id: str) -> TrustedToolAuthority:
        """Resolve server-trusted authority; unknown Agents fail closed."""
        if not isinstance(canonical_agent_id, str) or not _CANONICAL_AGENT_ID_RE.fullmatch(
            canonical_agent_id
        ):
            raise EngineToolProjectionError(
                "tool_agent_not_bound",
                "The requested Agent has no trusted tool binding.",
                status_code=403,
            )
        authority = dict(self.authorities).get(canonical_agent_id)
        if authority is None:
            raise EngineToolProjectionError(
                "tool_agent_not_bound",
                "The requested Agent has no trusted tool binding.",
                status_code=403,
            )
        if self.authorization_provider is None:
            return authority
        authorization = self.authorization_provider(canonical_agent_id)
        if not isinstance(authorization, ToolAuthorizationContext):
            raise EngineToolProjectionError(
                "tool_authorization_mismatch",
                "Tool authorization provider returned an invalid authority.",
                status_code=403,
            )
        if authorization.app_id != self.app_id:
            raise EngineToolProjectionError(
                "tool_authorization_mismatch",
                "Tool authorization does not belong to this application boundary.",
                status_code=403,
            )
        if authorization.agent_id != authority.compiled.runtime_profile.id:
            raise EngineToolProjectionError(
                "tool_authorization_mismatch",
                "Tool authorization does not match the compiled Agent profile.",
                status_code=403,
            )
        return TrustedToolAuthority(
            canonical_agent_id=authority.canonical_agent_id,
            definition=authority.definition,
            compiled=authority.compiled,
            authorization=authorization,
        )

    def resolve_tool(self, canonical_tool_id: str) -> RegisteredTool:
        """Resolve a canonical Tool through the Core registry authority."""
        try:
            return self.registry.get(canonical_tool_id)
        except ToolRegistryError as exc:
            raise EngineToolProjectionError(
                "tool_not_registered",
                "The requested Tool is not present in the trusted registry.",
                status_code=403,
            ) from exc
        except (TypeError, ValueError) as exc:
            raise EngineToolProjectionError(
                "invalid_tool_request",
                "tool_id must be a canonical versioned Tool id.",
            ) from exc

    def effective_resources(self, entry: RegisteredTool) -> EffectiveToolResources:
        """Reuse the Core narrowing-only resource policy for one resolved Tool."""
        try:
            return resolve_tool_resources(entry.runtime_spec, self.resource_policy)
        except ValueError as exc:
            raise EngineToolProjectionError(
                "invalid_tool_binding",
                "The effective Tool resource bounds are invalid.",
                status_code=503,
            ) from exc


@dataclass(frozen=True, slots=True)
class ToolExecutionWire:
    """Parsed, still-untrusted request data. Authority never comes from here."""

    app_id: str
    agent_id: str
    tool_id: str
    arguments: Mapping[str, Any]


def _reject_wired_authority(data: Mapping[str, Any]) -> None:
    keys = set(data)
    provider = keys & _PROVIDER_WIRE_KEYS
    if provider:
        raise EngineToolProjectionError(
            "provider_tool_wire_rejected",
            "Provider function-calling wire is not part of the Engine tool contract.",
        )
    minted = keys & _AUTHORITY_MINTING_KEYS
    if minted:
        raise EngineToolProjectionError(
            "caller_minted_tool_authority_rejected",
            "Caller-supplied tool authority is rejected; authority is server-owned.",
        )


def parse_tool_execution_request(payload: Any) -> ToolExecutionWire:
    """Parse one bounded tool execution request; unknown fields fail closed."""
    if not isinstance(payload, Mapping):
        raise EngineToolProjectionError("invalid_tool_request", "Request body must be an object.")
    data = dict(payload)
    _reject_wired_authority(data)
    unknown = set(data) - _EXECUTE_ALLOWED
    if unknown:
        raise EngineToolProjectionError(
            "invalid_tool_request",
            "Request contains unsupported fields.",
        )
    app_id = _require_identifier("app_id", data.get("app_id"))
    agent_id = data.get("agent_id")
    if not isinstance(agent_id, str) or not _CANONICAL_AGENT_ID_RE.fullmatch(agent_id):
        raise EngineToolProjectionError(
            "invalid_tool_request",
            "agent_id must be a canonical versioned Agent id.",
        )
    tool_id = data.get("tool_id")
    if not isinstance(tool_id, str) or not _CANONICAL_TOOL_ID_RE.fullmatch(tool_id):
        raise EngineToolProjectionError(
            "invalid_tool_request",
            "tool_id must be a canonical versioned Tool id.",
        )
    arguments = data.get("arguments", {})
    if not isinstance(arguments, Mapping) or isinstance(arguments, (str, bytes)):
        raise EngineToolProjectionError(
            "invalid_tool_request",
            "arguments must be a JSON object.",
        )
    arguments = dict(arguments)
    if json_size(arguments) > MAX_TOOL_ARGUMENT_BYTES:
        raise EngineToolProjectionError(
            "tool_arguments_too_large",
            "Tool arguments exceed the bounded Core argument ceiling.",
        )
    return ToolExecutionWire(app_id=app_id, agent_id=agent_id, tool_id=tool_id, arguments=arguments)


def parse_tool_continuation_ref(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("cont_") or len(value) > 128:
        raise EngineToolProjectionError(
            "invalid_continuation",
            "Continuation reference is invalid.",
            status_code=409,
        )
    return value


def _sanitize_output_key(key: Any) -> str:
    if not isinstance(key, str) or not key:
        return "field"
    if len(key) <= 128 and _IDENTIFIER_RE.fullmatch(key):
        return key
    return "field"


def _redact_recursive(value: Any, state: dict[str, int | bool]) -> Any:
    if state["nodes"] >= MAX_PUBLIC_OUTPUT_NODES:
        state["truncated"] = True
        return None
    state["nodes"] += 1
    if isinstance(value, Mapping):
        projected: dict[str, Any] = {}
        for key, item in list(value.items()):
            safe_key = _sanitize_output_key(key)
            if isinstance(key, str) and _SECRET_KEY_RE.search(key):
                projected[safe_key] = REDACTED_TOOL_VALUE
                continue
            projected[safe_key] = _redact_recursive(item, state)
        return projected
    if isinstance(value, (list, tuple)):
        items = list(value)[:MAX_PUBLIC_OUTPUT_LIST_ITEMS]
        if len(list(value)) > MAX_PUBLIC_OUTPUT_LIST_ITEMS:
            state["truncated"] = True
        return [_redact_recursive(item, state) for item in items]
    if isinstance(value, str):
        if len(value) > MAX_PUBLIC_OUTPUT_STRING_CHARS:
            state["truncated"] = True
            return value[:MAX_PUBLIC_OUTPUT_STRING_CHARS] + "[truncated]"
        return value
    if isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if value is None:
        return None
    return REDACTED_TOOL_VALUE


def project_redacted_tool_output(output: Any) -> tuple[Any, bool]:
    """Project one settled Core tool output through the single redaction filter.

    Values under secret-shaped keys never cross the Engine boundary
    (TOOL_RESULT_SECRET_LEAK = 0) and the public projection is bounded well
    under the Core output ceiling.
    """
    if isinstance(output, Mapping):
        source: Any = dict(output)
    elif isinstance(output, (list, tuple)):
        source = [dict(item) if isinstance(item, Mapping) else item for item in output]
    else:
        source = output
    state: dict[str, int | bool] = {"nodes": 0, "truncated": False}
    projected = _redact_recursive(source, state)
    try:
        size = json_size(projected)
    except EngineToolProjectionError:
        return None, True
    if size > MAX_PUBLIC_TOOL_OUTPUT_BYTES:
        return None, True
    return projected, bool(state["truncated"])


_LIFECYCLE_BY_STATUS: dict[RunStatus, ToolLifecycleKind] = {
    RunStatus.TOOL_RUNNING: ToolLifecycleKind.STARTED,
    RunStatus.COMPLETED: ToolLifecycleKind.COMPLETED,
    RunStatus.FAILED: ToolLifecycleKind.FAILED,
    RunStatus.REJECTED: ToolLifecycleKind.FAILED,
    RunStatus.TIMEOUT: ToolLifecycleKind.TIMED_OUT,
    RunStatus.POLICY_BLOCKED: ToolLifecycleKind.UNAVAILABLE,
}


def project_core_tool_lifecycle(
    event: ToolEvent,
    *,
    run_id: str,
    event_id: str,
    sequence: int,
    canonical_tool_id: str,
    error_code: str | None = None,
) -> ToolLifecycleEvent:
    """Normalize ONE genuine Core ToolEvent into the Core lifecycle envelope.

    The only accepted source is a ``ToolEvent`` value produced by Core
    ``ToolRuntime`` execution results or ``ToolRuntimeError.event``. Model or
    provider output can never reach this function through an Engine path, so
    synthetic tool events are structurally impossible
    (TOOL_EVENT_AUTHORITY = Core ToolRuntime only).
    """
    if not isinstance(event, ToolEvent):
        raise EngineToolProjectionError(
            "invalid_tool_event_source",
            "Tool lifecycle events may only be projected from Core runtime events.",
            status_code=500,
        )
    kind = _LIFECYCLE_BY_STATUS.get(event.status)
    if kind is None:
        raise EngineToolProjectionError(
            "invalid_tool_event_source",
            "The Core tool event status has no normalized lifecycle mapping.",
            status_code=500,
        )
    try:
        return ToolLifecycleEvent(
            event_id=event_id,
            run_id=run_id,
            kind=kind,
            tool_id=canonical_tool_id,
            sequence=sequence,
            duration_ms=event.duration_ms,
            error_code=error_code,
        )
    except ValueError as exc:
        raise EngineToolProjectionError(
            "invalid_tool_event_source",
            "The projected Core tool event violates the lifecycle contract.",
            status_code=500,
        ) from exc
