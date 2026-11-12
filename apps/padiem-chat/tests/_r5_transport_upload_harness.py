"""R5 전송 구역 — 조각 업로드(tus)·파일 레인·첨부 역량을 실제 모듈 실행으로 관찰 (#7186 R2).

세 모듈을 **한 Node 컨텍스트**에서 실행하고 `fetch`만 가짜로 바꾼다:

- `tus-upload.js` — OPTIONS(한도) → POST(생성) → PATCH(조각) → HEAD(재개) → GET(결과),
  재시도 지연 [0,1,3,5,10s], 1차 한국어 안내.
- `file-lane.js` — `shouldUse` 임계값·capabilities 조회·티켓 업로드·tus 라우팅.
- `attachment-capabilities.js` — `setMaxPerMessage` 저장·클램프.

모듈 사이 참조(`window.PadiemAttachmentCapabilities`·`window.PadiemTusUpload`)는
`_r5_strict_deps.js` 프록시로 싼다: 정의되지 않은 멤버를 읽으면 즉시 실패한다.
값·토큰은 만들지 않는다. 파일은 `slice`만 가진 합성 객체이고, 요청 본문은
바이트 수만 기록한다.
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
TUS = STATIC / "tus-upload.js"
LANE = STATIC / "file-lane.js"
CAPS = STATIC / "attachment-capabilities.js"
STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")

_NODE = r"""
const fs = require("fs");
const vm = require("vm");

// ── 가짜 fetch: 경로·메서드·헤더·본문 길이만 기록하고 정해진 응답을 돌려준다 ──
const calls = [];
let routes = [];
const file = {name: "note.txt", size: 0, lastModified: 0};
function response(status, headers, body) {
  const map = Object.assign({}, headers || {});
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: {get: (k) => (Object.prototype.hasOwnProperty.call(map, k) ? map[k] : null)},
    json: () => Promise.resolve(body === undefined ? null : body),
  };
}
function record(url, init) {
  const headers = {};
  Object.keys((init && init.headers) || {}).forEach((k) => { headers[k] = String(init.headers[k]); });
  const body = init && init.body;
  const entry = {
    url: String(url),
    method: String((init && init.method) || "GET").toUpperCase(),
    headers,
    bodyBytes: body && typeof body === "object" && Number.isFinite(body.size) ? body.size : null,
    sliceStart: body && typeof body === "object" && Number.isFinite(body.start) ? body.start : null,
  };
  calls.push(entry);
  return entry;
}
function fakeFetch(url, init) {
  record(url, init);
  const method = String((init && init.method) || "GET").toUpperCase();
  for (const route of routes) {
    if (route.method === method && route.match(String(url))) return Promise.resolve(route.reply());
  }
  return Promise.reject(new Error("no test route for " + method + " " + url));
}

// ── 컨텍스트 ──────────────────────────────────────────────────────────────
const win = {
  location: {href: "https://padiem.test/chat"},
  TextEncoder,
  btoa: (s) => Buffer.from(s, "binary").toString("base64"),
  atob: (s) => Buffer.from(s, "base64").toString("binary"),
  URL, Promise, Object, Number, String, Boolean, Array, Set, Math, JSON, Error, Date,
  setTimeout: (fn) => { fn(); return 0; },
  clearTimeout: () => {},
  CustomEvent: function CustomEvent(type, init) { this.type = type; this.detail = init && init.detail; },
  listeners: {},
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
  dispatchEvent(ev) { (this.listeners[ev && ev.type] || []).forEach((fn) => fn(ev)); return true; },
  dispatchEvent_: null,
};
win.window = win;
win.self = win;
win.globalThis = win;

const sandbox = Object.assign(Object.create(null), win);
sandbox.fetch = fakeFetch;
const ctx = vm.createContext(sandbox);
// strict deps 프록시: 두 모듈 밖으로 나가는 표면을 정의된 키만 허용한다.
const strictFactory = new Function("fetch", "return (" + "function () {})" + ";");
for (const key of ["Promise", "Object", "Number", "String", "Boolean", "Array", "Set",
                   "Math", "JSON", "Error", "URL", "TextEncoder", "btoa", "atob",
                   "setTimeout", "clearTimeout", "console"]) {
  ctx[key] = vm.runInContext(key, ctx);
}

function decodeMetadata(value) {
  const out = {};
  String(value || "").split(",").forEach((pair) => {
    const at = pair.indexOf(" ");
    if (at < 0) return;
    const key = pair.slice(0, at);
    out[key] = Buffer.from(pair.slice(at + 1), "base64").toString("utf8");
  });
  return out;
}

const results = {};

