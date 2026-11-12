"""#7186 R2 — chat-transport 구역 공용 실행 하네스.

`static/chat-transport.js`를 Node vm에서 실제로 올리고, 내보낸 함수를 호출해
"브라우저가 실제로 하는 일"을 관찰한다. 소스 문자열을 찾지 않으므로 주석·함수
위치·표현식 모양이 바뀌어도 계약이 유지되면 통과한다.

관찰 항목:

- `request_surface`: 오케스트레이션 스트림·재개·취소, 완료(JSON) 답변,
  오케스트레이션 미준비 시 `/api/chat/stream` fallback이 실제로 나가는
  method·경로·Accept·본문.
- `stream_loss`: 스트림 손실로 분류되는 코드와, 거절·한도 오류가 아닌지.
- `attachment_body`: 텍스트 첨부는 JSON으로, 파일 첨부는 4바이트 길이 + JSON
  헤더 + 원본 바이트 프레임으로 나가는지(메타데이터 상한 포함).
- `synthetic_done`: 서버 JSON 완료 응답이 어떤 `done` 프레임 필드로
  브라우저에 도착하는지.
- `sse_frames`: SSE 주석·CRLF·여러 data 줄과 NDJSON 레코드 정규화.
- `status_retry`: 상태 조회 재시도의 횟수·지연·쓰기/서버오류 비재시도.
- `exports`: transport가 창에 공개하는 함수 목록.

`fetch`만 가짜로 바꾼다. 응답은 시험이 정한 봉투를 그대로 돌려준다.
값·토큰은 만들지 않는다: 본문은 합성 메시지다.

사용법::

    from _r2_chat_transport_harness import observe
    observed = observe()
    assert ("POST", "/api/chat/stream") in observed["request_surface"]["paths"]
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"


_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const transportSource = fs.readFileSync(process.argv[2], "utf8");

function response({ status = 200, type = "application/json", body = null, headers = {} }) {
  const all = Object.assign({ "content-type": type }, headers);
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get(name) {
        const value = all[String(name).toLowerCase()];
        return value === undefined ? null : value;
      },
    },
    json: async () => body,
    body: null,
  };
}

function loadTransport(routes) {
  const calls = [];
  const delays = [];
  const sandbox = {
    console,
    setTimeout: (fn, ms) => { delays.push(ms); fn(); },
    clearTimeout,
    Response,
    Blob,
    TextEncoder,
    TextDecoder,
    crypto: require("crypto").webcrypto,
    Intl,
    Date,
    Math,
    JSON,
    Error,
    TypeError,
    Array,
    Object,
    String,
    Boolean,
    Number,
    Uint8Array,
    DataView,
    fetch: async (url, options = {}) => {
      const method = String(options.method || "GET").toUpperCase();
      const body = typeof options.body === "string" ? options.body : null;
      let bodyInfo = null;
      if (typeof options.body === "string") {
        bodyInfo = { kind: "text", text: options.body };
      } else if (options.body && typeof options.body.arrayBuffer === "function") {
        const bytes = new Uint8Array(await options.body.arrayBuffer());
        const headerBytes = bytes.length >= 4
          ? new DataView(bytes.buffer, bytes.byteOffset, 4).getUint32(0, false) : -1;
        let header = null;
        try {
          header = JSON.parse(new TextDecoder().decode(bytes.slice(4, 4 + headerBytes)));
        } catch (_) { /* 기록만 한다 */ }
        bodyInfo = {
          kind: "binary",
          totalBytes: bytes.length,
          headerBytes,
          header,
          payloadBytes: bytes.length - 4 - headerBytes,
          prefix: Array.from(bytes.slice(0, 4)),
          payload: Array.from(bytes.slice(4 + headerBytes)),
        };
      }
      calls.push({
        method,
        url,
        accept: options.headers && (options.headers.Accept || options.headers.accept),
        contentType: options.headers && (options.headers["Content-Type"] || options.headers["content-type"]),
        cache: options.cache,
        body,
        bodyInfo,
      });
      const route = routes[method + " " + url];
      if (!route) throw new Error("unexpected fetch: " + method + " " + url);
      return typeof route === "function" ? route() : route;
    },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(transportSource, sandbox, { filename: "chat-transport.js" });
  return { sandbox, calls, delays, transport: sandbox.PadiemChatTransport };
}

async function requestSurface() {
  let statusReady = true;
  const routes = {
    "GET /api/orchestration/status": () => response({
      type: "application/json",
      body: statusReady
        ? { orchestration_ready: true, authenticated: true }
        : { orchestration_ready: false, authenticated: true },
    }),
    "POST /api/orchestration": () => response({ type: "application/x-ndjson" }),
    "POST /api/orchestration/resume": () => response({ body: { ok: true } }),
    "POST /api/orchestration/cancel": () => response({ body: { ok: true } }),
    "POST /api/chat": () => response({ body: { answer: "답" } }),
    "POST /api/chat/stream": () => response({ type: "text/event-stream" }),
  };
  const { sandbox, calls, transport } = loadTransport(routes);
  const payload = { messages: [{ role: "user", content: "질문" }], tier: "plus" };
  const intent = { continuation_id: "cont_1" };

  await transport.requestOrchestrationStream(payload, null, true);
  await transport.resumeOrchestration(intent, null);
  await transport.cancelOrchestration(intent, null);
  const completed = await transport.requestCompleted(payload, null);

  statusReady = false;
  sandbox.window.PADIEM_CHAT_ORCHESTRATION_STREAM = false;
  transport.invalidateOrchestrationReady();
  await transport.requestStreaming(payload, null);

  return {
    requests: calls,
    paths: calls.map((call) => [call.method, call.url]),
    completed,
    defaultStreaming: loadTransport(routes).transport.orchestrationStreamingEnabled(),
    exported: Object.keys(transport).sort(),
  };
}

function streamLoss() {
  const { transport } = loadTransport({});
  const classify = (code) => transport.isStreamLoss({ error: { code } });
  return {
    invalid_engine_stream: classify("invalid_engine_stream"),
    invalid_engine_stream_event: classify("invalid_engine_stream_event"),
    orchestration_not_applicable: classify("orchestration_not_applicable"),
    engine_provider_rate_limited: classify("engine_provider_rate_limited"),
    no_error: transport.isStreamLoss(null),
    exported: Object.keys(transport).sort(),
  };
}

async function attachmentBody() {
  const routes = { "POST /api/chat": () => response({ body: { answer: "답" } }) };
  const { calls, transport } = loadTransport(routes);
  const file = new Blob([new Uint8Array([37, 80, 68, 70])], { type: "application/pdf" });
  const message = { messages: [{ role: "user", content: "질문" }] };

  await transport.requestCompleted(message, null);
  await transport.requestCompleted({
    ...message,
    attachments: [{ type: "document", name: "a.pdf", media_type: "application/pdf", file }],
  }, null);

  let oversized = null;
  try {
    await transport.requestCompleted({
      ...message,
      attachments: [{
        type: "document",
        name: "x".repeat(70000),
        media_type: "application/pdf",
        file,
      }],
    }, null);
  } catch (error) {
    oversized = error.message;
  }

  return {
    requests: calls.map((call) => ({ contentType: call.contentType, body: call.bodyInfo })),
    oversized,
  };
}

async function syntheticDone() {
  const routes = {
    "GET /api/orchestration/status": () => response({ body: { orchestration_ready: true, authenticated: true } }),
    "POST /api/orchestration": () => response({
      body: {
        answer: "답",
        conversation_id: "conv_1",
        answer_status: "grounded",
        evidence: [{ url: "https://example.test/a", title: "A" }],
        tool: { name: "web_search" },
        memory_proposals: [{ id: "mem_1" }],
      },
    }),
  };
  const { transport } = loadTransport(routes);
  const stream = await transport.requestOrchestrationStream({ messages: [] }, null, true);
  const text = await stream.text();
  const frames = text.split("\n\n").filter(Boolean).map((block) => {
    const frame = transport.parseSseFrame(block);
    return frame ? { event: frame.event, data: JSON.parse(frame.data) } : null;
  });
  return { contentType: stream.headers.get("content-type"), frames };
}

async function sseFrames() {
  const { transport } = loadTransport({});
  const crlf = transport.parseSseFrame(
    ": keepalive\r\nevent: delta\r\ndata: {\"delta\":\"가\"}\r\n\r\n",
  );
  const multiline = transport.parseSseFrame("data: {\"a\":1,\ndata: \"b\":2}");
  const body = [
    "{\"type\":\"delta\",\"text\":\"답\"}",
    "{\"type\":\"thought_summary\",\"summary\":\"요약\"}",
    "{\"thought_delta\":{\"delta\":\"생각\"}}",
    "{\"type\":\"error\",\"code\":\"stale_chat_client\"}",
  ].join("\n") + "\n";
  const stream = new Response(body, { headers: { "Content-Type": "application/x-ndjson" } });
  const ndjson = [];
  await transport.readSseEvents(stream, (frame) => {
    ndjson.push({ event: frame.event, data: JSON.parse(frame.data) });
    return false;
  });
  return {
    crlf: crlf ? { event: crlf.event, data: JSON.parse(crlf.data) } : null,
    multiline: multiline ? { event: multiline.event, data: JSON.parse(multiline.data) } : null,
    ndjson,
  };
}

async function statusRetry() {
  let plan = [];
  const routes = {};
  const route = () => {
    const step = plan.shift() || {};
    if (step.throw) throw new TypeError("Failed to fetch");
    return response({ status: step.status || 200, headers: step.headers || {}, body: {} });
  };
  routes["GET /api/connectors/status"] = route;
  routes["POST /api/connectors/status"] = route;
  const { calls, delays, transport } = loadTransport(routes);

  async function run(steps, options = {}) {
    plan = steps.slice();
    calls.length = 0;
    delays.length = 0;
    let retried = 0;
    try {
      const result = await transport.fetchStatusWithRetry(
        "/api/connectors/status", options, { onRetry: () => { retried += 1; } },
      );
      return { calls: calls.length, retried, status: result.status, delay: delays[0] ?? null };
    } catch (error) {
      return { calls: calls.length, retried, threw: error.name, delay: delays[0] ?? null };
    }
  }

  return {
    front_502_then_ok: await run([{ status: 502, headers: { "x-padiem-front": "1" } }, { status: 200 }]),
    front_503_then_ok: await run([{ status: 503, headers: { "x-padiem-front": "1" } }, { status: 200 }]),
    server_503: await run([{ status: 503 }]),
    write_is_not_retried: await run(
      [{ status: 502, headers: { "x-padiem-front": "1" } }, { status: 200 }],
      { method: "POST" },
    ),
    network_error_then_ok: await run([{ throw: true }, { status: 200 }]),
  };
}

(async () => {
  const results = {
    request_surface: await requestSurface(),
    stream_loss: streamLoss(),
    attachment_body: await attachmentBody(),
    synthetic_done: await syntheticDone(),
    sse_frames: await sseFrames(),
    status_retry: await statusRetry(),
  };
  process.stdout.write(JSON.stringify(results));
})().catch((error) => { console.error(error); process.exit(1); });
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for the transport harness")
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(_HARNESS, encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "chat-transport.js")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@lru_cache(maxsize=1)
def observe() -> dict:
    """모듈을 실제 실행해 얻은 한 번의 관찰(시험 파일 간 공유)."""

    return _run_harness()
