"""#7186 R2 — streaming 구역 공용 실행 하네스.

이 구역(답변 스트리밍·중단·재시도·모델 실패 처리)의 계약은 "브라우저가 실제로
하는 일"이다. 그래서 시험은 소스 문자열을 찾지 않고, 실제 세 파일을 한 Node
컨텍스트에 올려 실행한다.

- `chat-streaming-module.js` — 이 PR의 대상 모듈. `create(deps)`로 인스턴스를 만든다.
- `chat-transport.js` — 실제 전송 계층. `requestStreaming`/`requestCompleted`가
  어떤 method·경로·본문으로 나가는지는 이 파일이 정한다. 가짜 transport를 쓰면
  "보내는 요청"을 검사했다고 말할 수 없다.
- `thought-panel.js` — `thought`/`thought_reset` 프레임의 실제 처리자.

`fetch`만 가짜로 바꾼다. 경계는 거기 하나이고, 그 응답은 시험이 정한 SSE 본문을
그대로 흘려보낸다. DOM은 얇은 가짜다(실제 선택자·aria·dataset 변화를 관찰하기에
충분한 최소 구현).

사용법::

    from _r5_streaming_harness import run_streaming_scenario
    observed = run_streaming_scenario("stream_deltas_and_done")
    assert observed["request"] == {"method": "POST", "path": "/api/chat/stream", ...}
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")

#: 시나리오 이름 -> 시나리오 본문(JS). 각 본문은 `results` 객체를 채운다.
SCENARIOS = {
    # 답변 스트리밍: delta 두 조각 + done. 보내는 요청과 화면 요소를 함께 본다.
    "stream_deltas_and_done": r"""
  const article = makeArticle();
  const payload = { messages: [{ role: "user", content: "질문" }], tier: "plus", skill: "auto" };
  const context = { product: "chat", project: null };
  const ok = await api.requestStreamingAnswer(
    article, payload, [{ role: "user", content: "질문" }], "auto", context,
    new AbortController().signal, null,
  );
  results.ok = ok;
  results.request = lastRequest();
  results.article = {
    answerStarted: article.dataset.answerStarted,
    lifecycle: article.dataset.lifecycle,
    events: article.dataset.events || "",
    text: answerText(article),
    disclosureOpen: article._disclosure.open,
  };
""",
    # 생각(thought) 조각 -> thought_reset -> 새 생각 + 답변. #7484 계약.
    "thought_then_reset_then_answer": r"""
  const article = makeArticle();
  const payload = { messages: [{ role: "user", content: "질문" }], tier: "plus", skill: "auto" };
  const ok = await api.requestStreamingAnswer(
    article, payload, [{ role: "user", content: "질문" }], "auto",
    { product: "chat", project: null }, new AbortController().signal, null,
  );
  results.ok = ok;
  results.thought = {
    panelExists: Boolean(queryIn(article, ".orchestration-thought-summary")),
    panelOpen: queryIn(article, ".orchestration-thought-summary")
      ? queryIn(article, ".orchestration-thought-summary").open : null,
    label: (() => {
      const panel = queryIn(article, ".orchestration-thought-summary");
      const summary = panel && queryIn(panel, "summary");
      return summary ? summary.textContent : null;
    })(),
    text: (() => {
      const panel = queryIn(article, ".orchestration-thought-summary");
      if (!panel) return null;
      const all = [];
      (function collect(node) {
        if (node.tagName === "#TEXT") all.push(node.data);
        else if (typeof node.textContent === "string" && node.textContent) all.push(node.textContent);
        (node.children || []).forEach(collect);
      })(panel);
      return all.join(" ");
    })(),
  };
  results.article = { text: answerText(article), lifecycle: article.dataset.lifecycle };
""",
    # 스트림 오류 프레임: renderStreamError로 넘어가고 lifecycle이 failed가 된다.
    "stream_error_frame": r"""
  const article = makeArticle();
  const payload = { messages: [{ role: "user", content: "질문" }], tier: "plus", skill: "auto" };
  const ok = await api.requestStreamingAnswer(
    article, payload, [{ role: "user", content: "질문" }], "auto",
    { product: "chat", project: null }, new AbortController().signal, null,
  );
  results.ok = ok;
  results.error = {
    streamErrorRenders: live.streamErrorRenders,
    message: live.lastStreamErrorMsg,
    lifecycle: live.lastStreamErrorLifecycle,
    code: live.lastStreamErrorCode,
    clawGeneral: live.lastStreamErrorClaw,
    typingRemoved: article._typing.removed,
  };