async function main() {
  const [tusPath, lanePath, capsPath, strictPath] = process.argv.slice(2);
  const strictSource = fs.readFileSync(strictPath, "utf8");
  vm.runInContext(strictSource + "\nthis.r5StrictDeps = r5StrictDeps;", ctx, {filename: "_r5_strict_deps.js"});

  // 역량 모듈을 먼저 깔고, 그 표면을 프록시로 감싼 채 나머지를 얹는다.
  vm.runInContext(fs.readFileSync(capsPath, "utf8"), ctx, {filename: "attachment-capabilities.js"});
  ctx.window.PadiemAttachmentCapabilities =
    ctx.r5StrictDeps(ctx.window.PadiemAttachmentCapabilities, "PadiemAttachmentCapabilities");

  // ── attachment-capabilities.js: setMaxPerMessage 저장·클램프 ─────────────
  const caps = ctx.window.PadiemAttachmentCapabilities;
  const capSamples = [3, "4", 0, -1, 2.5, null, undefined, "abc", 1, 10, Infinity].map((value) => ({
    value: value === undefined ? null : value,
    stored: (caps.setMaxPerMessage(value), caps.maxPerMessage),
  }));
  results.caps = {
    samples: capSamples,
    accept: caps.accept,
    documentCount: caps.allDocuments.length,
    binarySupported: caps.binarySupported,
  };

  // ── tus-upload.js + file-lane.js 누적 ────────────────────────────────────
  vm.runInContext(fs.readFileSync(tusPath, "utf8"), ctx, {filename: "tus-upload.js"});
  ctx.window.PadiemTusUpload = ctx.r5StrictDeps(ctx.window.PadiemTusUpload, "PadiemTusUpload");
  vm.runInContext(fs.readFileSync(lanePath, "utf8"), ctx, {filename: "file-lane.js"});
  ctx.window.PadiemFileLane = ctx.r5StrictDeps(ctx.window.PadiemFileLane, "PadiemFileLane");

  results.tus = await observeTus(ctx, calls, routes);
  results.lane = await observeLane(ctx, calls, routes);
  results.requests = calls;

  process.stdout.write(JSON.stringify(results));
}

// ── tus: 한도 발견 → 생성 → 조각 → 결과 ──────────────────────────────────
function reset(table, list) {
  table.length = 0;
  list.length = 0;
}
function makeFile(name, size) {
  return {
    name,
    size,
    slice(start, end) { return {start, end, size: end - start}; },
  };
}
const TUS_ENDPOINT = "/api/chat/attachments/tus";
function findCalls(list, method) { return list.filter((c) => c.method === method); }

