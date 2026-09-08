from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RICH_PATH = ROOT / "static" / "rich-response.js"
APP_PATH = ROOT / "static" / "app.js"
SEARCH_PATH = ROOT / "static" / "search-sources.js"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _rich_runtime() -> str:
    rich = _source(RICH_PATH)
    start = rich.index("  const HEADING_PATTERN")
    end = rich.index('  messageList.addEventListener("padiem:message-lifecycle"', start)
    return rich[start:end]


def _run_node(script: str) -> str:
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_browser_response_scripts_parse_with_node() -> None:
    for path in (APP_PATH, SEARCH_PATH, RICH_PATH):
        subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )


def test_rich_response_is_lifecycle_driven_without_broad_dom_observers() -> None:
    rich = _source(RICH_PATH)

    assert 'messageList.addEventListener("padiem:message-lifecycle"' in rich
    assert "api.states.COMPLETED" in rich
    assert "lifecycleApi().isCompleted(article)" in rich
    assert "MutationObserver" not in rich
    assert 'document.getElementById("messageInput")' not in rich
    assert "canEnhanceAnswers" not in rich


def test_progressive_rich_response_executes_only_for_completed_lifecycle() -> None:
    runtime = _rich_runtime()
    script = r'''
class TextNode {
  constructor(value) { this.tagName = "#TEXT"; this.children = []; this.parentNode = null; this._text = String(value ?? ""); }
  get textContent() { return this._text; }
  set textContent(value) { this._text = String(value ?? ""); }
  hasClass() { return false; }
}

class Element {
  constructor(tagName) {
    this.tagName = String(tagName || "div").toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.hidden = false;
    this.className = "";
    this._classes = new Set();
    this._text = "";
    this.classList = { add: (...names) => names.forEach((name) => this._classes.add(name)) };
  }
  get textContent() { return this.children.length ? this.children.map((child) => child.textContent).join("") : this._text; }
  set textContent(value) { this._text = String(value ?? ""); this.children = []; }
  get childElementCount() { return this.children.length; }
  hasClass(name) { return this._classes.has(name) || String(this.className).split(/\s+/).includes(name); }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  append(...nodes) { nodes.forEach((node) => this.appendChild(node)); }
  addEventListener() {}
  querySelector(selector) {
    if (!selector.startsWith(".")) return null;
    const className = selector.slice(1);
    const stack = [...this.children];
    while (stack.length) {
      const node = stack.shift();
      if (node.hasClass(className)) return node;
      stack.unshift(...node.children);
    }
    return null;
  }
  insertAdjacentElement(position, element) {
    if (position !== "afterend" || !this.parentNode) throw new Error("unsupported insertion");
    const index = this.parentNode.children.indexOf(this);
    element.parentNode = this.parentNode;
    this.parentNode.children.splice(index + 1, 0, element);
    return element;
  }
}

global.Element = Element;
const document = {
  createElement(tagName) { return new Element(tagName); },
  createTextNode(value) { return new TextNode(value); },
};
const window = {
  PadiemChatLifecycle: {
    states: { COMPLETED: "completed" },
    isCompleted(article) { return article && article.dataset.lifecycle === "completed"; },
  },
};
const messageList = {
  active: [],
  querySelectorAll(selector) {
    if (selector !== ".assistant-message") throw new Error("unexpected selector");
    return this.active;
  },
};
const navigator = {};
'''+ runtime + r'''

function makeArticle(text, lifecycle = "streaming", withError = false) {
  const article = new Element("article");
  article.className = "assistant-message";
  article.dataset.lifecycle = lifecycle;
  const content = new Element("div");
  content.className = "assistant-content";
  const paragraph = new Element("p");
  paragraph.textContent = text;
  article.appendChild(content);
  content.appendChild(paragraph);
  if (withError) {
    const error = new Element("div");
    error.className = "error-box";
    content.appendChild(error);
  }
  return { article, content, paragraph };
}

function snapshot(entry) {
  return {
    flag: entry.article.dataset.richResponse || null,
    hidden: entry.paragraph.hidden,
    richCount: entry.content.children.filter((child) => child.hasClass("rich-response")).length,
  };
}

const progressive = makeArticle("# 제", "streaming");
messageList.active = [progressive.article];
enhanceAllAnswers();
const first = snapshot(progressive);
progressive.paragraph.textContent = "# 제목\n- 항목 1\n- 항목 2";
enhanceAllAnswers();
const whileStreaming = snapshot(progressive);
progressive.article.dataset.lifecycle = "completed";
enhanceAssistantMessage(progressive.article);
const completed = snapshot(progressive);

const errored = makeArticle("# 부분 응답", "completed", true);
enhanceAssistantMessage(errored.article);
const errorState = snapshot(errored);

const stored = makeArticle("# 저장된 제목\n- 저장 항목", "completed");
enhanceAssistantMessage(stored.article);
const storedState = snapshot(stored);

console.log(JSON.stringify({ first, whileStreaming, completed, errorState, storedState }));
'''
    result = json.loads(_run_node(script))

    locked = {"flag": None, "hidden": False, "richCount": 0}
    assert result["first"] == locked
    assert result["whileStreaming"] == locked
    assert result["completed"] == {"flag": "true", "hidden": True, "richCount": 1}
    assert result["errorState"] == locked
    assert result["storedState"] == {"flag": "true", "hidden": True, "richCount": 1}


def test_request_state_remains_single_owned_by_app_controller() -> None:
    rich = _source(RICH_PATH)
    app = _source(APP_PATH)

    assert "let inFlight = false;" in app
    assert "let activeRequestController = null;" in app
    assert "let activeRequestCancelReason = null;" in app
    assert "let conversationEpoch = 0;" in app
    assert "inFlight" not in rich
    assert "activeRequestController" not in rich
    assert "conversationEpoch" not in rich


def test_stream_error_guard_and_completed_paths_remain_present() -> None:
    rich = _source(RICH_PATH)
    app = _source(APP_PATH)

    assert 'content.querySelector(".error-box")' in rich
    stream_start = app.index("  async function requestStreamingAnswer(")
    stream_end = app.index("  async function requestAnswer(", stream_start)
    stream = app[stream_start:stream_end]
    assert "renderStreamError(article, message" in stream
    assert "renderStreamError(article, error instanceof Error" in stream
    assert 'paragraph.textContent = result.answer;' in app
    assert 'paragraph.textContent = text;' in app


def test_slice21_tool_transport_contract_is_not_reimplemented_here() -> None:
    rich = _source(RICH_PATH)
    search = _source(SEARCH_PATH)

    assert "fetch(" not in rich
    assert "PadiemChatToolBridge" not in rich
    assert 'payload.tool = toolId' in search
    assert '"/api/chat/stream"' in search
    assert '"/api/chat"' in search
