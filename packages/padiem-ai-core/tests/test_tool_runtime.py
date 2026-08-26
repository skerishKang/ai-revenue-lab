from __future__ import annotations

import asyncio
import json

import pytest

from padiem_ai_core import (
    AgentProfile,
    ApprovalPolicy,
    ErrorClass,
    RunStatus,
    ToolSideEffect,
    ToolSpec,
)
from padiem_ai_core.tool_runtime import (
    MAX_TOOL_ARGUMENT_BYTES,
    MAX_TOOL_OUTPUT_BYTES,
    ToolAuthorizationContext,
    ToolExecutionResult,
    ToolInvocation,
    ToolRuntime,
    ToolRuntimeError,
)


def run(coro):
    return asyncio.run(coro)


def profile(*allowed_tools: str, agent_id: str = "agent-1") -> AgentProfile:
    return AgentProfile(
        id=agent_id,
        title="Agent",
        description="Tool runtime test agent",
        system_instruction="Use only allowed tools.",
        task_type="general",
        optimize_for="balanced",
        max_tokens=500,
        allowed_tools=tuple(allowed_tools),
    )


def spec(
    tool_id: str = "core.echo",
    *,
    owner: str = "core",
    side_effect: ToolSideEffect = ToolSideEffect.READ,
    approval: ApprovalPolicy = ApprovalPolicy.NOT_REQUIRED,
    auth_scope: tuple[str, ...] = (),
    input_schema=None,
    timeout_seconds: float = 1.0,
) -> ToolSpec:
    return ToolSpec(
        id=tool_id,
        title="Tool",
        description="Tool runtime test tool",
        owner=owner,
        side_effect=side_effect,
        approval_policy=approval,
        auth_scope=auth_scope,
        input_schema=input_schema
        if input_schema is not None
        else {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        timeout_seconds=timeout_seconds,
    )


def auth(
    *,
    app_id: str = "padiem-chat",
    agent_id: str = "agent-1",
    scopes=(),
    confirmed=(),
    external=(),
) -> ToolAuthorizationContext:
    return ToolAuthorizationContext(
        app_id=app_id,
        agent_id=agent_id,
        granted_auth_scopes=tuple(scopes),
        user_confirmed_tools=tuple(confirmed),
        externally_authorized_tools=tuple(external),
    )


def assert_error(
    error: ToolRuntimeError,
    *,
    code: str,
    status: RunStatus,
    error_class: ErrorClass,
) -> None:
    assert error.code == code
    assert error.event is not None
    assert error.event.status is status
    assert error.event.error_class is error_class


def test_authorization_context_is_copy_safe_and_immutable() -> None:
    scopes = ["tree.read", "tree.write"]
    confirmed = ["lovetree.create"]
    external = ["billing.charge"]
    context = ToolAuthorizationContext(
        app_id="lovetree",
        agent_id="tree-builder",
        granted_auth_scopes=scopes,  # type: ignore[arg-type]
        user_confirmed_tools=confirmed,  # type: ignore[arg-type]
        externally_authorized_tools=external,  # type: ignore[arg-type]
    )
    scopes.append("admin.all")
    confirmed.clear()
    external.clear()
    assert context.granted_auth_scopes == ("tree.read", "tree.write")
    assert context.user_confirmed_tools == ("lovetree.create",)
    assert context.externally_authorized_tools == ("billing.charge",)
    with pytest.raises(Exception):
        context.app_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"app_id": "bad app", "agent_id": "agent"},
        {"app_id": "app", "agent_id": "bad agent"},
        {"app_id": "app", "agent_id": "agent", "granted_auth_scopes": ("x", "x")},
        {"app_id": "app", "agent_id": "agent", "user_confirmed_tools": ("x", "x")},
        {"app_id": "app", "agent_id": "agent", "externally_authorized_tools": ("x", "x")},
    ],
)
def test_authorization_context_rejects_invalid_identifiers_and_duplicates(kwargs) -> None:
    with pytest.raises(ValueError):
        ToolAuthorizationContext(**kwargs)


def test_invocation_copies_and_freezes_arguments() -> None:
    arguments = {"value": "hello", "nested": {"items": [1, 2]}}
    invocation = ToolInvocation("core.echo", arguments)
    arguments["value"] = "mutated"
    arguments["nested"]["items"].append(3)  # type: ignore[index,union-attr]
    assert invocation.arguments_copy() == {
        "value": "hello",
        "nested": {"items": [1, 2]},
    }
    with pytest.raises(TypeError):
        invocation.arguments["value"] = "x"  # type: ignore[index]