async function observeTus(ctx, calls, routes) {
  const out = {};

  // 1) 한 번에 끝나는 업로드: 진행률·상태·요청 순서·조각 크기·메타데이터
  reset(routes, calls);
  const states = [];
  const progress = [];
  const file9 = makeFile("보고서 note.txt", 9);
  routes.push(
    {method: "OPTIONS", match: (u) => u === TUS_ENDPOINT,
      reply: () => response(204, {"Tus-Max-Size": "1048576", "X-Padiem-Tus-Chunk-Max": "4"})},
    {method: "POST", match: (u) => u === TUS_ENDPOINT,
      reply: () => response(201, {Location: "/api/chat/attachments/tus/abc"}, {})},
    {method: "PATCH", match: (u) => u.endsWith("/abc"),
      reply: function () {
        const last = findCalls(calls, "PATCH").pop();
        const next = Number(last.headers["Upload-Offset"]) + last.bodyBytes;
        return response(204, {"Upload-Offset": String(next)});
      }},
    {method: "GET", match: (u) => u.endsWith("/abc"),
      reply: () => response(200, {}, {file: {file_id: "file_" + "a".repeat(32), size_bytes: 9}})},
  );
  const body = await ctx.window.PadiemTusUpload.upload({
    file: file9, endpoint: TUS_ENDPOINT, mediaType: "text/plain",
    onProgress: (sent, total) => progress.push([sent, total]),
    onState: (state) => states.push(state),
  });
  const post = findCalls(calls, "POST")[0];
  const patches = findCalls(calls, "PATCH");
  out.single = {
    result: body,
    order: calls.map((c) => c.method),
    states: states.map((s) => [s.phase, s.percent]),
    progress: progress,
    options: {
      url: findCalls(calls, "OPTIONS")[0].url,
      tusResumable: findCalls(calls, "OPTIONS")[0].headers["Tus-Resumable"],
    },
    post: {
      url: post.url,
      tusResumable: post.headers["Tus-Resumable"],
      uploadLength: post.headers["Upload-Length"],
      metadata: decodeMetadata(post.headers["Upload-Metadata"]),
    },
    patchSizes: patches.map((c) => c.bodyBytes),
    patchOffsets: patches.map((c) => c.headers["Upload-Offset"]),
    patchContentType: patches.map((c) => c.headers["Content-Type"]),
    patchTusResumable: patches.map((c) => c.headers["Tus-Resumable"]),
    resultCall: {method: findCalls(calls, "GET").length ? "GET" : null,
      url: findCalls(calls, "GET")[0] ? findCalls(calls, "GET")[0].url : null},
  };

  // 2) 413: 서버 한도 문구(한국어·바이트 표기)는 1차 안내에서만 나온다.
  reset(routes, calls);
  routes.push(
    {method: "OPTIONS", match: () => true,
      reply: () => response(204, {"Tus-Max-Size": "1048576", "X-Padiem-Tus-Chunk-Max": "4"})},
    {method: "POST", match: () => true,
      reply: () => response(413, {}, {error: {code: "request_too_large", message: "upstream said nope"}})},
  );
  out.tooLarge = await captureError(ctx, makeFile("big.txt", 9));

  // 3) 화면이 서버 본문 문구를 그대로 노출하지 않는다.
  reset(routes, calls);
  routes.push(
    {method: "OPTIONS", match: () => true, reply: () => response(204, {"Tus-Max-Size": "0"})},
    {method: "POST", match: () => true,
      reply: () => response(422, {}, {error: {code: "unsupported_kind", message: "upstream said nope"}})},
  );
  out.serverBody = await captureError(ctx, makeFile("weird.txt", 3));

  // 4) 끊김(네트워크) → HEAD 재개 → 이어 올림 → 결과
  reset(routes, calls);
  const resumeStates = [];
  let patchAttempts = 0;
  routes.push(
    {method: "OPTIONS", match: () => true,
      reply: () => response(204, {"Tus-Max-Size": "1048576", "X-Padiem-Tus-Chunk-Max": "4"})},
    {method: "POST", match: () => true,
      reply: () => response(201, {Location: "/api/chat/attachments/tus/r"}, {})},
    {method: "HEAD", match: () => true, reply: () => response(200, {"Upload-Offset": "4"})},
    {method: "PATCH", match: () => true,
      reply: function () {
        patchAttempts += 1;
        if (patchAttempts === 1) return Promise.reject(new Error("socket hang up"));
        const last = findCalls(calls, "PATCH").pop();
        return response(204, {"Upload-Offset": String(Number(last.headers["Upload-Offset"]) + last.bodyBytes)});
      }},
    {method: "GET", match: () => true,
      reply: () => response(200, {}, {file: {file_id: "file_" + "b".repeat(32), size_bytes: 9}})},
  );
  await ctx.window.PadiemTusUpload.upload({
    file: makeFile("resume.txt", 9), endpoint: TUS_ENDPOINT, mediaType: "text/plain",
    onState: (state) => resumeStates.push([state.phase, state.percent]),
  });
  out.resume = {
    order: calls.map((c) => c.method),
    headOffsets: findCalls(calls, "HEAD").map((c) => c.url),
    patchOffsets: findCalls(calls, "PATCH").map((c) => c.headers["Upload-Offset"]),
    phases: resumeStates,
  };

  // 5) 중단(digital abort)은 재시도를 돌리지 않고 즉시 한국어 안내로 끝난다.
  reset(routes, calls);
  const controller = new AbortController();
  routes.push(
    {method: "OPTIONS", match: () => true, reply: () => response(204, {"Tus-Max-Size": "1048576"})},
    {method: "POST", match: () => true,
      reply: () => { controller.abort(); return response(201, {Location: "/x"}, {}); }},
  );
  out.abort = await captureError(ctx, makeFile("cancel.txt", 9), controller.signal);
  out.abortRequests = calls.map((c) => c.method);

  return out;
}

async function captureError(ctx, file, signal, run) {
  try {
    if (typeof run === "function") { await run(); return {threw: false}; }
    await ctx.window.PadiemTusUpload.upload({
      file, endpoint: TUS_ENDPOINT, mediaType: "text/plain", signal,
    });
    return {threw: false};
  } catch (error) {
    return {
      threw: true,
      message: String(error && error.message || ""),
      safe: error && error.uiMessageSafe === true,
      code: error && error.code ? error.code : null,
    };
  }
}