""",
    # 첫 조각 전 오류: 문단이 없어도 일반 Chat 경로는 오류 카드로 끝난다.
    # (Claw 일반 요청만 문단이 없으면 위로 던진다 — 그 분기는 별도 계약이다.)
    "error_before_first_delta": r"""
  const article = makeArticle();
  const payload = { messages: [{ role: "user", content: "질문" }], tier: "plus", skill: "auto" };
  const ok = await api.requestStreamingAnswer(
    article, payload, [{ role: "user", content: "질문" }], "auto",
    { product: "chat", project: null }, new AbortController().signal, null,
  );
  results.ok = ok;
  results.error = {
    streamErrorRenders: live.streamErrorRenders,
    lifecycle: live.lastStreamErrorLifecycle,
    code: live.lastStreamErrorCode,
    errorRenders: live.errorRenders,
  };
  results.article = { text: answerText(article) };
""",
    # 중단: abort + 사유 + /api/pc/cancel POST 본문.
    "cancel_posts_run_id": r"""
  const article = makeArticle();
  live.inFlight = true;
  live.activeRequestArticle = article;
  live.activeRequestController = { abort() { live.aborted += 1; } };
  live.activeClawRunId = "run_cancel_9";
  api.cancelActiveStream();
  await new Promise((r) => setImmediate(r));
  results.cancel = {
    reason: live.activeRequestCancelReason,
    aborted: live.aborted,
    request: lastRequest(),
    runsInvalidated: live.runsInvalidated,
    notes: live.notes.slice(),
  };
""",
    # 중단: claw run id가 없으면 서버 취소를 보내지 않고 사용자 안내만 남긴다.
    "cancel_without_run_id": r"""
  const article = makeArticle();
  live.inFlight = true;
  live.activeRequestArticle = article;
  live.activeRequestController = { abort() { live.aborted += 1; } };
  live.activeClawRunId = null;
  api.cancelActiveStream();
  await new Promise((r) => setImmediate(r));
  results.cancel = {
    reason: live.activeRequestCancelReason,
    aborted: live.aborted,
    request: lastRequest(),
    notes: live.notes.slice(),
  };
""",
    # 중단 대상이 없으면 아무 것도 하지 않는다.
    "cancel_without_active_request": r"""
  live.inFlight = false;
  live.activeRequestController = null;
  live.activeRequestArticle = null;
  api.cancelActiveStream();
  await new Promise((r) => setImmediate(r));
  results.cancel = {
    reason: live.activeRequestCancelReason,
    aborted: live.aborted,
    request: lastRequest(),
  };
""",
    # requestAnswer 전체 경로: 요청 본문·tier·pc_run_id·정리(finally).
    "request_answer_full_path": r"""
  const ok = await api.requestAnswer(
    [{ role: "user", content: "질문" }], "auto", null,
    { product: "chat", project: null }, false, false,
  );
  results.ok = ok;
  results.request = lastRequest();
  results.answer = {
    inFlightAfter: live.inFlight,
    controllerAfter: live.activeRequestController,
    articleAfter: live.activeRequestArticle,
    cancelReasonAfter: live.activeRequestCancelReason,
    lastCompleted: Boolean(live.lastCompletedAnswerRequest),
    inputFocused: live.input.focused > 0,
    composerUpdates: live.composerUpdates,
    shellLabel: live.lastShell && live.lastShell.dataset.shellLabel,
  };
""",
    # 이미 진행 중이면 두 번째 요청은 거부되고 요청이 나가지 않는다.
    "request_answer_refused_while_in_flight": r"""
  live.inFlight = true;
  const ok = await api.requestAnswer(
    [{ role: "user", content: "질문" }], "auto", null,
    { product: "chat", project: null }, false, false,
  );
  results.ok = ok;
  results.request = lastRequest();
  live.inFlight = false;
""",
    # Claw 레인: 같은 제출 경로가 product=claw 본문으로 나간다.
    "request_answer_claw_lane": r"""
  const ok = await api.requestAnswer(
    [{ role: "user", content: "질문" }], "auto", null,
    { product: "claw", project: null }, true, false,
  );
  results.ok = ok;
  results.request = lastRequest();
  results.answer = {
    inFlightAfter: live.inFlight,
    inputFocused: live.input.focused > 0,
    products: live.products.slice(),
  };
""",
    # 완료형(첨부) 경로: method·경로·본문이 /api/chat POST로 나간다.
    "done_with_grounded_evidence": r"""
  const article = makeArticle();
  const payload = { messages: [{ role: "user", content: "질문" }], tier: "plus", skill: "auto" };
  const ok = await api.requestStreamingAnswer(
    article, payload, [{ role: "user", content: "질문" }], "auto",
    { product: "chat", project: null }, new AbortController().signal, null,
  );
  results.ok = ok;
  results.evidence = {
    rendered: live.searchSources.slice(),
    taskEvidence: article.dataset.taskEvidence === undefined ? null : article.dataset.taskEvidence,
  };
  results.article = { events: article.dataset.events || "" };
