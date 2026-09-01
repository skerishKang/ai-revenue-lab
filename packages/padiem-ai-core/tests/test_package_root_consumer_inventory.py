from __future__ import annotations

import ast
from pathlib import Path

import padiem_ai_core as core


REPO_ROOT = Path(__file__).resolve().parents[3]
SKIP_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
}

EXPECTED_RUNTIME_ROOT_IMPORTS = {
    "apps/living-learning/app/ai/padiem_core.py": frozenset(
        {
            "AgentProfile",
            "B14ExecutionClient",
            "B14ExecutionConfig",
            "ErrorClass",
            "ExecutionRequest",
            "ExecutionResult",
            "ExecutionRuntime",
            "ExecutionRuntimeError",
        }
    ),
    "apps/padiem-ai-engine/app/cloudflare_transport.py": frozenset(
        {
            "B14_CHAT_COMPLETIONS_PATH",
            "B14_STREAM_PREVIEW_PATH",
        }
    ),
    "apps/padiem-ai-engine/app/context_permission_wire.py": frozenset(
        {"ExecutionRequest"}
    ),
    "apps/padiem-ai-engine/app/continuation_binding.py": frozenset(
        {"ApprovalPause"}
    ),
    "apps/padiem-ai-engine/app/continuation_identity.py": frozenset(
        {
            "AgentPlan",
            "AgentRecoveryPolicy",
            "ExecutionContext",
            "ExecutionRequest",
            "request_fingerprint",
        }
    ),
    "apps/padiem-ai-engine/app/execution_context_wire.py": frozenset(
        {"ExecutionContext"}
    ),
    "apps/padiem-ai-engine/app/idempotency_binding.py": frozenset(
        {
            "B14RouteMetadata",
            "ExecutionResult",
            "IdempotencyConflictError",
            "RunMetadata",
            "RunStatus",
            "UsageMetadata",
        }
    ),
    "apps/padiem-ai-engine/app/orchestration_identity_service.py": frozenset(
        {
            "ExecutionContext",
            "IdempotencyConflictError",
            "OrchestrationError",
            "OrchestrationRequest",
            "OrchestrationResumeRequest",
            "OrchestrationRunner",
        }
    ),
    "apps/padiem-ai-engine/app/orchestration_service.py": frozenset(
        {
            "AgentPlan",
            "AgentPlanStep",
            "AgentPlannerError",
            "AgentProfile",
            "AgentRecoveryError",
            "AgentRecoveryPolicy",
            "ApprovalOutcome",
            "ApprovalPause",
            "ApprovalRequirement",
            "BoundedAgentDefinition",
            "CompiledAgentProfile",
            "ExecutionContext",
            "ExecutionRequest",
            "ExecutionResult",
            "IdempotencyConflictError",
            "OrchestrationError",
            "OrchestrationEvent",
            "OrchestrationRequest",
            "OrchestrationResult",
            "OrchestrationResumeRequest",
            "OrchestrationRunner",
            "ToolAuthorizationContext",
            "VerifiedApprovalDecision",
            "request_fingerprint",
        }
    ),
    "apps/padiem-ai-engine/app/service.py": frozenset(
        {
            "AgentProfile",
            "ExecutionContext",
            "ExecutionRequest",
            "ExecutionResult",
            "ExecutionRuntimeError",
            "IdempotencyConflictError",
        }
    ),
    "apps/padiem-ai-engine/app/streaming_service.py": frozenset(
        {
            "ExecutionContext",
            "ExecutionRequest",
            "ExecutionRuntimeError",
            "StreamingExecutionEvent",
        }
    ),
    "apps/padiem-ai-engine/worker.py": frozenset(
        {
            "B14ExecutionClient",
            "B14ExecutionConfig",
            "B14StreamingClient",
            "ExecutionRuntime",
            "StreamingExecutionRuntime",
        }
    ),
    "apps/padiem-ai-engine/worker_identity.py": frozenset(
        {
            "B14ExecutionClient",
            "B14ExecutionConfig",
            "B14StreamingClient",
            "ExecutionRuntime",
            "StreamingExecutionRuntime",
        }
    ),
    "apps/padiem-chat/app/b14_client.py": frozenset(
        {
            "AgentProfile",
            "B14ExecutionClient",
            "B14ExecutionConfig",
            "B14PostJSONTransport",
            "B14StreamingClient",
            "B14TransportResponse",
            "ExecutionRequest",
            "ExecutionRuntime",
            "ExecutionRuntimeError",
            "MAX_B14_RESPONSE_BYTES",
            "MultimodalExecutionRequest",
            "MultimodalExecutionRuntime",
            "StreamingExecutionRuntime",
        }
    ),
    "apps/padiem-chat/app/evidence.py": frozenset({"Evidence"}),
    "apps/padiem-chat/app/grounding.py": frozenset({"Evidence"}),
    "apps/padiem-chat/app/task_modes.py": frozenset({"AgentProfile"}),
    "apps/padiem-chat/app/web_tools.py": frozenset({"Evidence"}),
}


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*.py"):
        relative = path.relative_to(REPO_ROOT)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        files.append(path)
    return sorted(files)


