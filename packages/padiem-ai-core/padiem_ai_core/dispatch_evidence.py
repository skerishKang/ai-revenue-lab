"""Server-only execution dispatch evidence.

Core exposes only a context-local fact: an admitted runtime or trusted tool
handler actually started. No billing, provider, route, cost, prompt, response,
or client authority is carried here.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(slots=True)
class ExecutionDispatchEvidence:
    dispatched: bool = False
    dispatch_count: int = 0

    def mark_started(self) -> None:
        self.dispatched = True
        self.dispatch_count += 1


_ACTIVE_DISPATCH_EVIDENCE: ContextVar[ExecutionDispatchEvidence | None] = ContextVar(
    "padiem_core_execution_dispatch_evidence",
    default=None,
)


def activate_execution_dispatch_evidence(
    evidence: ExecutionDispatchEvidence,
) -> Token[ExecutionDispatchEvidence | None]:
    if not isinstance(evidence, ExecutionDispatchEvidence):
        raise TypeError("evidence must be ExecutionDispatchEvidence")
    return _ACTIVE_DISPATCH_EVIDENCE.set(evidence)


def reset_execution_dispatch_evidence(
    token: Token[ExecutionDispatchEvidence | None],
) -> None:
    _ACTIVE_DISPATCH_EVIDENCE.reset(token)


def mark_execution_dispatch_started() -> None:
    evidence = _ACTIVE_DISPATCH_EVIDENCE.get()
    if evidence is not None:
        evidence.mark_started()
