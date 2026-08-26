from __future__ import annotations

import subprocess
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
STREAM_JS = APP_ROOT / "static" / "search-sources.js"
APP_JS = APP_ROOT / "static" / "app.js"


def test_browser_streaming_source_contract_is_bounded() -> None:
    source = STREAM_JS.read_text(encoding="utf-8")
    app = APP_JS.read_text(encoding="utf-8")

    assert 'nativeFetch("/api/chat/stream"' in source
    assert 'Array.isArray(payload.attachments) && payload.attachments.length > 0' in source
    assert 'payload.tool !== undefined || payload.tool_input !== undefined' in source
    assert 'new TextDecoder("utf-8")' in source
    assert 'decoder.decode(result.value, { stream: true })' in source
    assert '["delta", "done", "error"]' in source
    assert 'state.textNode.appendData(delta)' in source
    assert 'label.textContent = "AI 응답"' in source
    assert 'window.addEventListener("pagehide", abortActiveStream)' in source
    assert 'newChatButton.addEventListener("click", abortActiveStream, true)' in source
    assert 'loginButton.addEventListener("click", abortActiveStream, true)' in source

    # Existing app state machine stays completion-gated. The transport adapter returns
    # a synthetic completed JSON response only after public SSE DONE, so partial text
    # never enters the browser conversation state on error/EOF.
    assert 'const response = await fetch("/api/chat", {' in app
    assert 'renderAnswer(article, data);' in app
    assert 'messages = outboundMessages.concat([{ role: "assistant", content: data.answer }]).slice(-20);' in app