@pytest.mark.parametrize("arguments", [[], "text", 1, None])
def test_invocation_rejects_non_object_root(arguments) -> None:
    with pytest.raises(ValueError, match="JSON object"):
        ToolInvocation("core.echo", arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "arguments",
    [
        {"x": float("nan")},
        {"x": float("inf")},
        {"x": float("-inf")},
        {"x": object()},
        {1: "bad-key"},
        {"x": (1, 2)},
    ],
)
def test_invocation_rejects_non_json_values(arguments) -> None:
    with pytest.raises(ValueError):
        ToolInvocation("core.echo", arguments)  # type: ignore[arg-type]


def test_invocation_rejects_oversized_arguments() -> None:
    with pytest.raises(ValueError, match="size limit"):
        ToolInvocation("core.echo", {"value": "x" * (MAX_TOOL_ARGUMENT_BYTES + 1)})


def test_registers_async_handler_and_lists_ids() -> None:
    runtime = ToolRuntime()

    async def handler(arguments):
        return arguments

    runtime.register(spec("core.echo"), handler)
    runtime.register(spec("core.read"), handler)
    assert runtime.registered_tool_ids == ("core.echo", "core.read")


def test_duplicate_registration_fails_closed() -> None:
    runtime = ToolRuntime()

    async def handler(arguments):
        return arguments

    runtime.register(spec(), handler)
    with pytest.raises(ToolRuntimeError) as info:
        runtime.register(spec(), handler)
    assert info.value.code == "duplicate_tool_registration"


def test_registration_rejects_sync_handler() -> None:
    runtime = ToolRuntime()

    def handler(arguments):
        return arguments

    with pytest.raises(ValueError, match="async callable"):
        runtime.register(spec(), handler)  # type: ignore[arg-type]


def test_registration_rejects_invalid_json_schema() -> None:
    runtime = ToolRuntime()

    async def handler(arguments):
        return arguments

    broken = spec(input_schema={"type": "definitely-not-a-json-schema-type"})
    with pytest.raises(ToolRuntimeError) as info:
        runtime.register(broken, handler)
    assert info.value.code == "invalid_tool_schema"
    assert runtime.registered_tool_ids == ()


def test_unknown_tool_calls_handler_zero_times() -> None:
    runtime = ToolRuntime()
    calls = 0

    async def handler(arguments):
        nonlocal calls
        calls += 1
        return arguments

    runtime.register(spec("core.echo"), handler)
    with pytest.raises(ToolRuntimeError) as info:
        run(
            runtime.execute(
                ToolInvocation("core.missing", {"value": "x"}),
                profile("core.missing"),
                auth(),
            )
        )
    assert_error(
        info.value,
        code="tool_not_registered",
        status=RunStatus.POLICY_BLOCKED,
        error_class=ErrorClass.POLICY_BLOCKED,
    )
    assert calls == 0


def test_agent_mismatch_calls_handler_zero_times() -> None:
    runtime = ToolRuntime()
    calls = 0

    async def handler(arguments):
        nonlocal calls
        calls += 1
        return arguments

    runtime.register(spec(), handler)
    with pytest.raises(ToolRuntimeError) as info:
        run(runtime.execute(ToolInvocation("core.echo", {"value": "x"}), profile("core.echo"), auth(agent_id="other-agent")))
    assert_error(
        info.value,
        code="tool_agent_mismatch",
        status=RunStatus.POLICY_BLOCKED,
        error_class=ErrorClass.POLICY_BLOCKED,
    )
    assert calls == 0


def test_agent_allowlist_denial_calls_handler_zero_times() -> None:
    runtime = ToolRuntime()
    calls = 0

    async def handler(arguments):
        nonlocal calls
        calls += 1
        return arguments

    runtime.register(spec(), handler)
    with pytest.raises(ToolRuntimeError) as info:
        run(runtime.execute(ToolInvocation("core.echo", {"value": "x"}), profile(), auth()))
    assert_error(
        info.value,
        code="tool_not_allowed",
        status=RunStatus.POLICY_BLOCKED,
        error_class=ErrorClass.POLICY_BLOCKED,
    )
    assert calls == 0