// ── file-lane: 임계값·역량 조회·티켓·tus 라우팅 ────────────────────────
async function observeLane(ctx, calls, routes) {
  const out = {};
  const lane = ctx.window.PadiemFileLane;

  out.threshold = {autoBytes: lane.AUTO_BYTES, samples: []};
  const sizes = [0, -1, 1, 9_999_999, 10_000_000, 10_000_001];
  for (const size of sizes) {
    out.threshold.samples.push({
      size, txt: lane.shouldUse({name: "a.txt", size}),
      png: lane.shouldUse({name: "a.png", size}),
      hwpxSmall: lane.shouldUse({name: "a.hwpx", size: 7}),
    });
  }
  // 바이너리 레인 지원 표시가 켜지면 작은 pdf도 레인으로 간주한다.
  ctx.window.PadiemAttachmentCapabilities.setFileLaneSupport(true);
  out.threshold.binaryLane = {
    pdfSmall: lane.shouldUse({name: "a.pdf", size: 7}),
    txtSmall: lane.shouldUse({name: "a.txt", size: 7}),
  };
  ctx.window.PadiemAttachmentCapabilities.setFileLaneSupport(false);

  // 역량 조회: 응답의 개수 한도를 setMaxPerMessage로 옮긴다(서버가 최종 판정).
  reset(routes, calls);
  routes.push({method: "GET", match: (u) => u === "/api/files/capabilities",
    reply: () => response(200, {}, {ready: true, max_per_message: 4})});
  out.capabilities = {
    ready: await lane.available(),
    maxPerMessage: ctx.window.PadiemAttachmentCapabilities.maxPerMessage,
    url: calls[0].url,
    method: calls[0].method,
  };
  reset(routes, calls);
  routes.push({method: "GET", match: () => true, reply: () => response(500, {}, null)});
  out.capabilitiesNotReady = await lane.available();

  // tus 라우팅: 조각 레인이 받는 형식은 공용 모듈로, 아니면 COM2 티켓으로.
  reset(routes, calls);
  const laneStates = [];
  routes.push(
    {method: "OPTIONS", match: () => true,
      reply: () => response(204, {"Tus-Max-Size": "1048576", "X-Padiem-Tus-Chunk-Max": "4"})},
    {method: "POST", match: (u) => u === "/api/chat/attachments/tus",
      reply: () => response(201, {Location: "/api/chat/attachments/tus/t1"}, {})},
    {method: "PATCH", match: (u) => u.endsWith("/t1"),
      reply: function () {
        const last = findCalls(calls, "PATCH").pop();
        return response(204, {"Upload-Offset": String(Number(last.headers["Upload-Offset"]) + last.bodyBytes)});
      }},
    {method: "GET", match: (u) => u.endsWith("/t1"),
      reply: () => response(200, {}, {file: {file_id: "file_" + "c".repeat(32), size_bytes: 9}})},
  );
  out.laneTus = {
    result: await lane.upload(makeFile("resumable.csv", 9), undefined, (s) => laneStates.push(s.phase)),
    methods: calls.map((c) => c.method),
    urls: calls.slice(0, 2).map((c) => c.url),
    states: laneStates,
  };

  // 받지 않는 형식(hwpx)은 티켓 경로로 간다: 티켓 POST → 업로드 POST.
  reset(routes, calls);
  routes.push(
    {method: "POST", match: (u) => u === "/api/files/ticket",
      reply: () => response(200, {}, {ok: true, upload_url: "https://files.padiem.test/files",
        headers: {"x-test": "1"}, max_bytes: 9})},
    {method: "POST", match: (u) => u.indexOf("https://files.padiem.test/") === 0,
      reply: () => response(200, {}, {ok: true, file_id: "file_" + "d".repeat(32), size_bytes: 9})},
  );
  out.laneTicket = {
    result: await lane.upload(makeFile("legacy.hwpx", 9), undefined, () => {}),
    methods: calls.map((c) => c.method),
    ticketUrl: findCalls(calls, "POST")[0].url,
    uploadUrl: findCalls(calls, "POST")[1] ? findCalls(calls, "POST")[1].url : null,
  };

  // 티켓 응답의 file_id 모양이 틀리면 화면은 공통 한국어 안내를 만든다.
  reset(routes, calls);
  routes.push(
    {method: "POST", match: (u) => u === "/api/files/ticket",
      reply: () => response(200, {}, {ok: true, upload_url: "https://files.padiem.test/files", headers: {}})},
    {method: "POST", match: (u) => u.indexOf("https://files.padiem.test/") === 0,
      reply: () => response(200, {}, {ok: true, file_id: "not-a-file-id", size_bytes: 9})},
  );
  out.laneBadId = await captureError(ctx, null, undefined, () =>
    lane.upload(makeFile("legacy.hwpx", 9), undefined, () => {}));

  return out;
}

main().catch((error) => { console.error(error && error.stack || error); process.exit(1); });
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for the transport upload harness")
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(_NODE, encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(harness), str(TUS), str(LANE), str(CAPS),
             str(Path(__file__).resolve().parent / "_r5_strict_deps.js")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@lru_cache(maxsize=1)
def observations() -> dict:
    """모듈을 실제 실행해 얻은 한 번의 관찰(시험 파일 간 공유)."""

    return _run_harness()
