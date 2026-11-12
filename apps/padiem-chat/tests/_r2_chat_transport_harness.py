"""#7186 R2 — chat-transport 구역 공용 실행 하네스.

`static/chat-transport.js`를 Node vm에서 실제로 올리고, 내보낸 함수를 호출해
"브라우저가 실제로 보내는 요청"과 "분류 결과"를 관찰한다. 소스 문자열을 찾지
않으므로 주석·함수 위치·표현식 모양이 바뀌어도 계약이 유지되면 통과한다.

관찰 항목:

- `request_surface`: 오케스트레이션 스트림·재개·취소, 완료(JSON) 답변,
  오케스트레이션 미준비 시 `/api/chat/stream` fallback이 실제로 나가는
  method·경로·Accept·본문.
- `stream_loss`: 스트림 손실로 분류되는 코드와, 거절·한도 오류가 아닌지.
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

function response({ status = 200, type = "application/json", body = null }) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get(name) {
        const key = String(name).toLowerCase();
        if (key === "content-type") return type;
        return null;
      },
    },
    json: async () => body,
    body: null,
  };
}

function loadTransport(routes) {
  const calls = [];
  const sandbox = {
    console,
    setTimeout,
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
      calls.push({
        method,
        url,
        accept: options.headers && (options.headers.Accept || options.headers.accept),
        contentType: options.headers && (options.headers["Content-Type"] || options.headers["content-type"]),
        cache: options.cache,
        body: typeof options.body === "string" ? options.body : null,
      });
      const route = routes[method + " " + url];
      if (!route) throw new Error("unexpected fetch: " + method + " " + url);
      return typeof route === "function" ? route() : route;
    },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(transportSource, sandbox, { filename: "chat-transport.js" });
  return { sandbox, calls, transport: sandbox.PadiemChatTransport };
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
  const { sandbox, transport } = loadTransport({});
  sandbox.window.PADIEM_PRODUCT_CAPS = undefined;
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

(async () => {
  const results = {
    request_surface: await requestSurface(),
    stream_loss: streamLoss(),
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
