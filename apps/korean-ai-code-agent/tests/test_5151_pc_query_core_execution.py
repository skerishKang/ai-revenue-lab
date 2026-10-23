"""#5151 — the product-side PC query assembly runs on the existing Core runtime.

The product adapter owns the PC tool contract (#5209). This suite drives that
contract through the existing Core ``AgentPlanExecutor``/``ToolRuntime`` with a
synthetic drive tool, so the whole flow is exercised offline:

    step selection -> synthetic drive tool -> tool result re-fed -> complete

A synthetic tool success is a local assembly proof only. It is not a PC
connection, not a dispatch and not an operational transition.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from kagent import pc_query_adapter as product_adapter
from kagent.pc_query_core_execution import (
    PcQueryCoreRequest,
    run_pc_query_with_core,
)

from padiem_ai_core.agent_definition import AgentTerminalReason
from padiem_ai_core.agent_runtime import AgentRuntimeError
from padiem_ai_core.tool_runtime import ToolInvocation, ToolRuntime

REPO_ROOT = Path(__file__).resolve().parents[3]
ADAPTER_PATH = REPO_ROOT / "apps" / "korean-ai-code-agent" / "src" / "kagent" / "pc_query_adapter.py"
EXECUTION_PATH = REPO_ROOT / "apps" / "korean-ai-code-agent" / "src" / "kagent" / "pc_query_core_execution.py"

CLAW = product_adapter.CLAW_APP_ID
CHAT = product_adapter.CHAT_APP_ID
DRIVE_TOOL_ID = product_adapter.PC_DRIVES_TOOL_ID
DEVICE_ID = "pc-com2"
SUBJECT_ID = "sub_" + "5" * 32
RUN_ID = "run_5151_core_execution"
INPUT_TEXT = "내 PC 드라이브 목록 알려줘"
ANSWER = "확인된 PC 드라이브: C:/ (250GB free)"


def _contract(app_id: str = CLAW, agent_id: str = product_adapter.PC_QUERY_AGENT_ID):
    return product_adapter.build_pc_query_product_contract(
        app_id=app_id, agent_id=agent_id,
    )


def _synthetic_runtime(observed: list[dict]) -> ToolRuntime:
    """A Core ToolRuntime carrying a synthetic drive tool.

    The handler never reaches a PC: it records the owner context and the
    trusted target it was called with and returns a canned inventory.
    """
    runtime = ToolRuntime()

    async def synthetic_query_drives(arguments):
        owner = product_adapter.PC_QUERY_OWNER.get()
        observed.append({"arguments": dict(arguments), "owner": owner})
        return {
            "dispatch_id": "dispatch_synthetic_5151",
            "output": '[{"Name":"C:","Root":"C:\\\\","Used":1,"Free":2}]',
            "result_sha256": "0" * 64,
            "execution_confirmed": True,
            "termination": "exited",
            "exit_code": 0,
        }

    runtime.register(product_adapter.pc_drives_tool_spec(), synthetic_query_drives)
    return runtime


def _request(*, device_id: str | None = DEVICE_ID, runtime: ToolRuntime | None = None):
    return PcQueryCoreRequest(
        contract=_contract(),
        tool_runtime=runtime if runtime is not None else _synthetic_runtime([]),
        input_text=INPUT_TEXT,
        run_id=RUN_ID,
        subject_id=SUBJECT_ID,
        device_id=device_id,
    )


class _RecordingStepSelector:
    """Model step selection: one drive call, then a completion."""

    def __init__(self, *, arguments: dict | None = None) -> None:
        self.calls: list[dict] = []
        self._arguments = arguments

    async def __call__(self, *, context, compiled_profile, observations):
        self.calls.append({
            "step_index": context.step_index,
            "run_id": context.run_id,
            "input_text": context.input_text,
            "observations": observations,
        })
        if context.tool_results:
            return {"action": "complete", "answer": ANSWER}
        return {
            "action": "tool",
            "tool_id": DRIVE_TOOL_ID,
            "arguments": self._arguments if self._arguments is not None else {},
        }


def test_core_assembly_runs_step_tool_result_and_completion() -> None:
    observed: list[dict] = []
    runtime = _synthetic_runtime(observed)
    selector = _RecordingStepSelector()

    outcome = asyncio.run(run_pc_query_with_core(
        request=_request(runtime=runtime), select_step=selector,
    ))

    assert outcome.completed is True
    assert outcome.answer == ANSWER
    assert outcome.terminal_reason is AgentTerminalReason.COMPLETED
    assert outcome.steps_executed == 2
    assert outcome.tool_calls == 1
    assert outcome.run_id == RUN_ID

    # The tool result was re-fed into the next step, so the model completed
    # from a verified observation instead of a first-step guess.
    assert len(selector.calls) == 2
    first, second = selector.calls
    assert first["observations"] == ()
    assert len(second["observations"]) == 1
    observation = second["observations"][0]
    assert observation["tool_id"] == DRIVE_TOOL_ID
    assert observation["output"]["dispatch_id"] == "dispatch_synthetic_5151"
    assert "C:" in observation["output"]["output"]
    assert second["run_id"] == RUN_ID
    assert second["input_text"] == INPUT_TEXT


def test_trusted_selected_pc_is_delivered_to_the_tool() -> None:
    observed: list[dict] = []
    runtime = _synthetic_runtime(observed)
    selector = _RecordingStepSelector()

    outcome = asyncio.run(run_pc_query_with_core(
        request=_request(runtime=runtime), select_step=selector,
    ))

    assert outcome.device_id == DEVICE_ID
    assert len(observed) == 1
    # The server-chosen target reaches the tool as the trusted plan argument.
    assert observed[0]["arguments"] == {"device_id": DEVICE_ID}
    # The verified owner run reaches the tool through the shared owner context.
    assert observed[0]["owner"] == (SUBJECT_ID, RUN_ID, CLAW, DEVICE_ID)


def test_model_named_pc_is_refused_and_the_tool_never_runs() -> None:
    observed: list[dict] = []
    runtime = _synthetic_runtime(observed)
    selector = _RecordingStepSelector(arguments={"device_id": "pc-attacker"})

    with pytest.raises(AgentRuntimeError) as err:
        asyncio.run(run_pc_query_with_core(
            request=_request(runtime=runtime), select_step=selector,
        ))

    assert err.value.code == "agent_step_failed"
    assert observed == [], "a model-named target must never reach the tool"


def test_product_identity_and_result_correlation_are_preserved() -> None:
    chat_outcome = asyncio.run(run_pc_query_with_core(
        request=PcQueryCoreRequest(
            contract=_contract(CHAT, product_adapter.CHAT_PC_QUERY_AGENT_ID),
            tool_runtime=_synthetic_runtime([]),
            input_text=INPUT_TEXT,
            run_id=RUN_ID,
            subject_id=SUBJECT_ID,
            device_id=DEVICE_ID,
        ),
        select_step=_RecordingStepSelector(),
    ))
    assert chat_outcome.product_app_id == CHAT
    assert chat_outcome.agent_id == product_adapter.CHAT_PC_QUERY_AGENT_ID
    assert chat_outcome.completed is True

    claw_outcome = asyncio.run(run_pc_query_with_core(
        request=_request(), select_step=_RecordingStepSelector(),
    ))
    assert claw_outcome.product_app_id == CLAW
    assert claw_outcome.agent_id == product_adapter.PC_QUERY_AGENT_ID
    assert claw_outcome.run_id == RUN_ID


def test_mixed_product_contract_fails_closed() -> None:
    contract = _contract(CHAT, product_adapter.CHAT_PC_QUERY_AGENT_ID)
    broken = product_adapter.PcQueryProductContract(
        app_id=CLAW,
        agent_id=contract.agent_id,
        definition=contract.definition,
        compiled=contract.compiled,
        authorization=contract.authorization,
        registry_entries=contract.registry_entries,
    )
    with pytest.raises(ValueError):
        asyncio.run(run_pc_query_with_core(
            request=PcQueryCoreRequest(
                contract=broken,
                tool_runtime=_synthetic_runtime([]),
                input_text=INPUT_TEXT,
                run_id=RUN_ID,
                subject_id=SUBJECT_ID,
                device_id=DEVICE_ID,
            ),
            select_step=_RecordingStepSelector(),
        ))


@pytest.mark.parametrize(
    "app_id,agent_id",
    [
        (CHAT, product_adapter.PC_QUERY_AGENT_ID),
        (CLAW, product_adapter.CHAT_PC_QUERY_AGENT_ID),
    ],
)
def test_contract_builder_refuses_a_crossed_product_pair(app_id, agent_id) -> None:
    """A Chat app id with the Claw agent id (or the reverse) is refused."""
    with pytest.raises(ValueError):
        _contract(app_id, agent_id)


def test_execution_refuses_a_crossed_product_pair_even_when_self_consistent() -> None:
    """Self-consistency is not enough: only a reviewed app/agent pair passes."""
    chat = _contract(CHAT, product_adapter.CHAT_PC_QUERY_AGENT_ID)
    crossed = product_adapter.PcQueryProductContract(
        app_id=CHAT,
        agent_id=product_adapter.PC_QUERY_AGENT_ID,
        definition=chat.definition,
        compiled=chat.compiled,
        authorization=chat.authorization,
        registry_entries=chat.registry_entries,
    )
    with pytest.raises(ValueError):
        asyncio.run(run_pc_query_with_core(
            request=PcQueryCoreRequest(
                contract=crossed,
                tool_runtime=_synthetic_runtime([]),
                input_text=INPUT_TEXT,
                run_id=RUN_ID,
                subject_id=SUBJECT_ID,
                device_id=DEVICE_ID,
            ),
            select_step=_RecordingStepSelector(),
        ))


def test_reviewed_product_pairs_are_accepted() -> None:
    """The two reviewed pairs keep working end to end."""
    for app_id, agent_id in product_adapter.PC_QUERY_PRODUCT_AGENTS.items():
        outcome = asyncio.run(run_pc_query_with_core(
            request=PcQueryCoreRequest(
                contract=_contract(app_id, agent_id),
                tool_runtime=_synthetic_runtime([]),
                input_text=INPUT_TEXT,
                run_id=RUN_ID,
                subject_id=SUBJECT_ID,
                device_id=DEVICE_ID,
            ),
            select_step=_RecordingStepSelector(),
        ))
        assert outcome.product_app_id == app_id
        assert outcome.agent_id == agent_id
        assert outcome.completed is True


@pytest.mark.parametrize("path", [ADAPTER_PATH, EXECUTION_PATH])
def test_product_side_modules_import_no_engine_application_module(path: Path) -> None:
    """The product side must not reach back into the Engine app."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
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
        f"{path.name} must not import Engine application modules: {engine_imports}"
    )


def test_tool_invocation_is_built_from_the_trusted_plan_argument() -> None:
    """The step policy substitutes the trusted argument for the model's empty one."""
    driver = product_adapter.StructuredPCQueryStepDriver(
        select_step=_RecordingStepSelector(),
        static_arguments=product_adapter.pc_query_plan_arguments(DEVICE_ID),
    )

    class _Context:
        run_id = RUN_ID
        step_index = 1
        input_text = INPUT_TEXT
        tool_results: tuple = ()

    decision = asyncio.run(driver.next_step(_Context(), None))
    assert isinstance(decision.invocation, ToolInvocation)
    assert decision.invocation.tool_id == DRIVE_TOOL_ID
    assert decision.invocation.arguments == {"device_id": DEVICE_ID}
