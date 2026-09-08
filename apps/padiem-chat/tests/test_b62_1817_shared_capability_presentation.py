from __future__ import annotations

import json
import subprocess
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE_PATH = APP_ROOT / "static" / "message-lifecycle.js"
CAPABILITY_CSS_PATH = APP_ROOT / "static" / "capability-presentation.css"


def _run_node(script: str) -> dict:
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _bootstrap(source: str) -> str:
    return r'''
global.window = globalThis;
global.document = {
  readyState: "loading",
  documentElement: {lang: "ko"},
  addEventListener() {},
};
global.CustomEvent = class CustomEvent {
  constructor(type, options = {}) {
    this.type = type;
    this.bubbles = Boolean(options.bubbles);
    this.detail = options.detail;
  }
};
''' + source


def test_shared_capability_presentation_groups_safe_normalized_events() -> None:
    source = LIFECYCLE_PATH.read_text(encoding="utf-8")
    script = _bootstrap(source) + r'''
const orchestration = {
  events: [
    {event_id:"evt_1",run_id:"run_1",trace_id:"trace_1",app_id:"padiem-chat",kind:"run_started",sequence:1,metadata:{hidden_reasoning:"DO_NOT_RENDER"}},
    {event_id:"evt_2",run_id:"run_1",trace_id:"trace_1",app_id:"padiem-chat",kind:"context_prepared",sequence:2,metadata:{private_memory:"DO_NOT_RENDER"}},
    {event_id:"evt_3",run_id:"run_1",trace_id:"trace_1",app_id:"padiem-chat",kind:"memory_read",sequence:3},
    {event_id:"evt_4",run_id:"run_1",trace_id:"trace_1",app_id:"padiem-chat",kind:"tool_started",sequence:4,metadata:{tool_arguments:"DO_NOT_RENDER"}},
    {event_id:"evt_5",run_id:"run_1",trace_id:"trace_1",app_id:"padiem-chat",kind:"tool_completed",sequence:5},
    {event_id:"evt_6",run_id:"run_1",trace_id:"trace_1",app_id:"padiem-chat",kind:"evidence_attached",sequence:6},
    {event_id:"evt_7",run_id:"run_1",trace_id:"trace_1",app_id:"padiem-chat",kind:"verification_completed",sequence:7},
  ],
};
const base = PadiemChatOrchestrationUI.viewModel(orchestration);
const presentation = PadiemChatCapabilityPresentation.presentationModel(base, null, false);
console.log(JSON.stringify({base, presentation}));
'''
    result = _run_node(script)
    presentation = result["presentation"]
    assert presentation["valid"] is True
    assert [item["group"] for item in presentation["stages"]] == ["agent", "context", "tool", "evidence"]
    assert presentation["latest"]["group"] == "evidence"
    assert presentation["evidenceAvailable"] is True
    serialized = json.dumps(presentation, ensure_ascii=False)
    for forbidden in ("DO_NOT_RENDER", "hidden_reasoning", "private_memory", "tool_arguments"):
        assert forbidden not in serialized


def test_shared_capability_presentation_covers_approval_and_terminal_states() -> None:
    source = LIFECYCLE_PATH.read_text(encoding="utf-8")
    script = _bootstrap(source) + r'''
const orchestration = {
  events: [
    {event_id:"evt_1",run_id:"run_1",trace_id:"trace_1",app_id:"padiem-chat",kind:"run_started",sequence:1},
    {event_id:"evt_2",run_id:"run_1",trace_id:"trace_1",app_id:"padiem-chat",kind:"approval_paused",sequence:2},
  ],
  approval_pause:{status:"paused",continuation_id:"pause_1",requirement:"user_confirmation",expires_at:"2099-01-01T00:00:00Z"},
  continuation_ref:"cont_SyntheticSafeRef_12345",
};
const base = PadiemChatOrchestrationUI.viewModel(orchestration);
const preview = PadiemChatCapabilityPresentation.presentationModel(base, "timed_out", true);
console.log(JSON.stringify({preview, terminals:PadiemChatCapabilityPresentation.terminalCatalog}));
'''
    result = _run_node(script)
    preview = result["preview"]
    assert preview["preview"] is True
    assert preview["approval"]["requirement"] == "user_confirmation"
    assert preview["terminal"] == {
        "key": "timed_out",
        "state": "timed_out",
        "label": "응답 시간이 지나 작업을 마치지 못했습니다.",
    }
    assert set(result["terminals"]) == {"completed", "failed", "cancelled", "timed_out"}


def test_deterministic_preview_is_explicit_synthetic_and_complete() -> None:
    source = LIFECYCLE_PATH.read_text(encoding="utf-8")
    script = _bootstrap(source) + r'''
console.log(JSON.stringify({
  fixtureIds:PadiemChatCapabilityPreview.fixtures.map((item) => item.id),
  enabled:PadiemChatCapabilityPreview.enabled(),
}));
'''
    result = _run_node(script)
    assert result["enabled"] is False
    assert result["fixtureIds"] == [
        "agent",
        "memory",
        "tool-completed",
        "tool-failed",
        "approval",
        "approval-resumed",
        "evidence",
        "completed",
        "failed",
        "cancelled",
        "timed-out",
    ]
    assert 'get("capability-preview") === "synthetic"' in source
    assert 'article.dataset.capabilityPreview = "synthetic"' in source
    assert "실제 Agent·Tool·Memory 실행이나 승인 권한을 나타내지 않습니다" in source
    assert "model.preview" in source


def test_presentation_kit_preserves_b62_authority_boundaries() -> None:
    source = LIFECYCLE_PATH.read_text(encoding="utf-8")
    css = CAPABILITY_CSS_PATH.read_text(encoding="utf-8")
    assert "PadiemChatCapabilityPresentation" in source
    assert "requiresTrustedDecision: true" in source
    assert "/internal/v1/orchestrate" not in source
    assert "authority_ref" not in source
    assert "decision_id" not in source
    assert "tool_arguments" not in source
    assert "hidden_reasoning" not in source
    assert "private_memory" not in source
    assert "min-height: 44px" in css
    assert "@media (max-width: 700px)" in css
    assert "prefers-reduced-motion" in css
