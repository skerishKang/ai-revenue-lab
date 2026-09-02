from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
LIFECYCLE_PATH = APP_ROOT / "static" / "message-lifecycle.js"
CORE_EVENTS_PATH = REPO_ROOT / "packages" / "padiem-ai-core" / "padiem_ai_core" / "orchestration_events.py"


def _run_node(script: str) -> dict:
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_b62_orchestration_kinds_match_shared_p01_contract() -> None:
    core = CORE_EVENTS_PATH.read_text(encoding="utf-8")
    source = LIFECYCLE_PATH.read_text(encoding="utf-8")

    core_values = set(re.findall(r'^\s+[A-Z_]+ = "([a-z_]+)"$', core, flags=re.MULTILINE))
    expected = {
        "run_started",
        "context_prepared",
        "memory_read",
        "plan_created",
        "skill_resolved",
        "tool_resolution",
        "tool_started",
        "tool_completed",
        "tool_failed",
        "evidence_attached",
        "verification_completed",
        "approval_paused",
        "run_resumed",
        "recovery_started",
        "recovery_decided",
        "retry_started",
        "retry_completed",
        "run_cancelled",
        "run_failed",
        "run_completed",
    }
    assert expected == core_values
    for kind in expected:
        assert f'"{kind}"' in source


def test_orchestration_view_model_is_product_safe_and_continuation_exact() -> None:
    source = LIFECYCLE_PATH.read_text(encoding="utf-8")
    script = r'''
global.window = globalThis;
global.CustomEvent = class CustomEvent {
  constructor(type, options = {}) {
    this.type = type;
    this.bubbles = Boolean(options.bubbles);
    this.detail = options.detail;
  }
};
''' + source + r'''
const orchestration = {
  events: [
    {event_id:"evt_1",run_id:"run_1",trace_id:"trace_1",app_id:"padiem-chat",kind:"run_started",sequence:1,metadata:{secret:"DO_NOT_RENDER"}},
    {event_id:"evt_2",run_id:"run_1",trace_id:"trace_1",app_id:"padiem-chat",kind:"tool_started",sequence:2,metadata:{tool_arguments:"DO_NOT_RENDER"}},
    {event_id:"evt_3",run_id:"run_1",trace_id:"trace_1",app_id:"padiem-chat",kind:"evidence_attached",sequence:3},
    {event_id:"evt_4",run_id:"run_1",trace_id:"trace_1",app_id:"padiem-chat",kind:"approval_paused",sequence:4},
  ],
  approval_pause: {
    status:"paused",
    continuation_id:"pause_1",
    run_id:"run_1",
    trace_id:"trace_1",
    step_index:1,
    agent_id:"agent_runtime_1",
    tool_id:"private_tool_id",
    requirement:"user_confirmation",
    approval_scope:["private.scope"],
    created_at:"2026-09-03T00:00:00+00:00",
    expires_at:"2026-09-03T01:00:00+00:00",
  },
  continuation_ref:"cont_ExactOpaqueRef_12345",
};
const model = PadiemChatOrchestrationUI.viewModel(orchestration);
const approve = PadiemChatOrchestrationUI.approvalIntent(orchestration, "approved");
const deny = PadiemChatOrchestrationUI.approvalIntent(orchestration, "denied");
const cancel = PadiemChatOrchestrationUI.cancelIntent(orchestration);
console.log(JSON.stringify({model, approve, deny, cancel}));
'''
    result = _run_node(script)

    model = result["model"]
    assert model["valid"] is True
    assert model["statusText"] == "계속하기 전에 확인이 필요합니다."
    assert model["evidenceAvailable"] is True
    assert model["terminal"] is None
    assert model["approval"] == {
        "continuationRef": "cont_ExactOpaqueRef_12345",
        "pauseId": "pause_1",
        "requirement": "user_confirmation",
        "expiresAt": "2026-09-03T01:00:00+00:00",
    }
    serialized = json.dumps(model, ensure_ascii=False)
    assert "private_tool_id" not in serialized
    assert "private.scope" not in serialized
    assert "DO_NOT_RENDER" not in serialized
    assert "tool_arguments" not in serialized
    assert "secret" not in serialized

    for name, outcome in (("approve", "approved"), ("deny", "denied")):
        intent = result[name]
        assert intent == {
            "continuationRef": "cont_ExactOpaqueRef_12345",
            "pauseId": "pause_1",
            "outcome": outcome,
            "requiresTrustedDecision": True,
        }
        assert "decision_id" not in intent
        assert "authority_ref" not in intent
        assert "evidence_ref" not in intent
    assert result["cancel"] == {"continuationRef": "cont_ExactOpaqueRef_12345"}


def test_orchestration_consumer_fails_closed_on_malformed_unknown_or_reordered_events() -> None:
    source = LIFECYCLE_PATH.read_text(encoding="utf-8")
    script = r'''
global.window = globalThis;
global.CustomEvent = class CustomEvent {};
''' + source + r'''
const base = {event_id:"evt_1",run_id:"run_1",trace_id:"trace_1",app_id:"padiem-chat",kind:"run_started",sequence:1};
const unknown = PadiemChatOrchestrationUI.viewModel({events:[{...base,kind:"hidden_reasoning"}]});
const duplicate = PadiemChatOrchestrationUI.viewModel({events:[base,{...base,event_id:"evt_2",kind:"run_completed"}]});
const reordered = PadiemChatOrchestrationUI.viewModel({events:[{...base,sequence:2},{...base,event_id:"evt_2",kind:"run_completed",sequence:1}]});
const malformedApproval = PadiemChatOrchestrationUI.viewModel({
  events:[base,{...base,event_id:"evt_2",kind:"approval_paused",sequence:2}],
  approval_pause:{status:"paused",continuation_id:"pause_1",requirement:"user_confirmation",expires_at:"2026-09-03T01:00:00Z"},
  continuation_ref:"not-an-engine-continuation",
});
console.log(JSON.stringify({unknown, duplicate, reordered, malformedApproval}));
'''
    result = _run_node(script)

    assert result["unknown"]["valid"] is False
    assert result["duplicate"]["valid"] is False
    assert result["reordered"]["valid"] is False
    assert result["malformedApproval"]["valid"] is True
    assert result["malformedApproval"]["approval"] is None


def test_orchestration_presenter_does_not_claim_engine_authority_or_failure_state() -> None:
    source = LIFECYCLE_PATH.read_text(encoding="utf-8")

    assert "PadiemChatOrchestrationUI" in source
    assert "requiresTrustedDecision: true" in source
    assert "/internal/v1/orchestrate" not in source
    assert "authority_ref" not in source
    assert "evidence_ref" not in source
    assert "decision_id" not in source
    assert "tool_arguments" not in source
    assert 'card.className = "error-box' not in source
    assert "PadiemChatLifecycle.set(article, model.terminal" not in source
