"""Chat static error-card polish (#7100 후속 owner screenshot).

Production follow-up after #7100: the owner's browser showed the connector
fallback failure as an error card whose status header carried an empty
ellipse pill ("AI 작업 상태" → stray icon → 00:03) and an oversized "다시
시도" button. The static bundle is served by the chat Worker's asset
deployment, so these fixes ride the next Worker release.

* a task card without a current stage must not render the
  ``.capability-current`` pill at all — both at render time and when the
  lifecycle transition clears a live label;
* the error card's retry button borrows the compact answer-action geometry
  (32px) on desktop; the mobile 44px touch-target rule stays authoritative;
* the ``orchestration_not_applicable`` refusal, wherever it still surfaces,
  reads as one general retry sentence — the compact code note carries the
  diagnostic detail.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

TESTS = Path(__file__).parent
STATIC = TESTS.parent / "static"

LIFECYCLE_SOURCE = (STATIC / "message-lifecycle.js").read_text(encoding="utf-8")
PRESENTATION_SOURCE = (STATIC / "capability-presentation.css").read_text(encoding="utf-8")
POLISH_SOURCE = (STATIC / "padiem-chat-ui-polish.css").read_text(encoding="utf-8")
STYLES_SOURCE = (STATIC / "styles.css").read_text(encoding="utf-8")
TRANSPORT = (STATIC / "chat-transport.js").read_text(encoding="utf-8")


def test_a_stageless_task_card_hides_the_status_pill():
    """빈 상태 pill은 아예 렌더링하지 않는다(헤딩과 시계 사이 깨진 아이콘 방지)."""
    render_block = LIFECYCLE_SOURCE[LIFECYCLE_SOURCE.index("status.textContent = view.statusLabel"):]
    assert "status.hidden = !view.statusLabel;" in render_block[:420]

    # The lifecycle transition that clears a live label also hides the pill.
    clear_block = LIFECYCLE_SOURCE[LIFECYCLE_SOURCE.index('if (current && !cardShowsLiveStatus(article))'):]
    assert "if (!current.textContent) current.hidden = true;" in clear_block[:400]

    # The pill is inline-flex: the hidden attribute wins only with an explicit rule.
    assert ".capability-current[hidden]" in PRESENTATION_SOURCE
    assert "display: none" in PRESENTATION_SOURCE.split(".capability-current[hidden]")[1][:120]


def test_the_error_card_retry_button_is_a_compact_secondary_control():
    """'다시 시도'는 카드 보조 버튼 크기(32px 토큰, 카드 폭 채우지 않음).

    The accepted base stylesheet (``static/styles.css``) is byte-pinned by the
    style contract, so the compact override lives in the polish layer file.
    """
    polish_block = POLISH_SOURCE.split(".app-shell .error-box .retry-button {")[1].split("}")[0]
    assert "min-height: 32px" in polish_block
    assert "width: fit-content" in polish_block
    assert "align-self: flex-start" in polish_block
    # The base stylesheet stays byte-pinned: it must not carry the override.
    assert ".error-box .retry-button {" not in STYLES_SOURCE
    # The mobile touch-target rule still overrides for small screens.
    assert ".retry-button," in (STATIC / "mobile-target-legibility.css").read_text(encoding="utf-8")


def run_node(source: str) -> dict:
    # Windows refuses a command line over ~32K characters (WinError 206), and
    # this harness embeds the whole transport source. Write it to a temp file
    # and let node execute the file instead of an inline -e script.
    import tempfile
    handle = tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False,
                                         encoding="utf-8", newline="\n")
    try:
        handle.write(source)
        handle.close()
        result = subprocess.run(
            ["node", handle.name], capture_output=True, text=True,
            encoding="utf-8", timeout=20,
            env={**os.environ, "TRANSPORT_MODULE": str(STATIC / "chat-transport.js")},
        )
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_connector_refusal_reads_as_one_general_retry_sentence():
    result = run_node("""
global.window={};
""" + TRANSPORT + """
const assert=require('node:assert/strict');
const transport=window.PadiemChatTransport;
const message=transport.streamErrorMessage(
  {error:{code:'orchestration_not_applicable',message:'이 요청은 커넥터 도구가 있는 기존 채팅 경로에서 처리합니다.'}},
  409,
);
assert.equal(message,'답변을 불러오지 못했습니다. 다시 시도해 주세요.');
console.log(JSON.stringify({generalMessage:true}));
""")


def test_the_fallback_refusal_still_hands_the_turn_to_the_main_stream():
    result = run_node("""
const assert=require('node:assert/strict');
const calls=[];
global.window={
  PadiemProductCapabilities:{get:()=>({auth:{loaded:true,ready:true,authenticated:true}})},
};
global.fetch=async(url,init)=>{
  calls.push(url);
  if(url==='/api/orchestration/status')
    return {ok:true,status:200,json:async()=>({orchestration_ready:true,authenticated:true})};
  if(url==='/api/orchestration')
    return {ok:false,status:409,json:async()=>({error:{code:'orchestration_not_applicable',message:'답변을 불러오지 못했습니다. 다시 시도해 주세요.'}})};
  if(url==='/api/chat/stream')
    return {ok:true,status:200,headers:{get:()=>'text/event-stream'}};
  throw new Error('unexpected '+url);
};
""" + TRANSPORT + """
(async()=>{
  const transport=window.PadiemChatTransport;
  await transport.requestStreaming({messages:[{role:'user',content:'이번 주 구글 캘린더 일정 알려줘'}]});
  assert.deepEqual(calls,['/api/orchestration/status','/api/orchestration','/api/chat/stream']);
  console.log(JSON.stringify({fallback:'/api/chat/stream'}));
})().catch(e=>{console.error(e);process.exitCode=1});
""")
    assert result == {"fallback": "/api/chat/stream"}