def _record(
    inventory: list[dict[str, object]],
    *,
    path: Path,
    line: int,
    kind: str,
    names: list[str],
) -> None:
    inventory.append(
        {
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "line": line,
            "kind": kind,
            "names": sorted(names),
        }
    )


def collect_package_root_consumers() -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []

    for path in _iter_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue

        module_aliases: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "padiem_ai_core":
                _record(
                    inventory,
                    path=path,
                    line=node.lineno,
                    kind="from_root",
                    names=[alias.name for alias in node.names],
                )

            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "padiem_ai_core":
                        local_name = alias.asname or "padiem_ai_core"
                        module_aliases.add(local_name)
                        _record(
                            inventory,
                            path=path,
                            line=node.lineno,
                            kind="module_import",
                            names=[local_name],
                        )

            if isinstance(node, ast.Call) and node.args:
                first_arg = node.args[0]
                if not isinstance(first_arg, ast.Constant) or first_arg.value != "padiem_ai_core":
                    continue

                if (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "importlib"
                    and node.func.attr == "import_module"
                ):
                    _record(
                        inventory,
                        path=path,
                        line=node.lineno,
                        kind="dynamic_module_import",
                        names=["padiem_ai_core"],
                    )
                elif isinstance(node.func, ast.Name) and node.func.id == "__import__":
                    _record(
                        inventory,
                        path=path,
                        line=node.lineno,
                        kind="dynamic_module_import",
                        names=["padiem_ai_core"],
                    )

        if module_aliases:
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in module_aliases
                ):
                    _record(
                        inventory,
                        path=path,
                        line=node.lineno,
                        kind="root_attribute",
                        names=[node.attr],
                    )

                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr"
                    and len(node.args) >= 2
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in module_aliases
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)
                ):
                    _record(
                        inventory,
                        path=path,
                        line=node.lineno,
                        kind="dynamic_root_attribute",
                        names=[node.args[1].value],
                    )

    return sorted(
        inventory,
        key=lambda item: (
            str(item["path"]),
            int(item["line"]),
            str(item["kind"]),
            tuple(item["names"]),
        ),
    )


def _is_test_path(path: str) -> bool:
    parts = Path(path).parts
    return "tests" in parts or Path(path).name.startswith("test_")


def _runtime_direct_root_imports(
    inventory: list[dict[str, object]],
) -> dict[str, frozenset[str]]:
    result: dict[str, set[str]] = {}
    for item in inventory:
        path = str(item["path"])
        if item["kind"] != "from_root" or _is_test_path(path):
            continue
        result.setdefault(path, set()).update(str(name) for name in item["names"])
    return {path: frozenset(names) for path, names in sorted(result.items())}


def test_runtime_package_root_consumers_match_compatibility_snapshot() -> None:
    inventory = collect_package_root_consumers()

    assert _runtime_direct_root_imports(inventory) == EXPECTED_RUNTIME_ROOT_IMPORTS

    runtime_non_direct = [
        item
        for item in inventory
        if not _is_test_path(str(item["path"])) and item["kind"] != "from_root"
    ]
    assert runtime_non_direct == []


def test_all_direct_root_imports_reference_declared_exports() -> None:
    exported = set(core.__all__)
    inventory = collect_package_root_consumers()

    direct_imports = [item for item in inventory if item["kind"] == "from_root"]
    assert direct_imports
    assert all("*" not in item["names"] for item in direct_imports)

    undeclared = {
        str(name)
        for item in direct_imports
        for name in item["names"]
        if str(name) not in exported
    }
    assert undeclared == set()


def test_root_module_attribute_access_is_declared_or_audited_private_surface() -> None:
    exported = set(core.__all__)
    inventory = collect_package_root_consumers()
    allowed_private = {"__all__", "_TOOL_RUNTIME_EXPORTS"}

    undeclared = {
        str(name)
        for item in inventory
        if item["kind"] in {"root_attribute", "dynamic_root_attribute"}
        for name in item["names"]
        if str(name) not in exported and str(name) not in allowed_private
    }
    assert undeclared == set()


def test_no_dynamic_or_wildcard_package_root_imports() -> None:
    inventory = collect_package_root_consumers()

    assert [item for item in inventory if item["kind"] == "dynamic_module_import"] == []
    assert [
        item
        for item in inventory
        if item["kind"] == "from_root" and "*" in item["names"]
    ] == []
