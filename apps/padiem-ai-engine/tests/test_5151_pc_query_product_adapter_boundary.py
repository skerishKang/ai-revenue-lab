"""#5151 — the PC tool contract belongs to the product adapter.

The Engine used to own the Claw/Chat PC tool contract: the product
identities, the tool ids/scopes/specs, the signed product callback, the
drive-query execution and the step policy. This suite pins the new ownership
boundary and the unchanged behaviour:

* the product adapter owns the contract and imports no Engine module;
* the Engine module is a temporary compatibility re-export of the SAME
  objects, so the owner context, the tool ids and the step policy have
  exactly one implementation;
* the Engine binding still registers the same three tools with the same
  ids, scopes and schemas, and the step policy still refuses a
  model-selected device.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app import claw_pc_query_step_driver as engine_driver
from app.claw_pc_query_step_driver import (
    PC_DRIVES_TOOL_ID,
    PC_LIST_FILES_TOOL_ID,
    PC_READ_FILE_TOOL_ID,
    StructuredPCQueryStepDriver,
    build_claw_pc_query_tool_binding,
)
from kagent import pc_query_adapter as product_adapter

from padiem_ai_core.agent_runtime import AgentStepContext
from padiem_ai_core.tool_runtime import ToolInvocation

ADAPTER_PATH = (
    Path(__file__).resolve().parents[3]
    / "apps" / "korean-ai-code-agent" / "src" / "kagent" / "pc_query_adapter.py"
)


class _FakeService:
    async def fetch(self, request):  # pragma: no cover - never called here
        raise AssertionError("no dispatch in this suite")


def _adapter_source() -> str:
    return ADAPTER_PATH.read_text(encoding="utf-8")


def test_product_adapter_imports_no_engine_application_module() -> None:
    """The product adapter must not reach back into the Engine app."""
    tree = ast.parse(_adapter_source(), filename=str(ADAPTER_PATH))
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
        "the product adapter must not import Engine application modules: "
        f"{engine_imports}"
    )


def test_product_adapter_uses_only_core_submodule_imports() -> None:
    """Shared Core is consumed as submodules, never as a product root grab."""
    tree = ast.parse(_adapter_source(), filename=str(ADAPTER_PATH))
    root_imports = [
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "padiem_ai_core"
    ]
    assert root_imports == [], (
        "the product adapter must not import the Core package root: "
        f"{root_imports}"
    )


def test_engine_module_re_exports_the_same_contract_objects() -> None:
    """One implementation: the Engine re-export is the adapter's own object."""
    assert engine_driver.PC_DRIVES_TOOL_ID is product_adapter.PC_DRIVES_TOOL_ID
    assert engine_driver.PC_LIST_FILES_TOOL_ID is product_adapter.PC_LIST_FILES_TOOL_ID
    assert engine_driver.PC_READ_FILE_TOOL_ID is product_adapter.PC_READ_FILE_TOOL_ID
    assert engine_driver.CLAW_APP_ID is product_adapter.CLAW_APP_ID
    assert engine_driver.CHAT_APP_ID is product_adapter.CHAT_APP_ID
    assert engine_driver.PC_QUERY_AGENT_ID is product_adapter.PC_QUERY_AGENT_ID
    assert engine_driver.CHAT_PC_QUERY_AGENT_ID is product_adapter.CHAT_PC_QUERY_AGENT_ID
    assert engine_driver.StructuredPCQueryStepDriver is product_adapter.StructuredPCQueryStepDriver
    assert engine_driver.PCQueryStepError is product_adapter.PCQueryStepError
    # The owner context is set by the Engine admission lane and read by the
    # product handler: it must be the very same ContextVar object.
    assert engine_driver._PC_QUERY_OWNER is product_adapter.PC_QUERY_OWNER
    assert engine_driver._selected_device_id is product_adapter.selected_device_id
    assert engine_driver._signed_chat_call is product_adapter.signed_chat_call
    assert engine_driver._make_query_drives_handler is product_adapter.make_query_drives_handler
    assert engine_driver._plan_step_arguments is product_adapter.plan_step_arguments


def test_engine_binding_registers_the_same_three_tools() -> None:
    binding = build_claw_pc_query_tool_binding(
        service=_FakeService(), request_factory=lambda *a, **k: None,
        secret="s" * 64,
    )
    registered = binding.tool_runtime.registered_tool_ids
    assert set(registered) == {
        PC_DRIVES_TOOL_ID, PC_LIST_FILES_TOOL_ID, PC_READ_FILE_TOOL_ID,
    }
    canonical = {entry.canonical_tool_id for entry in binding.registry.entries}
    assert canonical == {
        product_adapter.PC_DRIVES_CANONICAL_TOOL_ID,
        product_adapter.PC_LIST_FILES_CANONICAL_TOOL_ID,
        product_adapter.PC_READ_FILE_CANONICAL_TOOL_ID,
    }
    authority = binding.authorities[product_adapter.PC_QUERY_AGENT_ID]
    assert authority.authorization.granted_auth_scopes == (
        product_adapter.PC_QUERY_SCOPE,
        product_adapter.PC_LIST_FILES_SCOPE,
        product_adapter.PC_READ_FILE_SCOPE,
    )


def test_step_policy_uses_the_trusted_plan_target_and_refuses_a_model_device() -> None:
    """The model may pick the tool; only the trusted plan may pick the PC."""
    calls: list[dict] = []

    async def select_step(*, context, compiled_profile, observations):
        calls.append({"action": "tool", "tool_id": PC_DRIVES_TOOL_ID, "arguments": {}})
        return {"action": "tool", "tool_id": PC_DRIVES_TOOL_ID, "arguments": {}}

    driver = StructuredPCQueryStepDriver(
        select_step=select_step, static_arguments={"device_id": "pc-server"},
    )

    class _Context:
        tool_results: tuple = ()

    decision = _run(driver.next_step(_Context(), None))
    assert decision.invocation is not None
    assert decision.invocation.tool_id == PC_DRIVES_TOOL_ID
    assert decision.invocation.arguments == {"device_id": "pc-server"}, (
        "the trusted plan argument travels; the model never names the PC"
    )
    assert calls == [{"action": "tool", "tool_id": PC_DRIVES_TOOL_ID, "arguments": {}}]

    async def select_device(*, context, compiled_profile, observations):
        return {"action": "tool", "tool_id": PC_DRIVES_TOOL_ID,
                "arguments": {"device_id": "pc-attacker"}}

    hostile = StructuredPCQueryStepDriver(
        select_step=select_device, static_arguments={"device_id": "pc-server"},
    )
    with pytest.raises(product_adapter.PCQueryStepError):
        _run(hostile.next_step(_Context(), None))


def _run(coro):
    import asyncio

    return asyncio.run(coro)
