"""Shared test helper: an Agent step context backed by the tool result ledger.

#4379: the runtime keeps only references, so a step driver resolves the
results it needs through the ledger. Test doubles build the same shape.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Iterable

from padiem_ai_core.agent_tool_result_ledger import InMemoryToolResultLedger


def context_with_tool_results(
    *results: Any,
    run_id: str = "run_context",
    step_index: int = 1,
    input_text: str = "step",
) -> SimpleNamespace:
    """Build a step context whose results live in a process-local ledger."""
    ledger = InMemoryToolResultLedger()
    refs = ledger.adopt(
        run_id=run_id, step_index=step_index, results=tuple(results),
    )

    async def resolve_all() -> tuple[Any, ...]:
        return tuple([await ledger.resolve(ref) for ref in refs])

    return SimpleNamespace(
        run_id=run_id,
        step_index=step_index,
        input_text=input_text,
        tool_result_refs=refs,
        result_ledger=ledger,
        resolve_tool_result=ledger.resolve,
        resolve_tool_results=resolve_all,
    )


__all__ = ["context_with_tool_results"]
