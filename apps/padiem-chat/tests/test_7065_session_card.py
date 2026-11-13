"""The session card exercises real browser modules across the fetch boundary."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
HARNESS = Path(__file__).with_name("pc_session_harness.js")


@pytest.mark.parametrize("scenario", [
    "typed_only", "flow_and_offsets", "secret_confirmation", "expired_no_restore",
    "conversation_and_account", "scope_before_completion", "disabled_and_fallback",
    "bounds_enter_locale", "ended_hint_auth_errors",
])
def test_session_card(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for browser module contracts")
    result = subprocess.run([node, str(HARNESS), str(STATIC), scenario],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"passed": [scenario]}


def test_session_assets_load_after_auth_before_streaming():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('./auth-session.js') < html.index('./chat-pc-session-module.js') < html.index('./chat-streaming-module.js')
    assert 'href="./chat-pc-session.css"' in html
    assert 'id="chatPcSessionPanel"' in html
    assert "chat-pc-session" not in (STATIC / "app.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("mode", ["completed", "orchestration_json", "orchestration_stream_json", "claw_sse"])
def test_actual_completion_transport_to_session_card(monkeypatch, mode):
    import _r5_streaming_harness as streaming

    scenario = r"""
  const {setup, envelope} = require(path.join(STATIC, '../tests/pc_session_harness.js'));
  const card = setup();
  card.ctx.PadiemChatConversationState.reset();
  ctx.window.PadiemChatPcSessionModule = card.api;
  live.conversationState = card.ctx.PadiemChatConversationState;
  ctx.Response = Response;
  ctx.window.PADIEM_CHAT_ORCHESTRATION_STREAM = __MODE__ === 'orchestration_stream_json';
  const received = [];
  const data = {...envelope({output:'fixture-output', next_offset:14}), answer:'session receipt'};
  ctx.fetch = async (url, options) => {
    received.push(url);
    if (url === '/api/orchestration/status') return new Response(JSON.stringify({orchestration_ready:__MODE__ !== 'claw_sse',authenticated:true}), {headers:{'Content-Type':'application/json'}});
    if (__MODE__ === 'claw_sse') {
      return new Response('event: delta\ndata: '+JSON.stringify({delta:data.answer})+'\n\nevent: done\ndata: '+JSON.stringify({...data,done:true})+'\n\n', {headers:{'Content-Type':'text/event-stream'}});
    }
    return new Response(JSON.stringify(data), {headers:{'Content-Type':'application/json'}});
  };
  const article = makeArticle();
  const payload = {messages:[{role:'user',content:'PC session fixture'}],tier:'plus',skill:'auto'};
  if (__MODE__ === 'completed') {
    await api.requestCompletedAnswer(article,payload,payload.messages,null,{product:'chat'},new AbortController().signal);
  } else {
    await api.requestStreamingAnswer(article,payload,payload.messages,'auto',{product:'chat'},new AbortController().signal,{clawGeneral:__MODE__ === 'claw_sse'});
  }
  results.visible = !card.root.hidden;
  results.output = card.root.textContent.includes('fixture-output');
  results.sessionRequests = card.calls.length;
  results.received = received;
""".replace("__MODE__", json.dumps(mode))
    monkeypatch.setitem(streaming.SCENARIOS, "session_card_completion", scenario)
    result = streaming.run_streaming_scenario("session_card_completion")
    assert result["visible"] is True
    assert result["output"] is True
    assert result["sessionRequests"] == 0
    assert result["received"][-1] == {
        "completed": "/api/chat", "orchestration_json": "/api/orchestration",
        "orchestration_stream_json": "/api/orchestration", "claw_sse": "/api/chat/stream",
    }[mode]
