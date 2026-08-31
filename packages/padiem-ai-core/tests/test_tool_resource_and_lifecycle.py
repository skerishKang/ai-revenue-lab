import pytest

from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.tool_lifecycle import (
    ConnectorLifecycleEvent,
    ConnectorLifecycleKind,
    ToolLifecycleError,
    ToolLifecycleEvent,
    ToolLifecycleKind,
)
from padiem_ai_core.tool_resource_policy import (
    EffectiveToolResources,
    ToolResourcePolicy,
    ToolResourcePolicyError,
    resolve_tool_resources,
)


def spec(timeout=120.0):
    return ToolSpec(
        id="web.search",
        title="Web Search",
        description="Read-only web search",
        owner="core",
        side_effect=ToolSideEffect.READ,
        approval_policy=ApprovalPolicy.NOT_REQUIRED,
        input_schema={"type": "object"},
        output_contract={"type": "object"},
        auth_scope=(),
        timeout_seconds=timeout,
    )


def test_resource_policy_narrows_tool_spec_only() -> None:
    effective = resolve_tool_resources(
        spec(timeout=120.0),
        ToolResourcePolicy(max_argument_bytes=4096, max_output_bytes=8192, max_timeout_seconds=30),
    )
    assert effective == EffectiveToolResources(
        tool_id="web.search",
        argument_bytes=4096,
        output_bytes=8192,
        timeout_seconds=30.0,
        narrowed=True,
    )


def test_resource_policy_does_not_widen_lower_tool_spec_timeout() -> None:
    effective = resolve_tool_resources(
        spec(timeout=10.0),
        ToolResourcePolicy(max_timeout_seconds=300),
    )
    assert effective.timeout_seconds == 10.0
    assert effective.narrowed is False


def test_default_policy_preserves_existing_runtime_ceilings() -> None:
    effective = resolve_tool_resources(spec(timeout=30.0))
    assert effective.argument_bytes == 65_536
    assert effective.output_bytes == 262_144
    assert effective.timeout_seconds == 30.0
    assert effective.narrowed is False


def test_invalid_server_policy_fails_closed() -> None:
    with pytest.raises(ToolResourcePolicyError):
        ToolResourcePolicy(max_argument_bytes=0)
    with pytest.raises(ToolResourcePolicyError):
        ToolResourcePolicy(max_output_bytes=262_145)
    with pytest.raises(ToolResourcePolicyError):
        ToolResourcePolicy(max_timeout_seconds=301)


def test_effective_resource_projection_has_no_credentials_or_handlers() -> None:
    projected = resolve_tool_resources(spec()).to_public_dict()
    assert set(projected) == {"tool_id", "argument_bytes", "output_bytes", "timeout_seconds", "narrowed"}
    assert "credential" not in projected
    assert "handler" not in projected


def test_tool_lifecycle_event_is_scalar_only() -> None:
    event = ToolLifecycleEvent(
        event_id="event:tool:1",
        run_id="run:1",
        kind=ToolLifecycleKind.COMPLETED,
        tool_id="web.search",
        sequence=3,
        connector_id="connector:padiem:web@1",
        duration_ms=27,
        metadata={"status": "ok", "output_bytes": 512},
    )
    assert event.to_public_dict()["kind"] == "completed"
    assert event.to_public_dict()["metadata"] == {"status": "ok", "output_bytes": 512}


def test_tool_lifecycle_event_rejects_nested_sensitive_payload() -> None:
    with pytest.raises(ToolLifecycleError):
        ToolLifecycleEvent(
            event_id="event:tool:2",
            run_id="run:1",
            kind=ToolLifecycleKind.REQUESTED,
            tool_id="web.search",
            sequence=1,
            metadata={"arguments": {"api_key": "secret"}},
        )


def test_connector_lifecycle_event_is_bounded() -> None:
    event = ConnectorLifecycleEvent(
        event_id="event:connector:1",
        run_id="run:1",
        kind=ConnectorLifecycleKind.AUTHORIZED,
        connector_id="connector:padiem:web@1",
        sequence=1,
        tool_id="web.search",
        metadata={"subject_scope": "project"},
    )
    assert event.to_public_dict() == {
        "event_id": "event:connector:1",
        "run_id": "run:1",
        "kind": "authorized",
        "connector_id": "connector:padiem:web@1",
        "tool_id": "web.search",
        "sequence": 1,
        "metadata": {"subject_scope": "project"},
    }


def test_connector_event_rejects_sensitive_nested_data() -> None:
    with pytest.raises(ToolLifecycleError):
        ConnectorLifecycleEvent(
            event_id="event:connector:2",
            run_id="run:1",
            kind=ConnectorLifecycleKind.AUTHORIZED,
            connector_id="connector:padiem:web@1",
            sequence=1,
            metadata={"oauth": {"access_token": "secret"}},
        )


@pytest.mark.parametrize(
    ("connector_id", "tool_id"),
    [
        ("connector:padiem:web@1", "tool:padiem:web_search@1"),
        ("connector:owner:custom-connector@2", "web.search"),
    ],
)
def test_tool_lifecycle_accepts_canonical_ids(connector_id: str, tool_id: str) -> None:
    event = ToolLifecycleEvent(
        event_id="event:tool:canonical",
        run_id="run:1",
        kind=ToolLifecycleKind.COMPLETED,
        tool_id=tool_id,
        sequence=1,
        connector_id=connector_id,
        duration_ms=10,
        metadata={"status": "ok"},
    )
    assert event.connector_id == connector_id
    assert event.tool_id == tool_id


@pytest.mark.parametrize(
    "invalid_connector_id",
    [
        "connector:padiem:web",
        "connector:padiem:web@",
        "connector:padiem:web@x",
        "connector:padiem:web@0",
        "connector::web@1",
    ],
)
def test_tool_lifecycle_rejects_malformed_canonical_connector_id(invalid_connector_id: str) -> None:
    with pytest.raises(ToolLifecycleError) as exc_info:
        ToolLifecycleEvent(
            event_id="event:tool:invalid",
            run_id="run:1",
            kind=ToolLifecycleKind.COMPLETED,
            tool_id="web.search",
            sequence=1,
            connector_id=invalid_connector_id,
        )
    assert exc_info.value.code == "invalid_tool_lifecycle_event"