""",
    "completed_answer_with_attachment": r"""
  const article = makeArticle();
  const payload = {
    messages: [{ role: "user", content: "질문" }], tier: "plus", skill: "auto",
    attachments: [{ type: "file", file_id: "file_1" }],
  };
  const ok = await api.requestCompletedAnswer(
    article, payload, [{ role: "user", content: "질문" }],
    [{ type: "file", file_id: "file_1" }],
    { product: "chat", project: null }, new AbortController().signal,
  );
  results.ok = ok;
  results.request = lastRequest();
  results.article = {
    renderedAnswer: article.dataset.renderedAnswer,
    clockStarted: article.dataset.clockStarted,
  };
""",
    # 스트림이 done 없이 끝나면 완료로 위장하지 않는다: 부분 답변이 있으면
    # 오류 카드로, 없으면 예외로 끝난다. 여기서는 부분 답변이 있는 경우다.
    "stream_ends_without_done": r"""
  const article = makeArticle();
  const payload = { messages: [{ role: "user", content: "질문" }], tier: "plus", skill: "auto" };
  const ok = await api.requestStreamingAnswer(
    article, payload, [{ role: "user", content: "질문" }], "auto",
    { product: "chat", project: null }, new AbortController().signal, null,
  );
  results.ok = ok;
  results.error = { streamErrorRenders: live.streamErrorRenders };
  results.article = {
    text: answerText(article),
    lifecycle: article.dataset.lifecycle === undefined ? null : article.dataset.lifecycle,
  };
""",
    # done 중복: 첫 done에서 리더가 멈추므로 두 번째 done은 처리되지 않는다.
    # 완료 처리가 한 번만 일어나는 것이 계약이다.
    "duplicate_done_frame": r"""
  const article = makeArticle();
  const payload = { messages: [{ role: "user", content: "질문" }], tier: "plus", skill: "auto" };
  const ok = await api.requestStreamingAnswer(
    article, payload, [{ role: "user", content: "질문" }], "auto",
    { product: "chat", project: null }, new AbortController().signal, null,
  );
  results.ok = ok;
  results.completions = live.committed.length;
  results.convIds = live.convIds.slice();
  results.article = { lifecycle: article.dataset.lifecycle, text: answerText(article) };
""",
    # delta가 문자열이 아니면 형식 오류로 거부된다.
    "malformed_delta_frame": r"""
  const article = makeArticle();
  const payload = { messages: [{ role: "user", content: "질문" }], tier: "plus", skill: "auto" };
  let thrown = null;
  try {
    await api.requestStreamingAnswer(
      article, payload, [{ role: "user", content: "질문" }], "auto",
      { product: "chat", project: null }, new AbortController().signal, null,
    );
  } catch (err) {
    thrown = { name: err.name, message: err.message };
  }
  results.thrown = thrown;
""",
    # 진행 프레임: 진행 표시가 열리고 작업 단계가 기록된다.
    "progress_and_orchestration_events": r"""
  const article = makeArticle();
  const payload = { messages: [{ role: "user", content: "질문" }], tier: "plus", skill: "auto" };
  const ok = await api.requestStreamingAnswer(
    article, payload, [{ role: "user", content: "질문" }], "auto",
    { product: "chat", project: null }, new AbortController().signal, null,
  );
  results.ok = ok;
  results.article = {
    events: article.dataset.events || "",
    disclosureOpen: article._disclosure.open,
    text: answerText(article),
  };
""",
    # PC 진행 프레임: pc_work 단계와 진행 표시.
    "pc_progress_frames": r"""
  const article = makeArticle();
  const payload = { messages: [{ role: "user", content: "질문" }], tier: "plus", skill: "auto" };
  const ok = await api.requestStreamingAnswer(
    article, payload, [{ role: "user", content: "질문" }], "auto",
    { product: "chat", project: null }, new AbortController().signal, null,
  );
  results.ok = ok;
  results.article = {
    events: article.dataset.events || "",
    pcProgress: live.pcProgress.slice(),
    heartbeats: live.heartbeats,
  };
""",
    # 스크롤 팔로우 훅: delta마다 before/after, finally에서 endStreaming.
    "stream_scroll_follow_hooks": r"""
  const article = makeArticle();
  const payload = { messages: [{ role: "user", content: "질문" }], tier: "plus", skill: "auto" };
  await api.requestStreamingAnswer(
    article, payload, [{ role: "user", content: "질문" }], "auto",
    { product: "chat", project: null }, new AbortController().signal, null,
  );
  results.motion = {
    before: live.motionBefore,
    after: live.motionAfter,
    end: live.motionEnd,
  };
