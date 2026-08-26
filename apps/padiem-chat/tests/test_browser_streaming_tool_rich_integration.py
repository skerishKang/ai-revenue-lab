from __future__ import annotations

import subprocess
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
SEARCH_JS = APP_ROOT / "static" / "search-sources.js"
RICH_JS = APP_ROOT / "static" / "rich-response.js"
APP_JS = APP_ROOT / "static" / "app.js"


def test_cross_module_streaming_contract_is_explicit() -> None:
    search = SEARCH_JS.read_text(encoding="utf-8")
    rich = RICH_JS.read_text(encoding="utf-8")
    app = APP_JS.read_text(encoding="utf-8")

    assert 'return path === "/api/chat" || path === "/api/chat/stream";' in search
    assert 'return chatPath(inputValue) === "/api/chat/stream";' in search
    assert 'if (isStreamingChat) requestTarget = "/api/chat";' in search
    assert 'payload.tool = toolId;' in search
    assert 'toolCompletedAsStream(data, article)' in search
    assert 'if (isStreamingChat) return instrumentStreamingResponse(response, article);' in search
    assert 'article.dataset.streamState = state;' in search

    # Rich rendering must never lock a partial answer. A DONE stream gets one task
    # to settle all same-chunk deltas before enhancement runs.
    assert 'article.dataset.streamState === "active" || article.dataset.streamState === "error"' in rich
    assert 'article.dataset.streamState === "done" && article.dataset.richResponseSettled !== "true"' in rich
    assert 'article.dataset.richResponseSettled = "pending";' in rich
    assert 'window.setTimeout(() => {' in rich
    assert 'attributeFilter: ["data-stream-state"]' in rich

    # Merged Slice 20 remains authority: app.js still owns direct progressive SSE
    # and attachment completed-JSON routing. This repair does not reimplement it.
    assert 'fetch("/api/chat/stream"' in app
    assert 'fetch("/api/chat"' in app
    assert 'return await requestCompletedAnswer' in app
    assert 'return await requestStreamingAnswer' in app


