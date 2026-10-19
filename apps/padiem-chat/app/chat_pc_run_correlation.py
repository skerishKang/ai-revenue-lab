"""Offline correlation between an executed PC query run and the session row.

The b62 Chat product already owns the session/conversation contract: a PC
query run is staged as an owner-scoped run row whose conversation and
workspace linkage is immutable (``record_claw_run`` refuses a transfer to a
different conversation or workspace). This module reuses exactly that
contract to prove, offline, that the run a product-side PC query executed is
the same owner-scoped run that links to the conversation.

Proof scope
-----------
What this module proves is the **owner-scoped run ↔ conversation/workspace
linkage**. It does not verify a login session, a browser session or any
authentication state: the owner scope is the existing store's, and this
module only reads through it.

It adds no store, no session and no authority:

* the run row is read through the existing store method
  (``get_claw_run(user_id, run_id)``) and is never written;
* the conversation and workspace are read from that row, never supplied by a
  caller, so the answer's destination stays the one the product staged;
* the verdict is a bounded status code, never a free-text reason.

A verdict of ``correlated`` additionally requires an execution result that was
compared with the requested run and a row that links that run to a valid
conversation and workspace. Looking up the stored run alone is reported as
``run_only`` — the linkage is known, the executed-run correlation is not
proven.

Nothing here reaches a PC, a model, the Engine or the network: it is a
correlation check over the existing durable row and an already executed run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kagent.pc_query_core_execution import PcQueryCoreOutcome

from .history import validate_conversation_id
from .workspace_storage import _safe_identifier

# Bounded verdict codes. No free-text reason ever leaves this module.
CORRELATION_CORRELATED = "correlated"
CORRELATION_RUN_ONLY = "run_only"
CORRELATION_RUN_MISMATCH = "run_mismatch"
CORRELATION_RUN_NOT_FOUND = "run_not_found"
CORRELATION_LINK_MISSING = "link_missing"
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


def _valid_link(conversation_id: object, workspace_id: object) -> tuple[str | None, str | None]:
    """The conversation/workspace link of one run row, or ``(None, None)``.

    Both identifiers are checked with the validators the store itself used
    when it wrote the row, so a row without a valid link is never reported
    as a correlated run.
    """
    conversation = None
    try:
        conversation = validate_conversation_id(conversation_id)
    except ValueError:
        conversation = None
    if not isinstance(conversation, str) or not conversation:
        return None, None
    workspace = None
    try:
        workspace = _safe_identifier("workspace_id", workspace_id)
    except (TypeError, ValueError):
        workspace = None
    if not isinstance(workspace, str) or not workspace:
        return None, None
    return conversation, workspace


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

    The verdict is ``correlated`` only when an execution result was compared
    *and* the owner-scoped row links that run to a valid conversation and
    workspace. Without an execution result the linkage alone is reported as
    ``run_only``.
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

    row_run_id = row.get("run_id")
    if isinstance(row_run_id, str) and row_run_id and row_run_id != bounded_run:
        # The row the store returned is not the requested run.
        return PcQueryRunCorrelation(
            run_id=bounded_run,
            user_id=bounded_user,
            status=CORRELATION_RUN_MISMATCH,
            product_app_id=outcome.product_app_id if outcome is not None else None,
            agent_id=outcome.agent_id if outcome is not None else None,
        )

    conversation_id, workspace_id = _valid_link(
        row.get("conversation_id"), row.get("workspace_id"),
    )
    if conversation_id is None or workspace_id is None:
        # The row exists but does not link the run to a conversation and a
        # workspace: the answer has no proven destination.
        return PcQueryRunCorrelation(
            run_id=bounded_run,
            user_id=bounded_user,
            status=CORRELATION_LINK_MISSING,
            product_app_id=outcome.product_app_id if outcome is not None else None,
            agent_id=outcome.agent_id if outcome is not None else None,
        )

    return PcQueryRunCorrelation(
        run_id=bounded_run,
        user_id=bounded_user,
        status=CORRELATION_CORRELATED if outcome is not None else CORRELATION_RUN_ONLY,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        product_app_id=outcome.product_app_id if outcome is not None else None,
        agent_id=outcome.agent_id if outcome is not None else None,
    )


__all__ = [
    "CORRELATION_CORRELATED",
    "CORRELATION_INVALID_REQUEST",
    "CORRELATION_LINK_MISSING",
    "CORRELATION_RUN_MISMATCH",
    "CORRELATION_RUN_NOT_FOUND",
    "CORRELATION_RUN_ONLY",
    "PcQueryRunCorrelation",
    "verify_pc_query_run_correlation",
]