""",
    # #7186 R2 2차: file-lane 칩의 업로드 배선. 소스 문자열 대신 실제 모듈 실행으로
    # 관찰한다 — file-lane 칩마다 upload가 같은 abort signal로 1회씩 불리고, 반환
    # 참조가 칩에 합쳐져 실제 요청 페이로드의 {type:"file", file_id}로 이어지며,
    # 업로드 진행 문구가 상태 줄로 나가고, 취소가 같은 signal로 전달되는지.
    "file_lane_upload_wiring": r"""
  // 실제 attachmentPayload 빌더(대화 모듈)를 별도 컨텍스트에서 실행해 deps에
  // 연결한다. 칩 -> 페이로드 매핑도 가짜가 아니라 실행으로 관찰한다.
  const attWindow = {};
  const attCtx = { window: attWindow, console, JSON, Object, Array, Math, Date,
    Error, TypeError, Number, String, Boolean, RegExp, Promise, Map, Set, WeakMap };
  vm.createContext(attCtx);
  vm.runInContext(
    fs.readFileSync(path.join(STATIC, "chat-conversation-module.js"), "utf8"),
    attCtx, { filename: "chat-conversation-module.js" });
  deps.attachmentPayload =
    attWindow.PadiemChatConversationModule.create({}).attachmentPayload;

  const uploads = [];
  let hangUpload = false;
  let signalUploadStarted;
  const uploadStarted = new Promise((resolve) => { signalUploadStarted = resolve; });
  window.PadiemFileLane = {
    upload(file, signal, onState) {
      uploads.push({ fileName: file && file.name, signal, onState });
      if (hangUpload) {
        signalUploadStarted();
        return new Promise((_resolve, reject) => {
          signal.addEventListener("abort", () => {
            const err = new Error("upload aborted"); err.name = "AbortError"; reject(err);
          });
        });
      }
      onState({ phase: "uploading", percent: 40 });
      onState({ phase: "finalizing", percent: 100 });
      return Promise.resolve({ fileId: "file_up_" + (file && file.name ? file.name : "x") });
    },
  };

  // 1단계: file-lane 칩 두 개 + 이미 fileId가 있는 칩 하나.
  const notesBefore = live.notes.length;
  const ok = await api.requestAnswer(
    [{ role: "user", content: "질문" }], "auto",
    [
      { type: "file", name: "a.pdf", fileLane: true, file: { name: "a.pdf" } },
      { type: "file", name: "b.pdf", fileLane: true, file: { name: "b.pdf" } },
      { type: "file", name: "done.pdf", fileId: "file_pre" },
    ],
    { product: "chat", project: null }, false, false,
  );
  const requestA = lastRequest();
  results.ok = ok;
  results.upload = {
    calls: uploads.length,
    files: uploads.map((u) => u.fileName),
    sameSignal: uploads.length > 1 && uploads[0].signal === uploads[1].signal,
    preUploadedSkipped: uploads.every((u) => u.fileName !== "done.pdf"),
    notes: live.notes.slice(notesBefore),
  };
  results.payloadAttachments = requestA && requestA.body && requestA.body.attachments;

  // 2단계: 업로드가 걸려 있는 동안 취소 — 같은 signal로 중단되는지.
  hangUpload = true;
  const cancelledBefore = live.cancelledRenders;
  const pending = api.requestAnswer(
    [{ role: "user", content: "질문" }], "auto",
    [{ type: "file", name: "c.pdf", fileLane: true, file: { name: "c.pdf" } }],
    { product: "chat", project: null }, false, false,
  );
  await uploadStarted;
  const hungSignal = uploads[uploads.length - 1].signal;
  const controllerDuring = live.activeRequestController;
  api.cancelActiveStream();
  const ok2 = await pending;
  results.abort = {
    sameSignalAsController: Boolean(controllerDuring) && hungSignal === controllerDuring.signal,
    signalAborted: hungSignal.aborted === true,
    returnedFalse: ok2 === false,
    cancelledRendered: live.cancelledRenders > cancelledBefore,
  };
