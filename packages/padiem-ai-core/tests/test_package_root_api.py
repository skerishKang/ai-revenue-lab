from __future__ import annotations

import importlib

import pytest

import padiem_ai_core as core


FOUNDATIONAL_ROOT_EXPORTS = {
    "AgentProfile",
    "ApprovalPolicy",
    "ErrorClass",
    "Evidence",
    "RunMetadata",
    "RunStatus",
    "ToolEvent",
    "ToolSideEffect",
    "ToolSpec",
    "UsageMetadata",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionRuntime",
    "ExecutionRuntimeError",
    "MultimodalExecutionRequest",
    "MultimodalExecutionRuntime",
    "StreamingExecutionEvent",
    "StreamingExecutionRuntime",
}

REPRESENTATIVE_COMPATIBILITY_EXPORTS = {
    "B14ExecutionClient",
    "B14StreamingClient",
    "GroundedResearchRuntime",
    "ExecutionStateMachine",
    "ContextualExecutionRunner",
    "RetrievalRequest",
    "MemoryWriteRequest",
    "MemoryReadPolicy",
    "AgentPlanner",
    "ReusableSkillPackage",
    "ToolRegistrySnapshot",
    "ConnectorRegistrySnapshot",
    "EvidenceGraph",
    "VerificationRequest",
    "OrchestrationRunner",
    "AdapterConformanceSuite",
}


def test_package_root_all_is_unique_and_keeps_approved_contract_families() -> None:
    exported = tuple(core.__all__)

    assert len(exported) == len(set(exported))
    assert FOUNDATIONAL_ROOT_EXPORTS <= set(exported)
    assert REPRESENTATIVE_COMPATIBILITY_EXPORTS <= set(exported)


def test_package_root_all_names_are_direct_or_lazy_exports() -> None:
    lazy_exports = set(core._TOOL_RUNTIME_EXPORTS)

    assert lazy_exports <= set(core.__all__)
    unresolved = {
        name
        for name in core.__all__
        if name not in vars(core) and name not in lazy_exports
    }
    assert unresolved == set()


def test_tool_runtime_exports_remain_lazy_until_requested() -> None:
    fresh_core = importlib.reload(core)

    assert "ToolRuntime" in fresh_core.__all__
    assert "ToolRuntime" in fresh_core._TOOL_RUNTIME_EXPORTS
    assert "ToolRuntime" not in vars(fresh_core)


def test_tool_runtime_lazy_export_preserves_optional_dependency_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh_core = importlib.reload(core)
    real_import_module = fresh_core.importlib.import_module

    def missing_jsonschema(name: str, package: str | None = None):
        if name == ".tool_runtime" and package == fresh_core.__name__:
            error = ModuleNotFoundError("No module named 'jsonschema'")
            error.name = "jsonschema"
            raise error
        return real_import_module(name, package)

    monkeypatch.setattr(fresh_core.importlib, "import_module", missing_jsonschema)

    with pytest.raises(
        ImportError,
        match=r"Tool Runtime requires the optional 'tools' dependency",
    ):
        getattr(fresh_core, "ToolRuntime")
