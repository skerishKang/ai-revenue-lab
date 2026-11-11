"""#7186 R2 — 스트리밍 구역(답변 스트리밍·중단·재시도·모델 실패 처리) 계약.

R5 #7345 5b가 app.js의 스트리밍 5함수를 `chat-streaming-module.js`로 옮긴 뒤에도
계약 시험은 원문 줄·문자열을 고정했다. 이 시험은 그 자리를 실제 실행 관찰로
바꾼다. 판정 대상은 "브라우저가 하는 일"이다.

관찰하는 것:
- 보내는 요청의 method·경로·본문 (`/api/chat/stream`, `/api/chat`, `/api/pc/cancel`)
- 스트림 이벤트(생각·답변 조각·오류·thought_reset)를 넣었을 때의 화면 요소·aria·
  locale 키 변화
- #7482(PC 턴 시간 상한·확인 카드)와 #7484(생각 뒤 실패 시 1회 폴백) 계약

금지·경계 계약은 문자열로 유지하고 이유를 적는다(README §3).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from _r5_streaming_harness import run_streaming_scenario

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")

NAMES = (
    "requestCompletedAnswer",
    "applyStreamDone",
    "requestStreamingAnswer",
    "cancelActiveStream",
    "requestAnswer",
)
ASYNC_NAMES = {"requestCompletedAnswer", "requestStreamingAnswer", "requestAnswer"}


# ---------------------------------------------------------------------------
# 보내는 요청: method · 경로 · 본문
# ---------------------------------------------------------------------------
def test_streaming_answer_posts_the_payload_to_the_stream_route() -> None:
    """스트리밍 답변은 /api/chat/stream POST로 나가고 본문은 넘긴 payload 그대로다."""
    observed = run_streaming_scenario("stream_deltas_and_done")
    assert observed["ok"] is True
    request = observed["request"]
    assert request["method"] == "POST"
    assert request["path"] == "/api/chat/stream"
    assert request["body"]["messages"] == [{"role": "user", "content": "질문"}]
    assert request["body"]["tier"] == "plus"
    assert request["body"]["skill"] == "auto"


def test_completed_answer_posts_to_the_completed_route_with_attachments() -> None:
    """첨부가 있으면 완료형 경로(/api/chat POST)로 가고 첨부 본문이 실린다."""
    observed = run_streaming_scenario("completed_answer_with_attachment")
    assert observed["ok"] is True
    request = observed["request"]
    assert request["method"] == "POST"
    assert request["path"] == "/api/chat"
    assert request["body"]["attachments"] == [{"type": "file", "file_id": "file_1"}]
    assert observed["article"]["renderedAnswer"] == "완료답변"


def test_request_answer_sends_tier_and_the_pc_run_handle() -> None:
    """requestAnswer는 tier와 pc_run_id를 함께 보낸다(PC 턴 복구의 전제)."""
    observed = run_streaming_scenario("request_answer_full_path")
    assert observed["ok"] is True
    body = observed["request"]["body"]
    assert observed["request"]["path"] == "/api/chat/stream"
    assert body["tier"] == "plus"
    assert isinstance(body["pc_run_id"], str) and body["pc_run_id"]
    assert body["messages"] == [{"role": "user", "content": "질문"}]

def test_cancel_posts_the_run_id_to_the_pc_cancel_route() -> None:
    """중단은 서버 사실이다: /api/pc/cancel POST + run_id 본문."""
    observed = run_streaming_scenario("cancel_posts_run_id")
    cancel = observed["cancel"]
    assert cancel["reason"] == "user_cancel"
    assert cancel["aborted"] == 1
    assert cancel["request"]["method"] == "POST"
    assert cancel["request"]["path"] == "/api/pc/cancel"
    assert cancel["request"]["body"] == {"run_id": "run_cancel_9"}
    assert cancel["runsInvalidated"] == 1


def test_cancel_without_a_run_id_sends_no_server_request() -> None:
    """run id가 없으면 서버 취소를 보내지 않고 사용자 안내만 남긴다."""
    observed = run_streaming_scenario("cancel_without_run_id")
    cancel = observed["cancel"]
    assert cancel["reason"] == "user_cancel"
    assert cancel["aborted"] == 1
    assert cancel["request"] is None
    assert cancel["notes"] == [["answer-cancelled-note", "error"]]


def test_cancel_without_an_active_request_does_nothing() -> None:
    """진행 중인 요청이 없으면 중단은 아무 것도 하지 않는다."""
    observed = run_streaming_scenario("cancel_without_active_request")
    cancel = observed["cancel"]
    assert cancel["reason"] is None
    assert cancel["aborted"] == 0
    assert cancel["request"] is None


def test_a_second_request_is_refused_while_one_is_in_flight() -> None:
    """진행 중 재진입은 거부되고 요청이 나가지 않는다."""
    observed = run_streaming_scenario("request_answer_refused_while_in_flight")
    assert observed["ok"] is False
    assert observed["request"] is None


# ---------------------------------------------------------------------------
# 스트림 이벤트 -> 화면 요소 · aria · locale 키
# ---------------------------------------------------------------------------
def test_delta_frames_append_text_and_mark_answer_started() -> None:
    """답변 조각은 문단 텍스트로 누적되고 answer_started 단계가 기록된다."""
    observed = run_streaming_scenario("stream_deltas_and_done")
    article = observed["article"]
    assert article["text"] == "안녕하세요"
    assert article["answerStarted"] == "true"
    assert article["lifecycle"] == "completed"
    assert "answer_started" in article["events"]


def test_the_status_disclosure_opens_on_the_first_stream_frame() -> None:
    """meta 프레임에서 상태 표시가 열린다(진행 중임을 화면에 알린다)."""
    observed = run_streaming_scenario("stream_deltas_and_done")
    assert observed["article"]["disclosureOpen"] is True


def test_thought_frames_render_the_panel_and_thought_reset_collapses_it() -> None:
    """생각 조각은 패널을 그리고, thought_reset은 그 패널을 접는다(#7484)."""
    observed = run_streaming_scenario("thought_then_reset_then_answer")
    thought = observed["thought"]
    assert thought["panelExists"] is True
    # 접힌 상태로 남고, 라벨은 완료 라벨 locale 키다.
    assert thought["panelOpen"] is False
    assert thought["label"] == "orchestration-thinking-done-label"
    # reset 뒤에는 첫 모델의 생각이 남지 않고 두 번째 모델의 생각만 남는다.
    assert "첫 모델 생각" not in thought["text"]
    assert "두번째 모델 생각" in thought["text"]
    assert observed["article"]["text"] == "답변"


def test_a_stream_error_frame_renders_the_error_card_with_its_code() -> None:
    """오류 프레임은 오류 카드로 가고 lifecycle·code가 함께 전달된다."""
    observed = run_streaming_scenario("stream_error_frame")
    error = observed["error"]
    assert observed["ok"] is False
    assert error["streamErrorRenders"] == 1
    assert error["lifecycle"] == "failed"
    assert error["code"] == "upstream_unavailable"
    assert error["clawGeneral"] is False


def test_an_error_before_the_first_delta_still_ends_in_the_error_card() -> None:
    """첫 조각 전 오류도 오류 카드로 끝난다(빈 답변을 완료로 위장하지 않는다)."""
    observed = run_streaming_scenario("error_before_first_delta")
    assert observed["ok"] is False
    assert observed["error"]["streamErrorRenders"] == 1
    assert observed["error"]["lifecycle"] == "failed"
    assert observed["error"]["code"] == "upstream_unavailable"
    # 답변 문단은 만들어지지 않는다.
    assert observed["article"]["text"] is None


def test_progress_and_orchestration_frames_record_real_stages_only() -> None:
    """진행·오케스트레이션 프레임은 실제 단계만 기록한다(단계 날조 없음)."""
    observed = run_streaming_scenario("progress_and_orchestration_events")
    assert observed["ok"] is True
    events = observed["article"]["events"]
    assert "request_accepted" in events
    assert "tool_started" in events
    assert "web_search" in events
    assert observed["article"]["disclosureOpen"] is True


def test_pc_progress_and_heartbeat_frames_reach_the_lifecycle() -> None:
    """PC 진행·하트비트는 lifecycle로 전달되고 pc_work 단계가 기록된다."""
    observed = run_streaming_scenario("pc_progress_frames")
    assert observed["ok"] is True
    assert observed["article"]["pcProgress"] == [{"run_id": "run_pc_123", "step": 1}]
    assert observed["article"]["heartbeats"] == 1
    assert "pc_work" in observed["article"]["events"]


def test_stream_deltas_use_the_near_bottom_follow_hooks() -> None:
    """delta마다 before/after 팔로우 훅이 불리고 finally에서 endStreaming이 불린다."""
    observed = run_streaming_scenario("stream_scroll_follow_hooks")
    motion = observed["motion"]
    assert motion["before"] == 2
    assert motion["after"] == 2
    assert motion["end"] == 1


# ---------------------------------------------------------------------------
# 실패 처리: 완료로 위장하지 않는다
# ---------------------------------------------------------------------------
def test_a_stream_that_ends_without_done_is_not_reported_as_complete() -> None:
    """done 없는 종료는 완료가 아니다(부분 답변을 완료로 위장하지 않는다)."""
    observed = run_streaming_scenario("stream_ends_without_done")
    assert observed["ok"] is False
    assert observed["error"]["streamErrorRenders"] == 1
    assert observed["article"]["lifecycle"] != "completed"

def test_a_duplicate_done_frame_completes_only_once() -> None:
    """done 중복이 와도 완료 처리는 한 번만 일어난다."""
    observed = run_streaming_scenario("duplicate_done_frame")
    assert observed["ok"] is True
    assert observed["completions"] == 1
    assert observed["convIds"] == ["c"]
    assert observed["article"]["lifecycle"] == "completed"


def test_a_non_string_delta_is_refused() -> None:
    """delta가 문자열이 아니면 형식 오류로 거부된다."""
    observed = run_streaming_scenario("malformed_delta_frame")
    assert observed["thrown"] is not None
    assert observed["thrown"]["message"] == "stream-format-invalid"


def test_request_answer_clears_its_closure_state_and_refocuses_the_input() -> None:
    """요청이 끝나면 in-flight·controller·article이 정리되고 입력이 되돌아온다."""
    observed = run_streaming_scenario("request_answer_full_path")
    answer = observed["answer"]
    assert answer["inFlightAfter"] is False
    assert answer["controllerAfter"] is None
    assert answer["articleAfter"] is None
    assert answer["cancelReasonAfter"] is None
    assert answer["lastCompleted"] is True
    assert answer["inputFocused"] is True
    assert answer["composerUpdates"] >= 1
    assert answer["shellLabel"] == "answer-preparing"


# ---------------------------------------------------------------------------
# 구조·경계 계약 (문자열 유지, 이유 기록)
# ---------------------------------------------------------------------------
def test_index_loads_the_streaming_module_before_app() -> None:
    """모듈이 app.js보다 먼저 로드되어야 전달 함수가 정의된다(로드 순서 계약)."""
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert index.index("./chat-streaming-module.js") < index.index("./app.js")
    assert index.count("./chat-streaming-module.js") == 1


def test_app_keeps_one_line_forwarders_for_every_moved_function() -> None:
    """이동 본문은 모듈에만 살고 app.js는 전달 함수만 둔다(이중 소유 금지).

    실행 검사는 "어디에 살아 있는지"를 대신하지 못한다. 같은 본문이 양쪽에
    생기면 어느 쪽이 실제로 도는지 알 수 없으므로 구조 계약으로 유지한다.
    """
    for name in NAMES:
        prefix = "async function" if name in ASYNC_NAMES else "function"
        line = f"{prefix} {name}(...a) {{ return streamingModule().{name}(...a); }}"
        assert line in APP, name
        assert APP.count(f"function {name}(") == 1, name
    assert "function streamingModule() {" in APP
    assert "window.PadiemChatStreamingModule.create({" in APP


def test_moved_bodies_live_only_in_the_module() -> None:
    """이동한 본문의 소유는 모듈 하나다(구조 계약)."""
    markers = (
        'deps.activeRequestCancelReason = "user_cancel";',
        "deps.activeRequestController = controller;",
        "deps.activeRequestArticle = article;",
        "deps.inFlight = true;",
        "deps.lastCompletedAnswerRequest = {",
        "window.PadiemChatStreamingModule = {",
    )
    for marker in markers:
        assert marker in MODULE, marker
        assert marker not in APP, marker


def test_the_module_exposes_one_factory() -> None:
    """팩토리는 하나이고 5개 함수를 노출한다(공개 표면 계약)."""
    assert "window.PadiemChatStreamingModule = {" in MODULE
    assert "create(deps) {" in MODULE
    for name in NAMES:
        assert MODULE.count(f"function {name}(") == 1, name


def test_deps_surface_matches_the_mover_analysis() -> None:
    """deps getter 43개·setter 7개가 이동 분석과 정확히 같다(모듈이 만질 수 있는 표면)."""
    start = APP.index("window.PadiemChatStreamingModule.create({")
    block = APP[start:APP.index("});", start)]
    gets = set(re.findall(r"get (\w+)\(\)", block))
    sets = set(re.findall(r"set (\w+)\(value\)", block))
    assert len(gets) == 43
    assert sets == {
        "activeClawRunId",
        "activeProject",
        "activeRequestArticle",
        "activeRequestCancelReason",
        "activeRequestController",
        "inFlight",
        "lastCompletedAnswerRequest",
    }


def test_the_streaming_module_does_not_observe_dom_mutations() -> None:
    """MutationObserver 금지: 재렌더 루프가 입력 커서를 되돌리던 원인이었다."""
    assert "MutationObserver" not in MODULE
