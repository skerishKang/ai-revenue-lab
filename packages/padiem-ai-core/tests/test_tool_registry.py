import pytest

from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.tool_registry import (
    RegisteredTool,
    ToolRegistryError,
    ToolRegistrySnapshot,
)


def spec(**overrides) -> ToolSpec:
    values = {
        "id": "web.search",
        "title": "Web Search",
        "description": "Search approved web sources.",
        "owner": "core",
        "side_effect": ToolSideEffect.READ,
        "approval_policy": ApprovalPolicy.NOT_REQUIRED,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "output_contract": {"type": "search_results"},
        "auth_scope": (),
        "timeout_seconds": 20.0,
        "user_visible": True,
    }
    values.update(overrides)
    return ToolSpec(**values)


def registered(
    canonical_tool_id: str = "tool:padiem:web_search@1",
    **spec_overrides,
) -> RegisteredTool:
    return RegisteredTool.from_spec(
        canonical_tool_id=canonical_tool_id,
        runtime_spec=spec(**spec_overrides),
    )


def test_registry_wraps_existing_toolspec_instead_of_redefining_it() -> None:
    runtime_spec = spec()
    entry = RegisteredTool.from_spec(
        canonical_tool_id="tool:padiem:web_search@1",
        runtime_spec=runtime_spec,
    )

    assert entry.runtime_spec is runtime_spec
    assert entry.runtime_tool_id == "web.search"
    assert entry.to_public_dict()["runtime_spec"] == runtime_spec.to_public_dict()


def test_registry_is_deterministic_by_canonical_tool_id() -> None:
    second = registered(
        "tool:padiem:read_document@1",
        id="document.read",
        title="Read Document",
        description="Read an authorized document.",
    )
    registry = ToolRegistrySnapshot.from_entries((registered(), second))

    assert registry.canonical_tool_ids == (
        "tool:padiem:read_document@1",
        "tool:padiem:web_search@1",
    )


def test_same_major_id_with_different_spec_fails_closed() -> None:
    registry = ToolRegistrySnapshot.from_entries((registered(),))

    with pytest.raises(ToolRegistryError) as exc_info:
        registry.with_tool(
            canonical_tool_id="tool:padiem:web_search@1",
            runtime_spec=spec(timeout_seconds=10.0),
        )

    assert exc_info.value.code == "tool_registry_version_conflict"


def test_exact_same_registration_is_idempotent() -> None:
    registry = ToolRegistrySnapshot.from_entries((registered(),))

    assert registry.with_tool(
        canonical_tool_id="tool:padiem:web_search@1",
        runtime_spec=spec(),
    ) is registry


def test_one_runtime_id_cannot_back_multiple_canonical_tools() -> None:
    with pytest.raises(ToolRegistryError) as exc_info:
        ToolRegistrySnapshot.from_entries(
            (
                registered("tool:padiem:web_search@1"),
                registered("tool:padiem:search_alias@1"),
            )
        )

    assert exc_info.value.code == "duplicate_runtime_tool_id"


def test_multiple_major_versions_can_coexist_only_with_distinct_runtime_ids() -> None:
    registry = ToolRegistrySnapshot.from_entries(
        (
            registered("tool:padiem:web_search@1"),
            registered(
                "tool:padiem:web_search@2",
                id="web.search.v2",
                description="Search approved web sources using v2 runtime semantics.",
            ),
        )
    )

    assert registry.canonical_tool_ids == (
        "tool:padiem:web_search@1",
        "tool:padiem:web_search@2",
    )
    assert registry.get("tool:padiem:web_search@2").runtime_tool_id == "web.search.v2"


def test_invalid_unversioned_canonical_tool_id_is_rejected() -> None:
    with pytest.raises(ToolRegistryError) as exc_info:
        RegisteredTool.from_spec(
            canonical_tool_id="web.search",
            runtime_spec=spec(),
        )

    assert exc_info.value.code == "invalid_tool_registry_contract"


def test_registry_contains_no_handler_or_dynamic_execution_authority() -> None:
    entry = registered()

    assert not hasattr(entry, "handler")
    assert not hasattr(entry, "callable")
    assert not hasattr(entry, "module")
    assert not hasattr(entry, "import_path")


def test_toolspec_still_enforces_write_approval_before_registry() -> None:
    with pytest.raises(ValueError):
        spec(
            id="document.write",
            side_effect=ToolSideEffect.WRITE,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
        )


def test_fingerprint_detects_runtime_spec_content_tampering() -> None:
    original = registered()

    with pytest.raises(ToolRegistryError) as exc_info:
        RegisteredTool(
            canonical_tool_id=original.canonical_tool_id,
            runtime_spec=spec(description="Changed semantics."),
            fingerprint=original.fingerprint,
        )

    assert exc_info.value.code == "tool_registry_fingerprint_mismatch"
