from __future__ import annotations

import pytest

from padiem_ai_core import (
    AgentProfile,
    ApprovalPolicy,
    ErrorClass,
    Evidence,
    RunMetadata,
    RunStatus,
    ToolEvent,
    ToolSideEffect,
    ToolSpec,
    UsageMetadata,
)


def test_evidence_supports_non_web_sources_without_inventing_url() -> None:
    evidence = Evidence(
        id="evidence-1",
        title="Local document",
        snippet="bounded excerpt",
        retrieved_at="2026-08-26T00:00:00Z",
        provider="ai-book",
        source_type="document",
        url=None,
    )

    assert evidence.to_public_dict() == {
        "id": "evidence-1",
        "title": "Local document",
        "url": None,
        "snippet": "bounded excerpt",
        "retrieved_at": "2026-08-26T00:00:00Z",
        "provider": "ai-book",
        "source_type": "document",
    }


def test_required_identifiers_fail_closed() -> None:
    with pytest.raises(ValueError, match="safe identifier"):
        Evidence(
            id="",
            title="x",
            snippet="x",
            retrieved_at="now",
            provider="provider",
            source_type="document",
        )

    with pytest.raises(ValueError, match="safe identifier"):
        RunMetadata(
            trace_id="trace 1",
            app_id="padiem-chat",
            agent_id="auto",
            status=RunStatus.RECEIVED,
        )


def test_tool_contract_deep_freezes_schema_and_requires_approval_for_writes() -> None:
    source_schema = {"type": "object", "properties": {"query": {"type": "string"}}}
    tool = ToolSpec(
        id="web.search",
        title="Web search",
        description="Search public web evidence",
        owner="core",
        side_effect=ToolSideEffect.READ,
        approval_policy=ApprovalPolicy.NOT_REQUIRED,
        input_schema=source_schema,
        output_contract={"type": "evidence_list"},
        auth_scope=("web.read",),
    )

    source_schema["type"] = "changed"
    assert tool.input_schema["type"] == "object"
    with pytest.raises(TypeError):
        tool.input_schema["type"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        tool.input_schema["properties"]["query"]["type"] = "number"  # type: ignore[index]

    with pytest.raises(ValueError, match="require an approval policy"):
        ToolSpec(
            id="tree.create",
            title="Create tree",
            description="Create a product record",
            owner="lovetree",
            side_effect=ToolSideEffect.WRITE,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
        )


def test_tool_contract_requires_explicit_enums() -> None:
    with pytest.raises(ValueError, match="ToolSideEffect"):
        ToolSpec(
            id="web.search",
            title="Web search",
            description="Search public web evidence",
            owner="core",
            side_effect="read",  # type: ignore[arg-type]
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
        )

    with pytest.raises(ValueError, match="ApprovalPolicy"):
        ToolSpec(
            id="web.search",
            title="Web search",
            description="Search public web evidence",
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy="not_required",  # type: ignore[arg-type]
        )


def test_agent_profile_is_product_neutral_and_immutable() -> None:
    profile = AgentProfile(
        id="tree-builder",
        title="Tree builder",
        description="Builds a tree through product tools",
        system_instruction="Use only allowed product tools.",
        task_type="generation",
        optimize_for="balanced",
        max_tokens=1200,
        allowed_tools=["lovetree.read_moments", "lovetree.create_tree"],  # type: ignore[arg-type]
        required_capabilities=["text", "tools"],  # type: ignore[arg-type]
        context_policy={"product_context": "adapter_only"},
        model_policy={"route": "b14_auto"},
        max_steps=4,
        output_contract={"type": "tree_result"},
    )

    assert profile.allowed_tools == (
        "lovetree.read_moments",
        "lovetree.create_tree",
    )
    assert profile.required_capabilities == ("text", "tools")
    assert profile.context_policy["product_context"] == "adapter_only"
    with pytest.raises(TypeError):
        profile.model_policy["route"] = "direct"  # type: ignore[index]

    public = profile.to_public_dict()
    assert public["id"] == "tree-builder"
    assert public["allowed_tools"] == [
        "lovetree.read_moments",
        "lovetree.create_tree",
    ]
    assert "system_instruction" not in public
    assert "credential" not in public
    assert "secret" not in public


def test_agent_profile_rejects_duplicate_tools_and_capabilities() -> None:
    kwargs = dict(
        id="agent",
        title="Agent",
        description="Agent description",
        system_instruction="Instruction",
        task_type="general",
        optimize_for="balanced",
        max_tokens=100,
    )

    with pytest.raises(ValueError, match="duplicates"):
        AgentProfile(**kwargs, allowed_tools=("web.search", "web.search"))

    with pytest.raises(ValueError, match="duplicates"):
        AgentProfile(**kwargs, required_capabilities=("text", "text"))


def test_run_metadata_keeps_unknown_route_and_usage_unknown() -> None:
    run = RunMetadata(
        trace_id="trace-123",
        app_id="padiem-chat",
        agent_id="auto",
        session_id="session-1",
        status=RunStatus.COMPLETED,
    )

    public = run.to_public_dict()
    assert public["provider"] is None
    assert public["model"] is None
    assert public["duration_ms"] is None
    assert public["usage"] == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }
    assert "api_key" not in public
    assert "credential" not in public
    assert "secret" not in public


def test_run_metadata_serializes_tool_event_and_error_without_secret_fields() -> None:
    event = ToolEvent(
        tool_id="web.search",
        status=RunStatus.COMPLETED,
        duration_ms=42,
    )
    run = RunMetadata(
        trace_id="trace-456",
        app_id="ai-finder",
        agent_id="local-guide",
        status=RunStatus.FAILED,
        provider="provider-a",
        model="model/x",
        duration_ms=90,
        usage=UsageMetadata(input_tokens=10, output_tokens=20, total_tokens=30),
        tool_events=(event,),
        error_class=ErrorClass.PROVIDER_TIMEOUT,
    )

    public = run.to_public_dict()
    assert public["provider"] == "provider-a"
    assert public["model"] == "model/x"
    assert public["tool_events"] == [
        {
            "tool_id": "web.search",
            "status": "completed",
            "duration_ms": 42,
            "error_class": None,
        }
    ]
    assert public["error_class"] == "provider_timeout"
    assert not ({"api_key", "credential", "secret", "token"} & set(public))


def test_usage_metadata_rejects_negative_or_boolean_values() -> None:
    with pytest.raises(ValueError):
        UsageMetadata(input_tokens=-1)
    with pytest.raises(ValueError):
        UsageMetadata(output_tokens=True)  # type: ignore[arg-type]


def test_import_has_no_runtime_configuration_requirement() -> None:
    # If this test module imported the package successfully without configuring
    # environment variables, provider keys or network transports, the Slice 1
    # import-time boundary is intact.
    assert ToolSideEffect.HIGH_RISK.value == "high_risk"