def test_product_owner_mismatch_denies_but_core_owner_is_shared() -> None:
    runtime = ToolRuntime()
    product_calls = 0
    core_calls = 0

    async def product_handler(arguments):
        nonlocal product_calls
        product_calls += 1
        return {"ok": True}

    async def core_handler(arguments):
        nonlocal core_calls
        core_calls += 1
        return {"ok": True}

    runtime.register(spec("lovetree.read", owner="lovetree", input_schema={"type": "object"}), product_handler)
    runtime.register(spec("core.read", owner="core", input_schema={"type": "object"}), core_handler)

    with pytest.raises(ToolRuntimeError) as info:
        run(runtime.execute(ToolInvocation("lovetree.read", {}), profile("lovetree.read"), auth(app_id="ai-finder")))
    assert info.value.code == "tool_owner_mismatch"
    assert product_calls == 0

    result = run(runtime.execute(ToolInvocation("core.read", {}), profile("core.read"), auth(app_id="ai-finder")))
    assert result.output_copy() == {"ok": True}
    assert core_calls == 1


def test_missing_auth_scope_denies_zero_calls_and_all_scopes_allow() -> None:
    runtime = ToolRuntime()
    calls = 0

    async def handler(arguments):
        nonlocal calls
        calls += 1
        return {"ok": True}

    read_scope = "tree.read"
    private_scope = "tree.private"
    required_scopes = (read_scope, private_scope)
    runtime.register(spec(auth_scope=required_scopes), handler)
    invocation = ToolInvocation("core.echo", {"value": "x"})
    agent = profile("core.echo")

    with pytest.raises(ToolRuntimeError) as info:
        run(runtime.execute(invocation, agent, auth(scopes=(read_scope,))))
    assert info.value.code == "tool_auth_scope_missing"
    assert calls == 0

    result = run(runtime.execute(invocation, agent, auth(scopes=required_scopes)))
    assert result.output_copy() == {"ok": True}
    assert calls == 1


def test_user_confirmation_is_per_tool_and_model_argument_cannot_bypass() -> None:
    runtime = ToolRuntime()
    calls = 0

    async def handler(arguments):
        nonlocal calls
        calls += 1
        return {"ok": True}

    tool = spec(
        "lovetree.create",
        owner="lovetree",
        side_effect=ToolSideEffect.WRITE,
        approval=ApprovalPolicy.USER_CONFIRMATION,
        input_schema={"type": "object", "additionalProperties": True},
    )
    runtime.register(tool, handler)
    invocation = ToolInvocation(
        "lovetree.create",
        {"value": "x", "confirmed": True, "auth": "pretend"},
    )
    agent = profile("lovetree.create")

    with pytest.raises(ToolRuntimeError) as info:
        run(runtime.execute(invocation, agent, auth(app_id="lovetree", confirmed=("some.other.tool",))))
    assert info.value.code == "tool_user_confirmation_required"
    assert calls == 0

    result = run(runtime.execute(invocation, agent, auth(app_id="lovetree", confirmed=("lovetree.create",))))
    assert result.output_copy() == {"ok": True}
    assert calls == 1


def test_external_authorization_is_per_tool() -> None:
    runtime = ToolRuntime()
    calls = 0

    async def handler(arguments):
        nonlocal calls
        calls += 1
        return {"ok": True}

    tool = spec(
        "external.submit",
        owner="padiem-chat",
        side_effect=ToolSideEffect.HIGH_RISK,
        approval=ApprovalPolicy.EXTERNAL_AUTHORIZATION,
        input_schema={"type": "object"},
    )
    runtime.register(tool, handler)
    invocation = ToolInvocation("external.submit", {})
    agent = profile("external.submit")

    with pytest.raises(ToolRuntimeError) as info:
        run(runtime.execute(invocation, agent, auth(external=("other.submit",))))
    assert info.value.code == "tool_external_authorization_required"
    assert calls == 0

    result = run(runtime.execute(invocation, agent, auth(external=("external.submit",))))
    assert result.output_copy() == {"ok": True}
    assert calls == 1


def test_invalid_schema_arguments_rejected_before_handler() -> None:
    runtime = ToolRuntime()
    calls = 0

    async def handler(arguments):
        nonlocal calls
        calls += 1
        return arguments

    runtime.register(spec(), handler)
    with pytest.raises(ToolRuntimeError) as info:
        run(runtime.execute(ToolInvocation("core.echo", {"value": 123}), profile("core.echo"), auth()))
    assert_error(
        info.value,
        code="invalid_tool_arguments",
        status=RunStatus.REJECTED,
        error_class=ErrorClass.TOOL_VALIDATION_ERROR,
    )
    assert calls == 0
    assert "123" not in info.value.safe_message


