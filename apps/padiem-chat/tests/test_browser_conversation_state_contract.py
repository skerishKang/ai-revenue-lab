from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "static" / "conversation-state.js"
APP_PATH = ROOT / "static" / "app.js"
INDEX_PATH = ROOT / "static" / "index.html"


def test_conversation_state_loads_between_transport_and_app() -> None:
    html = INDEX_PATH.read_text(encoding="utf-8")
    assert html.index('<script src="./chat-transport.js"></script>') < html.index(
        '<script src="./conversation-state.js"></script>'
    ) < html.index('<script src="./app.js"></script>')


def test_conversation_state_helper_has_bounded_browser_only_contract() -> None:
    source = STATE_PATH.read_text(encoding="utf-8")
    assert 'const MAX_MESSAGES = 20;' in source
    assert 'window.PadiemChatConversationState = Object.freeze({' in source
    assert 'fetch(' not in source
    assert 'document.' not in source
    assert 'AbortController' not in source


def test_app_delegates_conversation_data_but_keeps_request_lifecycle() -> None:
    source = APP_PATH.read_text(encoding="utf-8")
    assert 'const conversationState = window.PadiemChatConversationState;' in source
    assert 'let messages = [];' not in source
    assert 'let conversationSkill = "auto";' not in source
    assert 'let conversationId = null;' not in source
    assert 'let conversationEpoch = 0;' in source
    assert 'let activeRequestController = null;' in source
    assert 'activeRequestCancelReason = "user_cancel";' in source
    assert 'conversationState.reset();' in source
    assert 'conversationState.outboundWithUser(prompt)' in source
    assert 'conversationState.commitAssistant(outboundMessages, data.answer);' in source
    assert 'conversationState.commitAssistant(outboundMessages, answer);' in source
    assert 'conversationState.setConversationId(retryContext.conversationId);' in source


def test_conversation_state_behavior_matches_existing_tail_id_and_skill_contract() -> None:
    script = f"""
    global.window = {{}};
    require({json.dumps(str(STATE_PATH))});
    const state = window.PadiemChatConversationState;
    for (let i = 0; i < 25; i += 1) {{
      state.appendMessage({{ role: i % 2 ? "assistant" : "user", content: String(i) }});
    }}
    const outbound = state.outboundWithUser("next");
    const secondOutbound = state.outboundWithUser("again");
    state.setConversationId("conv-1");
    state.setSkill("plan");
    const idBeforeReset = state.getConversationId();
    const skillBeforeReset = state.getSkill();
    state.commitAssistant(outbound, "answer");
    const afterCommit = state.outboundWithUser("probe");
    state.reset();
    process.stdout.write(JSON.stringify({{
      outboundLength: outbound.length,
      outboundFirst: outbound[0].content,
      outboundLast: outbound[outbound.length - 1].content,
      secondOutboundFirst: secondOutbound[0].content,
      secondOutboundLast: secondOutbound[secondOutbound.length - 1].content,
      afterCommitLength: afterCommit.length,
      afterCommitPenultimate: afterCommit[afterCommit.length - 2].content,
      idBeforeReset,
      skillBeforeReset,
      idAfterReset: state.getConversationId(),
      skillAfterReset: state.getSkill(),
    }}));
    """
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(completed.stdout)
    assert data == {
        "outboundLength": 20,
        "outboundFirst": "6",
        "outboundLast": "next",
        "secondOutboundFirst": "6",
        "secondOutboundLast": "again",
        "afterCommitLength": 20,
        "afterCommitPenultimate": "answer",
        "idBeforeReset": "conv-1",
        "skillBeforeReset": "plan",
        "idAfterReset": None,
        "skillAfterReset": "auto",
    }