""",
}

#: 시나리오별 SSE 프레임. 시험이 "무엇을 넣었을 때"를 정한다.
FRAMES = {
    "stream_deltas_and_done": [
        {"event": "meta", "data": "{}"},
        {"event": "delta", "data": json.dumps({"delta": "안녕"}, ensure_ascii=False)},
        {"event": "delta", "data": json.dumps({"delta": "하세요"}, ensure_ascii=False)},
        {"event": "done", "data": json.dumps({"done": True, "conversation_id": "conv-1"})},
    ],
    "thought_then_reset_then_answer": [
        {"event": "thought", "data": json.dumps({"text": "첫 모델 생각"}, ensure_ascii=False)},
        {"event": "thought_reset", "data": "{}"},
        {"event": "thought", "data": json.dumps({"text": "두번째 모델 생각"}, ensure_ascii=False)},
        {"event": "delta", "data": json.dumps({"delta": "답변"}, ensure_ascii=False)},
        {"event": "done", "data": json.dumps({"done": True, "conversation_id": "conv-2"})},
    ],
    "stream_error_frame": [
        {"event": "meta", "data": "{}"},
        {"event": "delta", "data": json.dumps({"delta": "부분"}, ensure_ascii=False)},
        {"event": "error", "data": json.dumps({"error": {"code": "upstream_unavailable"}})},
    ],
    "error_before_first_delta": [
        {"event": "meta", "data": "{}"},
        {"event": "error", "data": json.dumps({"error": {"code": "upstream_unavailable"}})},
    ],
    "stream_ends_without_done": [
        {"event": "delta", "data": json.dumps({"delta": "잘린답변"}, ensure_ascii=False)},
    ],
    "duplicate_done_frame": [
        {"event": "delta", "data": json.dumps({"delta": "답"}, ensure_ascii=False)},
        {"event": "done", "data": json.dumps({"done": True, "conversation_id": "c"})},
        {"event": "done", "data": json.dumps({"done": True, "conversation_id": "c"})},
    ],
    "malformed_delta_frame": [
        {"event": "delta", "data": json.dumps({"delta": 42})},
    ],
    "progress_and_orchestration_events": [
        {"event": "meta", "data": "{}"},
        {"event": "progress", "data": json.dumps({"stage": "planning"})},
        {"event": "orchestration_event",
         "data": json.dumps({"kind": "tool_started", "metadata": {"tool_id": "web_search"}})},
        {"event": "delta", "data": json.dumps({"delta": "답"}, ensure_ascii=False)},
        {"event": "done", "data": json.dumps({"done": True, "conversation_id": "c3"})},
    ],
    "pc_progress_frames": [
        {"event": "pc_progress", "data": json.dumps({"run_id": "run_pc_123", "step": 1})},
        {"event": "heartbeat", "data": json.dumps({"run_id": "run_pc_123"})},
        {"event": "delta", "data": json.dumps({"delta": "답"}, ensure_ascii=False)},
        {"event": "done", "data": json.dumps({"done": True, "conversation_id": "c4"})},
    ],
    "stream_scroll_follow_hooks": [
        {"event": "delta", "data": json.dumps({"delta": "가"}, ensure_ascii=False)},
        {"event": "delta", "data": json.dumps({"delta": "나"}, ensure_ascii=False)},
        {"event": "done", "data": json.dumps({"done": True, "conversation_id": "c5"})},
    ],
    "request_answer_full_path": [
        {"event": "delta", "data": json.dumps({"delta": "최종"}, ensure_ascii=False)},
        {"event": "done", "data": json.dumps({"done": True, "conversation_id": "c6"})},
    ],
    # file-lane 업로드 배선: 완료형 경로(/api/chat JSON)라 SSE 프레임은 없다.
    "file_lane_upload_wiring": [],
    "request_answer_claw_lane": [
        {"event": "delta", "data": json.dumps({"delta": "클로"}, ensure_ascii=False)},
        {"event": "done", "data": json.dumps({"done": True, "conversation_id": "c7"})},
    ],
    "done_with_grounded_evidence": [
        {"event": "delta", "data": json.dumps({"delta": "근거답변"}, ensure_ascii=False)},
        {"event": "done", "data": json.dumps({
            "done": True, "conversation_id": "c8",
            "evidence": [{"url": "https://example.test/a", "title": "A"}],
            "tool": {"id": "web_search"},
        }, ensure_ascii=False)},
    ],
}

#: 시나리오별 응답 content-type. 완료형 경로는 JSON이다.
CONTENT_TYPES = {
    "completed_answer_with_attachment": "application/json",
}


_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const STATIC = process.argv[2];
const SCENARIO = process.argv[3];
const FRAMES = JSON.parse(process.argv[4]);
const CONTENT_TYPE = process.argv[5];

function makeElement(tag) {
  const attrs = {};
  const classes = new Set();
  const node = {
    tagName: String(tag || "div").toUpperCase(),
    textContent: "",
    hidden: false,
    disabled: false,
    open: false,
    isConnected: true,
    dataset: {},
    attrs,
    children: [],
    parentElement: null,
    focused: 0,
    removed: false,
    get className() { return Array.from(classes).join(" "); },
    set className(value) {
      classes.clear();
      String(value || "").split(/\s+/).filter(Boolean).forEach((c) => classes.add(c));
    },
    classList: {
      add(...xs) { xs.forEach((x) => classes.add(x)); },
      remove(...xs) { xs.forEach((x) => classes.delete(x)); },
      contains(x) { return classes.has(x); },
    },
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k] === undefined ? null : attrs[k]; },
    removeAttribute(k) { delete attrs[k]; },
    append(...xs) { xs.forEach((x) => this.appendChild(x)); },
    appendChild(x) { x.parentElement = this; this.children.push(x); return x; },
    insertBefore(x, ref) {
      x.parentElement = this;
      const i = this.children.indexOf(ref);
      if (i < 0) this.children.push(x); else this.children.splice(i, 0, x);
      return x;
    },
    replaceChildren(...xs) { this.children = []; xs.forEach((x) => this.appendChild(x)); },
    remove() { this.removed = true; if (this.parentElement) {
      const i = this.parentElement.children.indexOf(this);
      if (i >= 0) this.parentElement.children.splice(i, 1);
    } },
    focus() { this.focused += 1; },
    scrollIntoView() {},
    querySelector(sel) { return queryIn(this, sel); },
    querySelectorAll(sel) { return queryAllIn(this, sel); },
  };
  return node;
}

function walk(node, out) {
  for (const child of node.children || []) { out.push(child); walk(child, out); }
  return out;
}

function matches(node, sel) {
  if (sel.startsWith(".")) return node.classList.contains(sel.slice(1));
  if (sel.startsWith("#")) return node.attrs.id === sel.slice(1);
  if (sel.startsWith("[") && sel.endsWith("]")) {
    const body = sel.slice(1, -1);
    const eq = body.indexOf("=");
    if (eq < 0) return node.attrs[body] !== undefined || node.dataset[body] !== undefined;
    const key = body.slice(0, eq);
    const value = body.slice(eq + 1).replace(/^["']|["']$/g, "");
    return node.attrs[key] === value;
  }
  return node.tagName === sel.toUpperCase();
}

function queryIn(root, sel) {
  const all = walk(root, []);
  for (const node of all) if (matches(node, sel)) return node;
  return null;
}

function queryAllIn(root, sel) {
  return walk(root, []).filter((node) => matches(node, sel));
}

function makeArticle() {
  const article = makeElement("article");
  const body = makeElement("div"); body.className = "assistant-body";
  const content = makeElement("div"); content.className = "assistant-content";
  const marker = makeElement("small"); marker.setAttribute("data-runtime-label", "");
  const disclosure = makeElement("details"); disclosure.className = "capability-kit-disclosure";
  const typing = makeElement("span"); typing.className = "typing";
  content.appendChild(typing);
  body.appendChild(marker);
  body.appendChild(content);
  article.appendChild(body);
  article.appendChild(disclosure);
  // Named handles the scenarios read directly. They are the same nodes the
  // module finds by selector, so an observation cannot drift from the DOM.
  article._disclosure = disclosure;
  article._typing = typing;
  article._content = content;
  article._body = body;
  return article;
}

function answerText(article) {
  const content = queryIn(article, ".assistant-content");
  const paragraph = content && content.children.find((c) => c.tagName === "P");
  if (!paragraph) return null;
  const text = paragraph.children.find((c) => c.tagName === "#TEXT");
  return text ? text.data : paragraph.textContent;
}

// --- live deps state -------------------------------------------------------
const live = {
  MESSAGE_LIFECYCLE: {
    STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed",
    CANCELLED: "cancelled", TIMED_OUT: "timed_out", WAITING_APPROVAL: "waiting_for_approval",
  },
  activeClawRunId: null,
  activeProject: null,
  activeRequestArticle: null,
  activeRequestCancelReason: null,
  activeRequestController: null,
  inFlight: false,
  lastCompletedAnswerRequest: null,
  conversationEpoch: 1,
  conversationProduct: "chat",
  authState: { authenticated: true },
  projectsReady: true,
  projectFileStatus: makeElement("div"),
  input: makeElement("textarea"),
  notes: [],
  products: [],
  committed: [],
  convIds: [],
  aborted: 0,
  runsInvalidated: 0,
  composerUpdates: 0,
  streamErrorRenders: 0,
  lastStreamErrorMsg: null,
  lastStreamErrorLifecycle: null,
  lastStreamErrorCode: null,
  lastStreamErrorClaw: null,
  errorRenders: 0,
  cancelledRenders: 0,
  lastShell: null,
  pcProgress: [],
  heartbeats: 0,
  searchSources: [],
  motionBefore: 0,
  motionAfter: 0,
  motionEnd: 0,
  uiT: (k, vars) => (vars && vars.count !== undefined ? `${k}:${vars.count}` : k),
  setNote: (m, k) => { live.notes.push([m, k]); },
  selectedProductTier: () => "plus",
  addAssistantShell: (label, state) => {
    const a = makeArticle();
    a.dataset.shellLabel = label;
    a.dataset.shellState = state;
    live.lastShell = a;
    return a;
  },
  renderTyping: () => {},
  renderAnswer: (article, data) => { article.dataset.renderedAnswer = data.answer; },
  renderProjectState: () => {},
  renderWebGroundingNotice: () => {},
  renderCancelled: () => { live.cancelledRenders += 1; },
  renderError: () => { live.errorRenders += 1; },
  renderStreamError: (article, msg, _o, _s, _c, clawGeneral, lifecycle, _cf, code) => {
    live.streamErrorRenders += 1;
    live.lastStreamErrorMsg = msg;
    live.lastStreamErrorLifecycle = lifecycle;
    live.lastStreamErrorClaw = clawGeneral;
    live.lastStreamErrorCode = code === undefined ? null : code;
  },
  revealErrorState: () => {},
  lifecycleForError: () => "failed",
  clawGeneralFailure: (code) => ({ message: `claw:${code}`, hint: "hint" }),
  handleCustomRequestFailure: () => {},
  openAuthDialog: () => {},
  projectById: () => null,
  loadRecentConversations: () => {},
  loadProjects: () => {},
  invalidateClawRunsRead: () => { live.runsInvalidated += 1; },
  updateComposer: () => { live.composerUpdates += 1; },
  attachmentPayload: (items) => (Array.isArray(items) && items.length ? items : null),
  recoverStoredPcResult: async () => false,
  waitForAcceptedPcRun: async () => {},
  conversationState: {
    setProduct(p) { live.products.push(p); },
    commitAssistant(msgs, ans) { live.committed.push([msgs.length, ans]); },
    setConversationId(id) { live.convIds.push(id); },
  },
};

// --- fetch boundary --------------------------------------------------------
const requests = [];
function lastRequest() {
  const r = requests[requests.length - 1];
  if (!r) return null;
  let body = r.body;
  if (typeof body === "string") { try { body = JSON.parse(body); } catch (_) {} }
  return { method: r.method, path: r.path, body };
}

function sseBody(frames) {
  const text = frames.map((f) => `event: ${f.event}\ndata: ${f.data}\n\n`).join("");
  const encoder = new TextEncoder();
  const bytes = encoder.encode(text);
  let sent = false;
  return {
    getReader() {
      return {
        async read() {
          if (sent) return { done: true, value: undefined };
          sent = true;
          return { done: false, value: bytes };
        },
        releaseLock() {},
        cancel() {},
      };
    },
  };
}

const fetchCalls = [];
async function fakeFetch(url, opts) {
  const method = (opts && opts.method) || "GET";
  let body = opts && opts.body;
  if (body && typeof body !== "string" && typeof body.text === "function") body = await body.text();
  const record = { path: String(url), method, body };
  fetchCalls.push(record);
  requests.push(record);
  if (String(url) === "/api/pc/cancel") {
    return { ok: true, status: 200, json: async () => ({ ok: true }) };
  }
  if (String(url) === "/api/chat") {
    return {
      ok: true, status: 200,
      headers: { get: () => "application/json" },
      json: async () => ({ answer: "완료답변", conversation_id: "conv-done", project_id: null }),
    };
  }
  return {
    ok: true, status: 200,
    headers: { get: () => CONTENT_TYPE },
    body: sseBody(FRAMES),
    json: async () => ({}),
  };
}

// --- context ---------------------------------------------------------------
const document = {
  documentElement: { lang: "ko" },
  createElement: (t) => makeElement(t),
  createTextNode: (v) => {
    const node = makeElement("#text");
    node.data = String(v || "");
    node.appendData = function (d) { this.data += d; };
    return node;
  },
};

const window = {
  PADIEM_CHAT_ORCHESTRATION_STREAM: false,
};
window.window = window;

const ctx = {
  document,
  window,
  console,
  fetch: fakeFetch,
  TextEncoder,
  TextDecoder,
  AbortController,
  setTimeout,
  clearTimeout,
  setImmediate,
  crypto: require("crypto").webcrypto,
  Uint8Array,
  Promise, Map, Set, WeakMap, Array, JSON, Date, Error, TypeError, Number, String,
  Boolean, Object, RegExp, Math,
};
vm.createContext(ctx);

// Real transport + real thought panel + the module under test.
for (const file of ["chat-transport.js", "thought-panel.js", "chat-streaming-module.js"]) {
  const source = fs.readFileSync(path.join(STATIC, file), "utf8");
  vm.runInContext(source, ctx, { filename: file });
}

// Lifecycle stub: records task events and the terminal state on the article.
// The module calls it as a bare global (`PadiemChatLifecycle.set(...)`) and also
// through `window.PadiemChatLifecycle?.` — both must resolve to this one object.
const lifecycleStub = {
  startTurnClock(article) { article.dataset.clockStarted = "true"; },
  releasePreparingRuntimeLabel(article) { article.dataset.releasedPreparing = "true"; },
  recordTaskEvent(article, evt) {
    article.dataset.events = (article.dataset.events ? article.dataset.events + "," : "") + evt;
  },
  renderTaskStatus(article) { article.dataset.taskStatus = "true"; },
  appendStreamDelta(node, delta) { node.appendData(delta); return true; },
  applyRuntimeLabel() {},
  recordProgressFrame() { return true; },
  recordPcProgress(article, value) { live.pcProgress.push(value); return true; },
  recordPcHeartbeat() { live.heartbeats += 1; return true; },
  set(article, state) { article.dataset.lifecycle = state; },
};
ctx.PadiemChatLifecycle = lifecycleStub;
ctx.window.PadiemChatLifecycle = lifecycleStub;
ctx.window.__padiemConversationMotion = {
  beforeStreamingDelta() { live.motionBefore += 1; return true; },
  afterStreamingDelta() { live.motionAfter += 1; },
  endStreaming() { live.motionEnd += 1; },
};
ctx.window.PadiemTierSelection = { ready: async () => {} };
ctx.window.PadiemCustomSelection = { get: () => null };
ctx.window.PadiemPcBrowserSurface = { runIdForProgress: () => "run_pc_123" };
ctx.window.PadiemChatPcScopeNotice = { render: () => {} };
ctx.window.PadiemChatMemoryReview = { render: () => {}, sync: () => {} };
ctx.window.PadiemClawAnswerSources = { render: () => {} };
ctx.window.PadiemSearchSources = {
  render(article, evidence) { live.searchSources.push(...evidence); },
};
ctx.window.PadiemChatOrchestrationUI = { render: () => {} };

// The thought panel is real and is called by the module through
// `window.PadiemChatThoughtPanel`. Its own state lives in a WeakMap inside it, so
// the observation reads the DOM node it painted instead of wrapping the API.
const thoughtPanel = ctx.window.PadiemChatThoughtPanel;

const deps = {};
for (const key of Object.keys(live)) {
  Object.defineProperty(deps, key, {
    get() { return live[key]; },
    set(value) { live[key] = value; },
  });
}
Object.defineProperty(deps, "chatTransport", { get() { return ctx.window.PadiemChatTransport; } });

// app.js passes its own one-line forwarders for the moved functions, so the
// module reaches them through deps. They must resolve to this same instance.
const INTERNAL = [
  "requestCompletedAnswer", "applyStreamDone", "requestStreamingAnswer",
  "cancelActiveStream", "requestAnswer",
];
let api;
for (const name of INTERNAL) {
  Object.defineProperty(deps, name, { get() { return api[name]; } });
}
api = ctx.window.PadiemChatStreamingModule.create(r5StrictDeps(deps, "streaming.deps"));

const results = {};
const makeArticleRef = makeArticle;
const answerTextRef = answerText;
const lastRequestRef = lastRequest;
const queryRef = queryIn;
Object.assign(ctx, {
  makeArticle: makeArticleRef, answerText: answerTextRef,
  lastRequest: lastRequestRef, queryIn: queryRef,
});

(async () => {
  const makeArticle = makeArticleRef;
  const answerText = answerTextRef;
  const lastRequest = lastRequestRef;
  const queryIn = queryRef;
  __SCENARIO__
  process.stdout.write(JSON.stringify(results));
})().catch((err) => {
  process.stderr.write(String(err && err.stack || err));
  process.exit(1);
});
"""


def run_streaming_scenario(name: str) -> dict:
    """한 시나리오를 실제 모듈로 실행하고 관찰값을 돌려준다."""
    if name not in SCENARIOS:
        raise KeyError(name)
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for the streaming harness")
    body = SCENARIOS[name]
    frames = FRAMES.get(name, [])
    content_type = CONTENT_TYPES.get(name, "text/event-stream")
    script = STRICT + "\n" + _HARNESS.replace("__SCENARIO__", body)
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(script, encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(harness), str(STATIC), name,
             json.dumps(frames, ensure_ascii=False), content_type],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)