def test_tool_routing_and_stream_lifecycle_with_real_node_web_streams() -> None:
    harness = r'''
const fs = require("fs");
const assert = require("assert");

class FakeClassList {
  constructor() { this.values = new Set(); }
  toggle(name, enabled) { if (enabled) this.values.add(name); else this.values.delete(name); }
  add(name) { this.values.add(name); }
}

class FakeElement {
  constructor(text = "") {
    this.textContent = text;
    this.dataset = {};
    this.hidden = true;
    this.disabled = false;
    this.title = "";
    this.id = "";
    this.isConnected = true;
    this.listeners = new Map();
    this.attributes = new Map();
    this.classList = new FakeClassList();
  }
  addEventListener(name, fn, options) {
    const list = this.listeners.get(name) || [];
    list.push({ fn, options });
    this.listeners.set(name, list);
  }
  dispatch(name, target = this) {
    const entries = [...(this.listeners.get(name) || [])];
    for (const entry of entries) entry.fn({ type: name, target });
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) || null; }
  querySelector(selector) {
    if (selector === "small") return this.small || null;
    if (selector === ".assistant-content") return this.content || null;
    if (selector === ".typing" || selector === ".error-box") return null;
    return null;
  }
  querySelectorAll(selector) {
    if (selector === ".assistant-message") return this.assistants || [];
    return [];
  }
  closest(selector) { return selector === ".retry-button" && this.retry ? this : null; }
  focus() {}
}

global.Element = FakeElement;
global.MutationObserver = class { constructor(fn) { this.fn = fn; } observe() {} };

const webButton = new FakeElement("웹 검색");
const deepButton = new FakeElement("심층 리서치");
const webStarter = new FakeElement("웹에서 찾아줘");
webStarter.small = new FakeElement("");
const input = new FakeElement("");
const runtimeNote = new FakeElement("");
const attachmentThumb = new FakeElement("");
attachmentThumb.hidden = true;
const article = new FakeElement("");
const content = new FakeElement("");
article.content = content;
article.dataset = {};
const messageList = new FakeElement("");
messageList.assistants = [article];

const elements = {
  messageList,
  messageInput: input,
  runtimeNote,
  attachmentThumb,
  deepResearchButton: deepButton,
};

global.document = {
  getElementById(id) { return elements[id] || null; },
  querySelectorAll(selector) {
    if (selector === ".composer-tools .tool-button") return [webButton];
    if (selector === ".starter") return [webStarter];
    return [];
  },
  createElement() { return new FakeElement(""); },
};

global.window = {
  location: { href: "https://example.test/" },
  setTimeout,
};

let networkCalls = [];
let failNextTool = false;
function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function ordinaryStream() {
  return new Response(
    'event: delta\ndata: {"delta":"일반"}\n\nevent: delta\ndata: {"delta":" 답변"}\n\nevent: done\ndata: {"done":true}\n\n',
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}

window.fetch = async (url, init = {}) => {
  const body = typeof init.body === "string" ? JSON.parse(init.body) : null;
  networkCalls.push({ url, body });
  if (url === "/health") return jsonResponse({ web_tools_ready: true, deep_research_ready: true });
  if (url === "/api/chat/stream") return ordinaryStream();
  if (url === "/api/chat") {
    if (failNextTool) {
      failNextTool = false;
      return jsonResponse({ error: { code: "tool_failed", message: "도구 실패" } }, 503);
    }
    const tool = body && body.tool;
    return jsonResponse({
      answer: tool ? `${tool}-완료` : "json-완료",
      conversation_id: "c-tool",
      tool: tool ? { id: tool } : undefined,
    });
  }
  throw new Error(`unexpected URL ${url}`);
};

const source = fs.readFileSync("static/search-sources.js", "utf8");
eval(source);

(async () => {
  await new Promise((resolve) => setTimeout(resolve, 0));

  networkCalls = [];
  article.dataset = {};
  const ordinary = await window.fetch("/api/chat/stream", {
    method: "POST",
    body: JSON.stringify({ messages: [{ role: "user", content: "일반" }], mode: "auto" }),
  });
  assert.equal(networkCalls.length, 1);
  assert.equal(networkCalls[0].url, "/api/chat/stream");
  assert.equal(networkCalls[0].body.tool, undefined);
  assert.equal(article.dataset.streamState, "active");
  const ordinaryText = await ordinary.text();
  assert(ordinaryText.includes('event: done'));
  assert.equal(article.dataset.streamState, "done");

  networkCalls = [];
  article.dataset = {};
  webButton.dispatch("click");
  const web = await window.fetch("/api/chat/stream", {
    method: "POST",
    body: JSON.stringify({ messages: [{ role: "user", content: "웹" }], mode: "auto" }),
  });
  assert.equal(networkCalls.length, 1);
  assert.equal(networkCalls[0].url, "/api/chat");
  assert.equal(networkCalls[0].body.tool, "web_search");
  assert.equal(web.headers.get("content-type").includes("text/event-stream"), true);
  const webText = await web.text();
  assert(webText.includes('"delta":"web_search-완료"'));
  assert(webText.includes('"conversation_id":"c-tool"'));
  assert.equal(article.dataset.streamState, "done");

  networkCalls = [];
  article.dataset = {};
  deepButton.dispatch("click");
  const deep = await window.fetch("/api/chat/stream", {
    method: "POST",
    body: JSON.stringify({ messages: [{ role: "user", content: "깊게" }], mode: "auto" }),
  });
  assert.equal(networkCalls.length, 1);
  assert.equal(networkCalls[0].url, "/api/chat");
  assert.equal(networkCalls[0].body.tool, "deep_research");
  assert((await deep.text()).includes('"delta":"deep_research-완료"'));

  networkCalls = [];
  await window.fetch("/api/chat", {
    method: "POST",
    body: JSON.stringify({ messages: [], mode: "auto", attachments: [{ type: "document" }] }),
  });
  assert.equal(networkCalls.length, 1);
  assert.equal(networkCalls[0].url, "/api/chat");
  assert.equal(networkCalls[0].body.tool, undefined);

  // A failed tool call keeps retryTool. The existing capture-phase retry listener
  // must re-arm the same tool, and the next Slice-20 stream request must again be
  // rerouted to completed JSON rather than silently becoming ordinary SSE.
  networkCalls = [];
  webButton.dispatch("click");
  failNextTool = true;
  const failed = await window.fetch("/api/chat/stream", {
    method: "POST",
    body: JSON.stringify({ messages: [], mode: "auto" }),
  });
  assert.equal(failed.status, 503);
  assert.equal(networkCalls[0].url, "/api/chat");
  assert.equal(networkCalls[0].body.tool, "web_search");

  const retryTarget = new FakeElement("");
  retryTarget.retry = true;
  messageList.dispatch("click", retryTarget);
  networkCalls = [];
  const retried = await window.fetch("/api/chat/stream", {
    method: "POST",
    body: JSON.stringify({ messages: [], mode: "auto" }),
  });
  assert.equal(networkCalls[0].url, "/api/chat");
  assert.equal(networkCalls[0].body.tool, "web_search");
  assert((await retried.text()).includes('web_search-완료'));

  console.log("TOOL_STREAM_INTEGRATION_OK");
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
    assert "TOOL_STREAM_INTEGRATION_OK" in completed.stdout


def test_rich_response_waits_for_settled_done_text() -> None:
    harness = r'''
