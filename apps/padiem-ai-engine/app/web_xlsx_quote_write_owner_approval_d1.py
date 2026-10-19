"""Independent Engine/Core proof of explicit owner WRITE decision (#3933).

A reserved edit in B62 (032) is NOT an approval. Only a separate (033)
signed-in owner decision tied to the real WRITE pause, full immutable edit,
continuation and first-party Core VerifiedApprovalDecision can grant it.
"""
from __future__ import annotations

import hashlib
import inspect
from collections.abc import Mapping
from typing import Any

from padiem_ai_core.agent_approval import (
    ApprovalPause, VerifiedApprovalDecision, tool_invocation_digest,
)
from padiem_ai_core.tool_runtime import ToolInvocation

from .web_xlsx_p01_trusted_scope_d1 import _mapping
from .web_xlsx_quote_write_tool_binding import (
    RUNTIME_TOOL, TrustedQuoteWriteScope, quote_write_arguments,
)
from .web_xlsx_quote_write_scope_d1 import D1WebQuoteWriteScopeResolver


class D1WebQuoteOwnerWriteApprovalGrant:
    """Always read independently from private B62 D1; never from HTTP args."""

    def __init__(self, private_b62_d1: Any):
        if not callable(getattr(private_b62_d1, "prepare", None)):
            raise ValueError("independent read-only B62 D1 required")
        self._db = private_b62_d1

    async def __call__(self, *, pause: ApprovalPause,
                       decision: VerifiedApprovalDecision,
                       invocation: ToolInvocation,
                       continuation_ref: str) -> bool:
        if (not isinstance(pause, ApprovalPause)
                or not isinstance(decision, VerifiedApprovalDecision)
                or not isinstance(invocation, ToolInvocation)
                or invocation.tool_id != RUNTIME_TOOL
                or pause.tool_id != RUNTIME_TOOL
                or decision.pause_id != pause.pause_id
                or decision.outcome.value not in ("approved", "denied")
                or pause.invocation_sha256 != tool_invocation_digest(invocation)):
            return False
        args = invocation.arguments
        if not isinstance(args, Mapping):
            return False
        ref = args.get("selection_ref")
        if not isinstance(ref, str):
            return False
        resolver = D1WebQuoteWriteScopeResolver(self._db)
        current = await resolver(ref)
        if not isinstance(current, TrustedQuoteWriteScope):
            return False
        if dict(args) != quote_write_arguments(current):
            return False

        outcome = decision.outcome.value
        owner = current.owner_id
        did = "decision_b54_" + hashlib.sha256(
            f"{owner}|{pause.pause_id}|{outcome}".encode("utf-8")
        ).hexdigest()[:32]
        if (decision.decision_id != did
                or decision.authority_ref != "b54_session:" + owner
                or decision.evidence_ref != "b54_decision:" + did):
            return False

        sql = (
            "SELECT d.selection_ref,d.pause_id,d.continuation_ref,"
            "d.user_id,d.workspace_id,d.run_id,d.source_document_id,"
            "d.source_sha256,d.workcopy_document_id,d.edit_sha256,"
            "d.outcome,d.state "
            "FROM claw_web_xlsx_quote_write_decisions d "
            "JOIN claw_web_xlsx_quote_edit_receipts e ON "
            "e.selection_ref=d.selection_ref AND e.user_id=d.user_id "
            "AND e.workspace_id=d.workspace_id AND e.run_id=d.run_id "
            "AND e.source_document_id=d.source_document_id "
            "AND e.source_sha256=d.source_sha256 "
            "AND e.workcopy_document_id=d.workcopy_document_id "
            "AND e.edit_sha256=d.edit_sha256 "
            "WHERE d.selection_ref=? AND d.pause_id=? "
            "AND d.continuation_ref=? AND d.outcome=? "
            "AND d.state='dispatching' AND e.state='dispatching' LIMIT 1"
        )
        item = self._db.prepare(sql).bind(
            ref, pause.pause_id, continuation_ref,
            "approve" if outcome == "approved" else "deny",
        ).first()
        item = await item if inspect.isawaitable(item) else item
        item = _mapping(item)
        return bool(item and all(item.get(column) == getattr(current, attribute)
                                 for column, attribute in (
            ("user_id", "owner_id"), ("workspace_id", "workspace_id"),
            ("run_id", "run_id"), ("source_document_id", "source_document_id"),
            ("source_sha256", "source_sha256"),
            ("workcopy_document_id", "workcopy_document_id"),
            ("edit_sha256", "edit_sha256"),
        )))
