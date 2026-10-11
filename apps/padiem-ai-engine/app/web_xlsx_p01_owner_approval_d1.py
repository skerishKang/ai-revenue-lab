"""#3580 fixed Engine-side proof of signed-in B62 XLSX approve OR deny.

Trust comes from an independent read-only B62 D1 receipt and the Core-issued
pause/digest. The private Service Binding credential is NOT user authority.
"""
from __future__ import annotations

import hashlib
import inspect
from collections.abc import Mapping
from typing import Any

from padiem_ai_core.agent_approval import ApprovalPause, VerifiedApprovalDecision, tool_invocation_digest
from padiem_ai_core.tool_runtime import ToolInvocation

from .web_xlsx_p01_tool_binding import RUNTIME_TOOL, TrustedWebXlsxSelectionScope, web_xlsx_p01_arguments
from .web_xlsx_p01_trusted_scope_d1 import _mapping, D1WebXlsxTrustedScopeResolver


class D1WebXlsxOwnerApprovalGrant:
    """Server-injected owner decision guard, approval grants only confirmation."""

    def __init__(self, private_b62_d1: Any) -> None:
        if not callable(getattr(private_b62_d1, "prepare", None)):
            raise ValueError("independent read-only B62 D1 binding required")
        self.db = private_b62_d1

    async def __call__(
        self, *, pause: ApprovalPause, decision: VerifiedApprovalDecision,
        invocation: ToolInvocation, continuation_ref: str,
    ) -> bool:
        if (not isinstance(pause, ApprovalPause)
                or not isinstance(decision, VerifiedApprovalDecision)
                or not isinstance(invocation, ToolInvocation)
                or invocation.tool_id != RUNTIME_TOOL
                or decision.pause_id != pause.pause_id
                or decision.outcome.value not in ("approved", "denied")
                or pause.invocation_sha256 != tool_invocation_digest(invocation)):
            return False
        args = invocation.arguments
        if not isinstance(args, Mapping):
            return False
        try:
            scope = TrustedWebXlsxSelectionScope(
                owner_id=args["owner_id"], workspace_id=args["workspace_id"],
                run_id=args["run_id"], selection_ref=args["selection_ref"],
                document_id=args["document_id"], source_sha256=args["source_sha256"],
                original_immutable=True, source_active=True,
            )
            if dict(args) != web_xlsx_p01_arguments(scope):
                return False
        except (KeyError, TypeError, ValueError):
            return False
        # Revalidate the owner, running job, immutable source and SHA BEFORE
        # issuing even a confirmation grant. The handler checks once more.
        source = await D1WebXlsxTrustedScopeResolver(
            self.db, required_status="waiting_p01",
        )(scope.selection_ref)
        if source != scope:
            return False
        owner = scope.owner_id
        outcome = decision.outcome.value
        expected_decision = "decision_b54_" + hashlib.sha256(
            f"{owner}|{pause.pause_id}|{outcome}".encode("utf-8")
        ).hexdigest()[:32]
        if (decision.decision_id != expected_decision
                or decision.authority_ref != "b54_session:" + owner
                or decision.evidence_ref != "b54_decision:" + expected_decision):
            return False
        sql = (
            "SELECT d.request_ref,d.selection_ref,d.user_id,d.workspace_id,"
            "d.run_id,d.source_sha256,d.pause_id,d.outcome,d.state,"
            "p.continuation_ref,p.document_id,p.status AS request_status "
            "FROM claw_web_xlsx_p01_decision_receipts d "
            "JOIN claw_web_xlsx_p01_requests p ON p.request_ref=d.request_ref "
            "AND p.selection_ref=d.selection_ref "
            "AND p.user_id=d.user_id AND p.workspace_id=d.workspace_id "
            "AND p.run_id=d.run_id AND p.source_sha256=d.source_sha256 "
            "AND p.pause_id=d.pause_id "
            "WHERE d.request_ref=p.request_ref AND d.selection_ref=? "
            "AND d.user_id=? AND d.workspace_id=? AND d.run_id=? "
            "AND d.source_sha256=? AND d.pause_id=? AND p.continuation_ref=? "
            "AND d.outcome=? AND d.state='dispatching' "
            "AND p.status='waiting_p01' LIMIT 1"
        )
        stmt = self.db.prepare(sql).bind(
            scope.selection_ref, owner, scope.workspace_id, scope.run_id,
            scope.source_sha256, pause.pause_id, continuation_ref,
            "approve" if outcome == "approved" else "deny",
        )
        row = stmt.first()
        if inspect.isawaitable(row):
            row = await row
        row = _mapping(row)
        return bool(
            row and row.get("document_id") == scope.document_id
            and row.get("continuation_ref") == continuation_ref
            and row.get("pause_id") == pause.pause_id
        )
