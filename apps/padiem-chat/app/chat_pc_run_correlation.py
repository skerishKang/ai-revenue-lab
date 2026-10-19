"""Offline correlation between an executed PC query run and the session row.

The b62 Chat product already owns the session/conversation contract: a PC
query run is staged as an owner-scoped run row whose conversation and
workspace linkage is immutable (``record_claw_run`` refuses a transfer to a
different conversation or workspace). This module reuses exactly that
contract to prove, offline, that the run a product-side PC query executed is
the same run that owns the conversation.

It adds no store, no session and no authority:

* the run row is read through the existing store method
  (``get_claw_run(user_id, run_id)``) and is never written;
* the conversation and workspace are read from that row, never supplied by a
  caller, so the answer's destination stays the one the product staged;
* the verdict is a bounded status code, never a free-text reason.

Nothing here reaches a PC, a model, the Engine or the network: it is a
correlation check over the existing durable row and an already executed run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kagent.pc_query_core_execution import PcQueryCoreOutcome

# Bounded verdict codes. No free-text reason ever leaves this module.
CORRELATION_CORRELATED = "correlated"
CORRELATION_RUN_MISMATCH = "run_mismatch"
CORRELATION_RUN_NOT_FOUND = "run_not_found"
CORRELATION_INVALID_REQUEST = "invalid_request"


@dataclass(frozen=True, slots=True)
class PcQueryRunCorrelation:
    """The correlation verdict for one executed product PC query run."""

    run_id: str
    user_id: str
    status: str
    conversation_id: str | None = None
    workspace_id: str | None = None
    product_app_id: str | None = None
    agent_id: str | None = None

    @property
    def correlated(self) -> bool:
        return self.status == CORRELATION_CORRELATED


def _bounded_id(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 128:
        return None
    return value


async def verify_pc_query_run_correlation(
    *,
    store: Any,
    user_id: str,
    run_id: str,
    outcome: PcQueryCoreOutcome | None,
) -> PcQueryRunCorrelation:
    """Correlate an executed product PC query run with the existing session row.

    ``store`` is the existing history store (anything that provides
    ``get_claw_run(user_id, run_id)``). ``outcome`` is the product-side run
    result; when it is given, its run id must be the requested run id.
    """
    bounded_user = _bounded_id(user_id)
    bounded_run = _bounded_id(run_id)
    if bounded_user is None or bounded_run is None:
        return PcQueryRunCorrelation(
            run_id=bounded_run or "",
            user_id=bounded_user or "",
            status=CORRELATION_INVALID_REQUEST,
        )

    if outcome is not None:
        if not isinstance(outcome, PcQueryCoreOutcome):
            return PcQueryRunCorrelation(
                run_id=bounded_run,
                user_id=bounded_user,
                status=CORRELATION_INVALID_REQUEST,
            )
        if outcome.run_id != bounded_run:
            # The executed run is not the requested run: refuse before any
            # row is read, so no other run's conversation can be claimed.
            return PcQueryRunCorrelation(
                run_id=bounded_run,
                user_id=bounded_user,
                status=CORRELATION_RUN_MISMATCH,
                product_app_id=outcome.product_app_id,
                agent_id=outcome.agent_id,
            )

    get_claw_run = getattr(store, "get_claw_run", None)
    if not callable(get_claw_run):
        return PcQueryRunCorrelation(
            run_id=bounded_run,
            user_id=bounded_user,
            status=CORRELATION_INVALID_REQUEST,
        )
    row = await get_claw_run(bounded_user, bounded_run)
    if not isinstance(row, dict):
        # No owner-scoped row: the run was never staged for this user, or it
        # belongs to another owner. The store stays the only authority.
        return PcQueryRunCorrelation(
            run_id=bounded_run,
            user_id=bounded_user,
            status=CORRELATION_RUN_NOT_FOUND,
        )

    conversation_id = row.get("conversation_id")
    workspace_id = row.get("workspace_id")
    return PcQueryRunCorrelation(
        run_id=bounded_run,
        user_id=bounded_user,
        status=CORRELATION_CORRELATED,
        conversation_id=conversation_id if isinstance(conversation_id, str) else None,
        workspace_id=workspace_id if isinstance(workspace_id, str) else None,
        product_app_id=outcome.product_app_id if outcome is not None else None,
        agent_id=outcome.agent_id if outcome is not None else None,
    )


__all__ = [
    "CORRELATION_CORRELATED",
    "CORRELATION_INVALID_REQUEST",
    "CORRELATION_RUN_MISMATCH",
    "CORRELATION_RUN_NOT_FOUND",
    "PcQueryRunCorrelation",
    "verify_pc_query_run_correlation",
]