def test_browser_streaming_runtime_with_real_node_web_streams() -> None:
    harness = r'''
const fs = require("fs");
const assert = require("assert");

class FakeTarget {
  constructor() { this.listeners = new Map(); }
  addEventListener(name, fn) {
    const list = this.listeners.get(name) || [];
    list.push(fn);
    this.listeners.set(name, list);
  }
  removeEventListener(name, fn) {
    const list = this.listeners.get(name) || [];
    this.listeners.set(name, list.filter((item) => item !== fn));
  }
  dispatch(name) {
    for (const fn of this.listeners.get(name) || []) fn({ type: name, target: this });
  }
}

class FakeText {
  constructor(text = "") { this.data = text; }
  appendData(value) { this.data += value; }
}

class FakeElement extends FakeTarget {
  constructor(kind = "div") {
    super();
    this.kind = kind;
    this.children = [];
    this.textContent = "";
    this.isConnected = true;
  }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; }
  querySelector(selector) {
    if (selector === ".assistant-content") return this.content || null;
    if (selector === "[data-runtime-label]") return this.label || null;
    return null;
  }
  querySelectorAll() { return []; }
  scrollIntoView() {}
}

const content = new FakeElement("content");
const label = new FakeElement("label");
const article = new FakeElement("article");
article.content = content;
article.label = label;
const messageList = new FakeElement("list");
messageList.querySelectorAll = (selector) => selector === ".assistant-message" ? [article] : [];
const newChatButton = new FakeTarget();
const loginButton = new FakeTarget();
const elements = { messageList, newChatButton, loginButton };

global.document = {
  getElementById: (id) => elements[id] || null,
  querySelectorAll: () => [],
  createElement: (kind) => new FakeElement(kind),
  createTextNode: (text) => new FakeText(text),
};

global.window = {
  location: { href: "https://example.test/" },
  addEventListener: () => {},
};

function responseFromBytes(chunks, status = 200, contentType = "text/event-stream") {
  let index = 0;
  return new Response(new ReadableStream({
    pull(controller) {
      if (index >= chunks.length) {
        controller.close();
        return;
      }
      controller.enqueue(chunks[index++]);
    },
  }), { status, headers: { "Content-Type": contentType } });
}

function splitInsideUtf8(text) {
  const bytes = new TextEncoder().encode(text);
  const needle = new TextEncoder().encode("안");
  let start = -1;
  outer: for (let i = 0; i <= bytes.length - needle.length; i += 1) {
    for (let j = 0; j < needle.length; j += 1) {
      if (bytes[i + j] !== needle[j]) continue outer;
    }
    start = i;
    break;
  }
  assert(start >= 0);
  const first = start + 1;
  const second = Math.min(bytes.length, start + needle.length + 5);
  return [bytes.slice(0, first), bytes.slice(first, second), bytes.slice(second)];
}

let scenario = "success";
let calls = [];
let lastSignal = null;

window.fetch = async (url, init = {}) => {
  calls.push({ url, init });
  if (url !== "/api/chat/stream") {
    return new Response(JSON.stringify({ answer: "completed-json" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }
  lastSignal = init.signal || null;
  if (scenario === "preerror") {
    return new Response(JSON.stringify({ error: { code: "quota", message: "잠시 후 다시 시도해 주세요." } }), {
      status: 429,
      headers: { "Content-Type": "application/json", "Retry-After": "30" },
    });
  }
  if (scenario === "error") {
    const raw = 'event: delta\ndata: {"delta":"부분"}\n\nevent: error\ndata: {"error":{"code":"stream_error","message":"중단됨"}}\n\n';
    return responseFromBytes([new TextEncoder().encode(raw)]);
  }
  if (scenario === "eof") {
    const raw = 'event: delta\ndata: {"delta":"부분"}\n\n';
    return responseFromBytes([new TextEncoder().encode(raw)]);
  }
  if (scenario === "pending") {
    return await new Promise((resolve, reject) => {
      init.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    });
  }
  const raw = 'event: delta\r\ndata: {"delta":"안"}\r\n\r\nevent: delta\ndata: {"delta":"녕"}\n\nevent: done\ndata: {"done":true,"conversation_id":"c1","project_id":"p1","project":{"id":"p1","name":"프로젝트"},"project_files_used":2}\n\n';
  return responseFromBytes(splitInsideUtf8(raw));
};

const source = fs.readFileSync("static/search-sources.js", "utf8");
eval(source);

(async () => {
  calls = [];
  scenario = "success";
  const response = await window.fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages: [{ role: "user", content: "안녕" }], mode: "auto", skill: "explain" }),
  });
  const data = await response.json();
  assert.deepEqual(calls.map((item) => item.url), ["/api/chat/stream"]);
  assert.equal(data.answer, "안녕");
  assert.equal(data.conversation_id, "c1");
  assert.equal(data.project_id, "p1");
  assert.equal(data.project_files_used, 2);
  assert.equal(label.textContent, "AI 응답");
  assert.equal(content.children.length, 1);
  assert.equal(content.children[0].children[0].data, "안녕");

  calls = [];
  await window.fetch("/api/chat", {
    method: "POST",
    body: JSON.stringify({ messages: [], mode: "auto", attachments: [{ type: "document" }] }),
  });
  assert.deepEqual(calls.map((item) => item.url), ["/api/chat"]);

  calls = [];
  await window.fetch("/api/chat", {
    method: "POST",
    body: JSON.stringify({ messages: [], mode: "auto", tool: "web_search" }),
  });
  assert.deepEqual(calls.map((item) => item.url), ["/api/chat"]);

  calls = [];
  scenario = "preerror";
  const denied = await window.fetch("/api/chat", {
    method: "POST",
    body: JSON.stringify({ messages: [], mode: "auto" }),
  });
  assert.equal(denied.status, 429);
  assert.deepEqual(calls.map((item) => item.url), ["/api/chat/stream"]);

  calls = [];
  scenario = "error";
  await assert.rejects(
    window.fetch("/api/chat", {
      method: "POST",
      body: JSON.stringify({ messages: [], mode: "auto" }),
    }),
    /중단됨/,
  );
  assert.deepEqual(calls.map((item) => item.url), ["/api/chat/stream"]);

  calls = [];
  scenario = "eof";
  await assert.rejects(
    window.fetch("/api/chat", {
      method: "POST",
      body: JSON.stringify({ messages: [], mode: "auto" }),
    }),
    /완료되지 않았습니다/,
  );
  assert.deepEqual(calls.map((item) => item.url), ["/api/chat/stream"]);

  calls = [];
  scenario = "pending";
  const pending = window.fetch("/api/chat", {
    method: "POST",
    body: JSON.stringify({ messages: [], mode: "auto" }),
  });
  await Promise.resolve();
  assert(lastSignal && !lastSignal.aborted);
  newChatButton.dispatch("click");
  await assert.rejects(pending, (error) => error && error.name === "AbortError");
  assert(lastSignal.aborted);
  assert.deepEqual(calls.map((item) => item.url), ["/api/chat/stream"]);

  console.log("BROWSER_STREAMING_HARNESS_OK");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''

    completed = subprocess.run(
        ["node", "-e", harness],
        cwd=APP_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "BROWSER_STREAMING_HARNESS_OK" in completed.stdout
