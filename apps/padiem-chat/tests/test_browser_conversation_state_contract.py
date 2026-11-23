from __future__ import annotations

import json
import subprocess

# #8060: shipped reads live in _support; the contracts stay unchanged.
from _support import browser_conversation_state_source as sheets


def test_conversation_state_loads_between_transport_and_app() -> None:
    html = sheets.index_html()
    assert html.index('<script src="./chat-transport.js"></script>') < html.index(
        '<script src="./conversation-state.js"></script>'
    ) < html.index('<script src="./app.js"></script>')


def test_conversation_state_helper_has_no_model_input_tail_and_no_network() -> None:
    source = sheets.state_source()
    assert 'const MAX_MESSAGES = 20;' not in source
    assert 'slice(-MAX_MESSAGES)' not in source
    assert 'window.PadiemChatConversationState = Object.freeze({' in source
    assert 'fetch(' not in source
    assert 'document.' not in source
    assert 'AbortController' not in source


def test_app_delegates_conversation_data_but_keeps_request_lifecycle() -> None:
    source = sheets.app_source()
    conv = sheets.conversation_module()  # #7216 R5 step 5a
    stream = sheets.streaming_module()  # #7216 R5 step 5b
    assert 'const conversationState = window.PadiemChatConversationState;' in source
    assert 'let messages = [];' not in source
    assert 'let conversationSkill = "auto";' not in source
    assert 'let conversationId = null;' not in source
    assert 'let conversationEpoch = 0;' in source
    assert 'let activeRequestController = null;' in source
    assert 'deps.activeRequestCancelReason = "user_cancel";' in stream
    assert 'deps.conversationState.reset();' in conv
    assert 'conversationState.outboundWithUser(prompt)' in source
    assert 'deps.conversationState.commitAssistant(outboundMessages, data.answer);' in stream
    assert 'deps.conversationState.commitAssistant(outboundMessages, answer);' in stream
    assert 'conversationState.setConversationId(retryContext.conversationId);' in source


def test_conversation_state_preserves_all_model_turns_and_id_skill_contract() -> None:
    script = f"""
    global.window = {{}};
    require({json.dumps(sheets.state_path())});
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
        text=True, encoding="utf-8",
    )
    data = json.loads(completed.stdout)
    assert data == {
        "outboundLength": 26,
        "outboundFirst": "0",
        "outboundLast": "next",
        "secondOutboundFirst": "0",
        "secondOutboundLast": "again",
        "afterCommitLength": 28,
        "afterCommitPenultimate": "answer",
        "idBeforeReset": "conv-1",
        "skillBeforeReset": "plan",
        "idAfterReset": None,
        "skillAfterReset": "auto",
    }

def test_removed_model_input_caps_are_absent_from_the_server_modules() -> None:
    """A4/A5: the legacy caps were names only; they are gone, not merely None."""

    from app import b66_ai_conversation, request_contract

    for name in ("MAX_MESSAGES", "MAX_MESSAGE_CHARS", "MAX_TOTAL_MESSAGE_CHARS"):
        assert not hasattr(request_contract, name), name
    for name in ("MAX_MESSAGE_CHARS", "MAX_REPLY_CHARS"):
        assert not hasattr(b66_ai_conversation, name), name
        assert name not in b66_ai_conversation.__all__, name