def test_valid_arguments_invoke_once_and_handler_receives_isolated_mutable_copy() -> None:
    runtime = ToolRuntime()
    calls = 0
    received = None

    async def handler(arguments):
        nonlocal calls, received
        calls += 1
        received = arguments
        arguments["value"] = "handler-mutated-copy"
        return {"answer": arguments["value"]}

    runtime.register(spec(), handler)
    original = {"value": "original"}
    invocation = ToolInvocation("core.echo", original)
    result = run(runtime.execute(invocation, profile("core.echo"), auth()))

    assert calls == 1
    assert isinstance(received, dict)
    assert original == {"value": "original"}
    assert invocation.arguments_copy() == {"value": "original"}
    assert result.output_copy() == {"answer": "handler-mutated-copy"}
    assert result.event.status is RunStatus.COMPLETED
    assert result.event.error_class is None


def test_timeout_is_normalized_and_not_retried() -> None:
    runtime = ToolRuntime()
    calls = 0

    async def handler(arguments):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"ok": True}

    runtime.register(spec(timeout_seconds=0.01), handler)
    with pytest.raises(ToolRuntimeError) as info:
        run(runtime.execute(ToolInvocation("core.echo", {"value": "x"}), profile("core.echo"), auth()))
    assert_error(
        info.value,
        code="tool_timeout",
        status=RunStatus.TIMEOUT,
        error_class=ErrorClass.TOOL_RUNTIME_ERROR,
    )
    assert calls == 1


def test_handler_exception_is_normalized_without_raw_secret_and_not_retried() -> None:
    runtime = ToolRuntime()
    calls = 0

    async def handler(arguments):
        nonlocal calls
        calls += 1
        raise RuntimeError("PRIVATE_HANDLER_DETAIL_DO_NOT_REFLECT")

    runtime.register(spec(), handler)
    with pytest.raises(ToolRuntimeError) as info:
        run(runtime.execute(ToolInvocation("core.echo", {"value": "x"}), profile("core.echo"), auth()))
    assert_error(
        info.value,
        code="tool_execution_failed",
        status=RunStatus.FAILED,
        error_class=ErrorClass.TOOL_RUNTIME_ERROR,
    )
    assert "PRIVATE_HANDLER_DETAIL" not in info.value.safe_message
    assert "PRIVATE_HANDLER_DETAIL" not in json.dumps(info.value.to_public_dict())
    assert calls == 1


@pytest.mark.parametrize(
    "bad_output",
    [object(), {"value": object()}, (1, 2), float("nan"), float("inf")],
)
def test_invalid_non_json_or_non_finite_output_is_rejected(bad_output) -> None:
    runtime = ToolRuntime()

    async def handler(arguments):
        return bad_output

    runtime.register(spec(), handler)
    with pytest.raises(ToolRuntimeError) as info:
        run(runtime.execute(ToolInvocation("core.echo", {"value": "x"}), profile("core.echo"), auth()))
    assert_error(
        info.value,
        code="invalid_tool_output",
        status=RunStatus.FAILED,
        error_class=ErrorClass.TOOL_RUNTIME_ERROR,
    )


def test_oversized_output_is_rejected() -> None:
    runtime = ToolRuntime()

    async def handler(arguments):
        return {"value": "x" * (MAX_TOOL_OUTPUT_BYTES + 1)}

    runtime.register(spec(), handler)
    with pytest.raises(ToolRuntimeError) as info:
        run(runtime.execute(ToolInvocation("core.echo", {"value": "x"}), profile("core.echo"), auth()))
    assert info.value.code == "invalid_tool_output"


def test_valid_output_is_copy_safe_and_public_result_is_bounded_shape() -> None:
    runtime = ToolRuntime()
    handler_output = {"nested": {"items": [1, 2]}}

    async def handler(arguments):
        return handler_output

    runtime.register(spec(), handler)
    result = run(runtime.execute(ToolInvocation("core.echo", {"value": "x"}), profile("core.echo"), auth()))
    handler_output["nested"]["items"].append(3)  # type: ignore[index,union-attr]

    assert isinstance(result, ToolExecutionResult)
    assert result.output_copy() == {"nested": {"items": [1, 2]}}
    public = result.to_public_dict()
    assert public["tool_id"] == "core.echo"
    assert public["event"]["status"] == "completed"
    assert public["event"]["error_class"] is None
    assert public["output"] == {"nested": {"items": [1, 2]}}
