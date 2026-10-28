"""#3580 cross-application: actual Engine ToolExecutionService pause wire."""
from __future__ import annotations
import pytest

from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.orchestration_service import InMemoryContinuationStore
from app.tool_execution_service import ToolExecutionEngineService
from app.web_xlsx_p01_tool_binding import (
    APP_ID, AGENT_ID, CANONICAL_TOOL, TrustedWebXlsxSelectionScope,
    build_web_xlsx_p01_tool_binding, web_xlsx_p01_arguments,
)


@pytest.mark.asyncio
async def test_real_tool_runtime_issues_canonical_web_xlsx_confirmation_pause():
    scope = TrustedWebXlsxSelectionScope(
        owner_id="owner_web_a", workspace_id="owner:web_a",
        run_id="run_web_55", selection_ref="sel_" + "a"*32,
        document_id="doc_" + "b"*32, source_sha256="c"*64,
        original_immutable=True, source_active=True,
    )
    called = []
    async def source(ref):
        called.append(ref)
        return scope
    binding = build_web_xlsx_p01_tool_binding(source)
    engine = ToolExecutionEngineService(
        tool_binding_resolver=lambda app: binding if app == APP_ID else None,
        approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
        continuation_store=InMemoryContinuationStore(),
    )
    result = await engine.execute_payload({
        "app_id": APP_ID, "agent_id": AGENT_ID,
        "tool_id": CANONICAL_TOOL,
        "arguments": web_xlsx_p01_arguments(scope),
    })
    assert result.status_code == 200, result.body
    data = result.body
    assert set(data) == {"ok", "tool"} and data["ok"] is True
    tool = data["tool"]
    assert tool["contract_version"] == "padiem.engine.tools/1.0"
    assert tool["agent_id"] == AGENT_ID
    assert tool["canonical_tool_id"] == CANONICAL_TOOL
    # Owner decision 2026-10-28: the connected owner's confirmation tool runs
    # directly — no approval pause, no continuation to resume.
    assert tool["status"] == "completed"
    assert "approval_pause" not in tool
    assert "continuation_ref" not in tool
    # The handler ran on the resolved selection (the server preflight and the
    # handler both observe it, so it never reach-evaluates a foreign source).
    assert called and called[-1] == scope.selection_ref