const fs = require("fs");
const assert = require("assert");

class FakeClassList { add() {} }
class FakeElement {
  constructor(tagName = "DIV", text = "") {
    this.tagName = tagName;
    this.textContent = text;
    this.dataset = {};
    this.children = [];
    this.hidden = false;
    this.isConnected = true;
    this.classList = new FakeClassList();
    this.childElementCount = 0;
  }
  appendChild(child) { this.children.push(child); this.childElementCount = this.children.length; return child; }
  querySelector(selector) {
    if (selector === ".assistant-content") return this.content || null;
    if (selector === ".typing" || selector === ".error-box") return null;
    return null;
  }
  querySelectorAll(selector) { return selector === ".assistant-message" ? (this.assistants || []) : []; }
  insertAdjacentElement(_where, element) { this.inserted = element; return element; }
  addEventListener() {}
  setAttribute() {}
}

global.Element = FakeElement;
let observerCallback = null;
let observerOptions = null;
global.MutationObserver = class {
  constructor(fn) { observerCallback = fn; }
  observe(_target, options) { observerOptions = options; }
};

const raw = new FakeElement("P", "첫");
const content = new FakeElement("DIV");
content.children = [raw];
const article = new FakeElement("ARTICLE");
article.content = content;
article.dataset.streamState = "active";
const messageList = new FakeElement("DIV");
messageList.assistants = [article];

global.document = {
  getElementById(id) { return id === "messageList" ? messageList : null; },
  createElement(tag) { return new FakeElement(String(tag).toUpperCase()); },
  body: new FakeElement("BODY"),
};
global.navigator = {};
global.URL = { createObjectURL() { return "blob:test"; }, revokeObjectURL() {} };
global.window = { setTimeout };

const source = fs.readFileSync("static/rich-response.js", "utf8");
eval(source);

(async () => {
  assert(observerCallback);
  assert.equal(observerOptions.attributes, true);
  assert.deepEqual(observerOptions.attributeFilter, ["data-stream-state"]);

  observerCallback();
  assert.equal(article.dataset.richResponse, undefined);

  article.dataset.streamState = "done";
  observerCallback();
  assert.equal(article.dataset.richResponseSettled, "pending");
  assert.equal(article.dataset.richResponse, undefined);

  // Simulate later deltas from the same network chunk arriving before the next task.
  raw.textContent = "첫둘셋 최종";
  observerCallback();
  assert.equal(article.dataset.richResponse, undefined);

  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(article.dataset.richResponseSettled, "true");
  assert.equal(article.dataset.richResponse, "true");
  assert.equal(raw.hidden, true);
  assert(raw.inserted);
  assert.equal(raw.inserted.children[0].textContent, "첫둘셋 최종");

  console.log("RICH_STREAM_SETTLE_OK");
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
    assert "RICH_STREAM_SETTLE_OK" in completed.stdout
