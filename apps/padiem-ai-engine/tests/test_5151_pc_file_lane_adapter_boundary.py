"""#5151 — the PC file lane and the model prompt live in the product adapter.

The Engine application must not keep its own copy: the product adapter owns the
file lane, the relative-path projection and the model step prompt, and the
Engine module is a compatibility re-export of the same objects. The owner
context stays the one shared instance, so the adapter's handlers and the
Engine's admission lane still see the same verified owner run.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app import claw_pc_query_step_driver as driver

from kagent import pc_query_adapter as product_adapter

from padiem_ai_core.tool_runtime import ToolRuntime

REPO_ROOT = Path(__file__).resolve().parents[3]
ADAPTER_PATH = (
    REPO_ROOT / "apps" / "korean-ai-code-agent" / "src" / "kagent" / "pc_query_adapter.py"
)


def test_the_product_adapter_owns_the_file_lane_and_the_prompt() -> None:
    for name in (
        "pc_files_endpoint",
        "signed_files_call",
        "validate_pc_file_arguments",
        "pc_list_folder_prefix",
        "pc_list_entries_with_paths",
        "pc_file_call_ref",
        "make_pc_file_handler",
        "build_live_pc_query_driver",
    ):
        assert hasattr(product_adapter, name), name


def test_the_engine_module_re_exports_the_same_objects() -> None:
    """One implementation: the Engine's name is the product adapter's object."""
    assert driver.make_pc_file_handler is product_adapter.make_pc_file_handler
    assert driver._make_pc_file_handler is product_adapter.make_pc_file_handler
    assert driver.pc_files_endpoint is product_adapter.pc_files_endpoint
    assert driver._pc_files_endpoint is product_adapter.pc_files_endpoint
    assert driver.signed_files_call is product_adapter.signed_files_call
    assert driver._signed_files_call is product_adapter.signed_files_call
    assert driver.pc_list_folder_prefix is product_adapter.pc_list_folder_prefix
    assert driver._pc_list_folder_prefix is product_adapter.pc_list_folder_prefix
    assert driver.pc_list_entries_with_paths is product_adapter.pc_list_entries_with_paths
    assert driver._pc_list_entries_with_paths is product_adapter.pc_list_entries_with_paths
    assert driver.validate_pc_file_arguments is product_adapter.validate_pc_file_arguments
    assert driver._validate_pc_file_arguments is product_adapter.validate_pc_file_arguments
    assert driver.pc_file_call_ref is product_adapter.pc_file_call_ref
    assert driver._pc_file_call_ref is product_adapter.pc_file_call_ref
    assert driver.build_live_pc_query_driver is product_adapter.build_live_pc_query_driver


def test_the_owner_context_stays_one_shared_instance() -> None:
    """The Engine admission lane sets it; the product handlers read it."""
    assert driver._PC_QUERY_OWNER is product_adapter.PC_QUERY_OWNER
    assert driver.PC_QUERY_OWNER is product_adapter.PC_QUERY_OWNER


def test_the_product_adapter_does_not_import_the_engine_application() -> None:
    """The product must not reach back into the Engine app."""
    tree = ast.parse(ADAPTER_PATH.read_text(encoding="utf-8"), filename=str(ADAPTER_PATH))
    engine_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app" or alias.name.startswith("app."):
                    engine_imports.append(alias.name)
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "app" or module.startswith("app."):
                engine_imports.append(module)
    assert engine_imports == [], (
        f"the product adapter must not import Engine application modules: {engine_imports}"
    )


def test_the_engine_binding_still_registers_the_same_three_tools() -> None:
    binding = driver.build_claw_pc_query_tool_binding(
        service=object(), request_factory=lambda *a, **k: None, secret="s" * 64,
    )
    assert isinstance(binding.tool_runtime, ToolRuntime)
    assert set(binding.tool_runtime.registered_tool_ids) == {
        product_adapter.PC_DRIVES_TOOL_ID,
        product_adapter.PC_LIST_FILES_TOOL_ID,
        product_adapter.PC_READ_FILE_TOOL_ID,
    }
    canonical = {entry.canonical_tool_id for entry in binding.registry.entries}
    assert canonical == {
        product_adapter.PC_DRIVES_CANONICAL_TOOL_ID,
        product_adapter.PC_LIST_FILES_CANONICAL_TOOL_ID,
        product_adapter.PC_READ_FILE_CANONICAL_TOOL_ID,
    }
    authority = binding.authorities[product_adapter.PC_QUERY_AGENT_ID]
    assert authority.authorization.app_id == product_adapter.CLAW_APP_ID
    assert authority.authorization.granted_auth_scopes == (
        product_adapter.PC_QUERY_SCOPE,
        product_adapter.PC_LIST_FILES_SCOPE,
        product_adapter.PC_READ_FILE_SCOPE,
    )
