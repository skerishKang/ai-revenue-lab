from __future__ import annotations

import ast
from pathlib import Path

import padiem_ai_core as core


PACKAGE_DIR = Path(__file__).resolve().parents[1] / "padiem_ai_core"
INIT_PATH = PACKAGE_DIR / "__init__.py"

EXPECTED_DIRECT_TOOL_RUNTIME_EXPORTS = {
    "OrchestrationEvent",
    "OrchestrationEventError",
    "OrchestrationEventKind",
    "OrchestrationError",
    "OrchestrationRequest",
    "OrchestrationResult",
    "OrchestrationResumeRequest",
    "OrchestrationRunner",
    "public_orchestration_event",
}

EXPECTED_LAZY_ONLY_TOOL_RUNTIME_EXPORTS = {
    "MAX_TOOL_ARGUMENT_BYTES",
    "MAX_TOOL_OUTPUT_BYTES",
    "ToolAuthorizationContext",
    "ToolExecutionResult",
    "ToolHandler",
    "ToolInvocation",
    "ToolRuntime",
    "ToolRuntimeError",
}

EXPECTED_LAZY_IMAGE_HELPER_EXPORTS = {
    "IMAGE_ERROR_CODES",
    "ImageContractError",
    "ImageInspection",
    "ImageOutput",
    "inspect_image",
    "sanitize_metadata",
    "thumbnail_image",
    "transform_image",
}

#: Every lazy group, mapped to the submodule that owns it.
EXPECTED_LAZY_EXPORT_OWNERS = {
    **{name: "tool_runtime" for name in EXPECTED_LAZY_ONLY_TOOL_RUNTIME_EXPORTS},
    **{name: "image_helpers" for name in EXPECTED_LAZY_IMAGE_HELPER_EXPORTS},
}


def _direct_export_owners() -> dict[str, set[str]]:
    tree = ast.parse(INIT_PATH.read_text(encoding="utf-8"), filename=str(INIT_PATH))
    owners: dict[str, set[str]] = {}

    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level != 1 or not node.module:
            continue
        for alias in node.names:
            owners.setdefault(alias.asname or alias.name, set()).add(node.module)

    return owners


def _resolved_owner_map() -> dict[str, str]:
    direct = _direct_export_owners()
    exported = set(core.__all__)
    lazy_declared = set(core._TOOL_RUNTIME_EXPORTS) | set(
        core._IMAGE_HELPER_EXPORTS
    )

    ambiguous = {
        name: modules
        for name, modules in direct.items()
        if name in exported and len(modules) != 1
    }
    assert ambiguous == {}

    lazy_only = lazy_declared - set(direct)
    expected_lazy_only = set(EXPECTED_LAZY_EXPORT_OWNERS)
    assert lazy_only == expected_lazy_only
    assert lazy_declared == expected_lazy_only | EXPECTED_DIRECT_TOOL_RUNTIME_EXPORTS

    owner_map: dict[str, str] = {}
    for name in exported:
        modules = direct.get(name, set())
        if modules:
            owner_map[name] = next(iter(modules))
        elif name in lazy_only:
            owner_map[name] = EXPECTED_LAZY_EXPORT_OWNERS[name]

    return owner_map


def test_every_root_export_has_one_owning_submodule() -> None:
    owner_map = _resolved_owner_map()

    assert set(owner_map) == set(core.__all__)
    assert all(owner_map[name] for name in core.__all__)


def test_every_owning_submodule_exists_in_the_package() -> None:
    owner_modules = set(_resolved_owner_map().values())
    missing = {
        module
        for module in owner_modules
        if not (PACKAGE_DIR / f"{module}.py").is_file()
    }

    assert missing == set()


def test_recommended_specialized_import_path_is_defined_for_every_root_export() -> None:
    owner_map = _resolved_owner_map()
    recommended = {
        name: f"padiem_ai_core.{module}"
        for name, module in owner_map.items()
    }

    assert set(recommended) == set(core.__all__)
    assert all(path.startswith("padiem_ai_core.") for path in recommended.values())


def test_current_runtime_compatibility_constants_have_explicit_owners() -> None:
    owner_map = _resolved_owner_map()

    assert owner_map["B14_CHAT_COMPLETIONS_PATH"] == "b14_execution"
    assert owner_map["B14_STREAM_PREVIEW_PATH"] == "b14_streaming"
    assert owner_map["MAX_B14_RESPONSE_BYTES"] == "b14_execution"
    assert owner_map["request_fingerprint"] == "execution_context"
