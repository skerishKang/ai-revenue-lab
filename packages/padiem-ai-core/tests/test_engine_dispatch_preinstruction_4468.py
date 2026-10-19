"""#4465/#4468: the shared server-time preinstruction must reach the Engine/P01/Claw
model payload, not only the B62/B66 client path.

`dispatch_preinstruction` is the one trusted per-dispatch context, and its own
docstring claims it covers "B62, B66, Engine/Claw and Core callers". These tests
drive the real Core execution runtime and assert on the actual B14 payload that
would leave the server, so a regression here is a regression in what the model
is told about "today".
"""
from __future__ import annotations

import asyncio
import re

import pytest

from padiem_ai_core.b14_execution import B14ExecutionResult
from padiem_ai_core.contracts import AgentProfile
from padiem_ai_core.dispatch_preinstruction import PREINSTRUCTION_VERSION
from padiem_ai_core.execution_runtime import ExecutionRequest, ExecutionRuntime

# The rendered context always states the sampled server date in KST.
_SERVER_TIME = re.compile(
    r"서버 기준 현재 시각: \d{4}-\d{2}-\d{2}\([월화수목금토일]\) \d{2}:\d{2}:\d{2} KST"
)


class FakeExecutor:
    """Captures the exact B14 request the runtime would dispatch."""

    def __init__(self) -> None:
        self.calls: list[object] = []

    async def execute(self, request):  # noqa: ANN001 - test double
        self.calls.append(request)
        return B14ExecutionResult(answer="ok")


def agent(**overrides) -> AgentProfile:
    values = {
        "id": "general-agent",
        "title": "General",
        "description": "General product-neutral agent",
        "system_instruction": "Answer carefully.",
        "task_type": "general",
        "optimize_for": "korean",
        "max_tokens": 700,
        "required_capabilities": ("free",),
        "model_policy": {"model": "test/route"},
    }
    values.update(overrides)
    return AgentProfile(**values)


def dispatch(system_instruction: str | None = "Answer carefully.") -> dict:
    executor = FakeExecutor()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)
    asyncio.run(runtime.run(ExecutionRequest(
        agent=agent(system_instruction=system_instruction),
        messages=({"role": "user", "content": "오늘 기준으로 알려줘"},),
        trace_id="trace-4468",
        session_id="session-4468",
    )))
    assert len(executor.calls) == 1
    return executor.calls[0].to_payload()


def system_message(payload: dict) -> str:
    systems = [m for m in payload["messages"] if m["role"] == "system"]
    # The single server-owned system role is a load-bearing invariant.
    assert len(systems) == 1, f"expected exactly one system message, got {len(systems)}"
    return systems[0]["content"]


def test_engine_payload_carries_the_versioned_server_date_preinstruction() -> None:
    content = system_message(dispatch())
    assert PREINSTRUCTION_VERSION in content
    assert _SERVER_TIME.search(content), content


def test_the_product_instruction_survives_after_the_preinstruction() -> None:
    content = system_message(dispatch())
    assert "Answer carefully." in content
    assert content.index(PREINSTRUCTION_VERSION) < content.index("Answer carefully.")


def test_a_dispatch_without_a_product_instruction_still_gets_the_server_date() -> None:
    """CENTRAL decision: inject on every real model call, instruction or not."""
    content = system_message(dispatch(system_instruction=None))
    assert PREINSTRUCTION_VERSION in content
    assert _SERVER_TIME.search(content), content


def test_the_preinstruction_is_injected_exactly_once_per_dispatch() -> None:
    content = system_message(dispatch())
    assert content.count(PREINSTRUCTION_VERSION) == 1


def test_the_preinstruction_counts_toward_the_transport_envelope(monkeypatch) -> None:
    """The mandatory context must not be able to escape the 5.5MB guard."""
    import padiem_ai_core.execution_runtime as runtime_module

    pre_bytes = len(
        runtime_module.render_dispatch_preinstruction(
            runtime_module.server_wall_clock()
        ).encode("utf-8")
    )
    product = "x" * 10
    composed_bytes = pre_bytes + len("\n\n".encode("utf-8")) + len(product.encode("utf-8"))
    request = ExecutionRequest(
        agent=agent(system_instruction=product),
        messages=({"role": "user", "content": "오늘 기준으로 알려줘"},),
    )

    # A budget that fits the product instruction alone (but not the mandatory
    # preinstruction) must fail closed rather than silently dropping the date.
    monkeypatch.setattr(runtime_module, "MAX_SYSTEM_CONTEXT_BYTES", pre_bytes + 5)
    with pytest.raises(ValueError, match="transport safety envelope"):
        runtime_module._compose_system_instruction(request)

    # The same request composes once the budget accounts for the whole payload.
    monkeypatch.setattr(runtime_module, "MAX_SYSTEM_CONTEXT_BYTES", composed_bytes)
    composed = runtime_module._compose_system_instruction(request)
    assert PREINSTRUCTION_VERSION in composed
    assert product in composed
