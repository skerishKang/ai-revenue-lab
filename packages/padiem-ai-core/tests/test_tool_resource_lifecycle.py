import pytest

from padiem_ai_core import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.tool_lifecycle import (
    ConnectorLifecycleEvent,
    ConnectorLifecycleKind,
    ToolLifecycleError,
    ToolLifecycleEvent,
    ToolLifecycleKind,
)
from padiem_ai_core.tool_resource_policy import (
    ToolResourcePolicy,
    ToolResourcePolicyError,
    resolve_tool_resources,
)


def tool_spec(*, timeout_seconds: float = 60.0) -> ToolSpec:
    return ToolSpec(
        id="calculator",
        title="Calculator",
        description="Network-free test calculator.",
        owner="padiem",
        side_effect=ToolSideEffect.READ,
        approval_policy=ApprovalPolicy.NOT_REQUIRED,
        input_schema={"type": "object"},
        output_contract={"type": "object"},
        timeout_seconds=timeout_seconds,
    )


def test_resource_policy_can_only_narrow_tool_spec_ceiling() -> None:
    resources = resolve_tool_resources(
        tool_spec(timeout_seconds=90.0),
        ToolResourcePolicy(
            max_argument_bytes=1024,
            max_output_bytes=2048,
            max_timeout_seconds=30.0,
        ),
    )

    assert resources.tool_id == "calculator"
    assert resources.argument_bytes == 1024
    assert resources.output_bytes == 2048
    assert resources.timeout_seconds == 30.0
    assert resources.narrowed is True


def test_resource_policy_rejects_widening_outside_runtime_bounds() -> None:
    with pytest.raises(ToolResourcePolicyError) as exc_info:
        ToolResourcePolicy(max_timeout_seconds=301.0)

    assert exc_info.value.code == "invalid_tool_resource_policy"


def test_resource_policy_public_projection_has_no_authority_or_credentials() -> None:
    public = resolve_tool_resources(tool_spec(), ToolResourcePolicy(max_timeout_seconds=15.0)).to_public_dict()
    rendered = repr(public).lower()

    assert public == {
        "tool_id": "calculator",
        "argument_bytes": 1048576,
        "output_bytes": 1048576,
        "timeout_seconds": 15.0,
        "narrowed": True,
    }
    assert "credential" not in rendered
    assert "token" not in rendered
    assert "authorization" not in rendered
    assert "arguments" not in rendered
    assert "output" not in rendered


def test_tool_lifecycle_event_is_bounded_scalar_public_envelope() -> None:
    event = ToolLifecycleEvent(
        event_id="evt_tool_1",
        run_id="run_tool_1",
        kind=ToolLifecycleKind.COMPLETED,
        tool_id="tool:padiem:calculator@1",
        sequence=1,
        connector_id="connector:padiem:math@1",
        duration_ms=12,
        metadata={"status": "completed", "bytes": 7, "approved": True},
    )

    assert event.to_public_dict() == {
        "event_id": "evt_tool_1",
        "run_id": "run_tool_1",
        "kind": "completed",
        "tool_id": "tool:padiem:calculator@1",
        "sequence": 1,
        "connector_id": "connector:padiem:math@1",
        "duration_ms": 12,
        "error_code": None,
        "metadata": {"status": "completed", "bytes": 7, "approved": True},
    }


def test_tool_lifecycle_rejects_raw_arguments_outputs_and_credentials() -> None:
    with pytest.raises(ToolLifecycleError) as exc_info:
        ToolLifecycleEvent(
            event_id="evt_tool_2",
            run_id="run_tool_1",
            kind=ToolLifecycleKind.STARTED,
            tool_id="tool:padiem:calculator@1",
            sequence=1,
            metadata={"arguments": {"secret": "do-not-project"}},
        )

    assert exc_info.value.code == "invalid_tool_lifecycle_event"


def test_tool_lifecycle_has_explicit_terminal_revoked_and_unavailable_semantics() -> None:
    revoked = ToolLifecycleEvent(
        event_id="evt_tool_revoked",
        run_id="run_tool_1",
        kind=ToolLifecycleKind.REVOKED,
        tool_id="tool:padiem:calculator@1",
        sequence=1,
        error_code="tool_revoked",
    )
    unavailable = ToolLifecycleEvent(
        event_id="evt_tool_unavailable",
        run_id="run_tool_1",
        kind=ToolLifecycleKind.UNAVAILABLE,
        tool_id="tool:padiem:calculator@1",
        sequence=2,
        error_code="tool_unavailable",
    )

    assert revoked.to_public_dict()["kind"] == "revoked"
    assert unavailable.to_public_dict()["kind"] == "unavailable"


def test_connector_lifecycle_event_is_scalar_only_and_no_raw_auth_material() -> None:
    event = ConnectorLifecycleEvent(
        event_id="evt_connector_1",
        run_id="run_tool_1",
        kind=ConnectorLifecycleKind.TOOL_BOUND,
        connector_id="connector:padiem:math@1",
        tool_id="tool:padiem:calculator@1",
        sequence=1,
        metadata={"scope": "read", "healthy": True},
    )
    public = event.to_public_dict()

    assert public["kind"] == "tool_bound"
    assert public["connector_id"] == "connector:padiem:math@1"
    assert public["tool_id"] == "tool:padiem:calculator@1"
    assert "credential" not in repr(public).lower()
    assert "token" not in repr(public).lower()


def test_connector_lifecycle_rejects_nested_secret_metadata() -> None:
    with pytest.raises(ToolLifecycleError) as exc_info:
        ConnectorLifecycleEvent(
            event_id="evt_connector_2",
            run_id="run_tool_1",
            kind=ConnectorLifecycleKind.AUTHORIZED,
            connector_id="connector:padiem:math@1",
            sequence=1,
            metadata={"credentials": {"access_token": "secret"}},
        )

    assert exc_info.value.code == "invalid_tool_lifecycle_event"
