from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RICH_PATH = ROOT / "static" / "rich-response.js"
APP_PATH = ROOT / "static" / "app.js"
SEARCH_PATH = ROOT / "static" / "search-sources.js"
TRANSPORT_PATH = ROOT / "static" / "chat-transport.js"


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
        text=True, encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def test_browser_response_scripts_parse_with_node() -> None:
    for path in (APP_PATH, SEARCH_PATH, RICH_PATH):
        subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True,
            text=True, encoding="utf-8",
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
    this.classList = { add: (...names) => names.forEach((name) => this._classes.add(name)), contains: (name) => this._classes.has(name) };
    if (this.tagName === "TEMPLATE") {
      // A real <template> keeps its children in an inert fragment: not
      // rendered, not announced, not matched by content queries.
      const nodes = [];
      this.content = {
        children: nodes,
        appendChild(node) { node.parentNode = this; nodes.push(node); return node; },
        get textContent() { return nodes.map((node) => node.textContent).join(""); },
      };
    }
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
  replaceWith(...nodes) {
    if (!this.parentNode) throw new Error("orphan replace");
    const parent = this.parentNode;
    const index = parent.children.indexOf(this);
    parent.children.splice(index, 1, ...nodes);
    nodes.forEach((node) => { node.parentNode = parent; });
    this.parentNode = null;
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

function makeArticle(text, lifecycle = "streaming", withError = false, withNotice = false) {
  const article = new Element("article");
  article.className = "assistant-message";
  article.dataset.lifecycle = lifecycle;
  const content = new Element("div");
  content.className = "assistant-content";
  if (withNotice) {
    const notice = new Element("p");
    notice.className = "web-grounding-notice reference-note";
    notice.textContent = "웹 근거를 확인하지 못했습니다.";
    content.appendChild(notice);
  }
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
  const visible = entry.content.children.filter((child) => child.tagName !== "TEMPLATE");
  const source = entry.content.children.find((child) => child.tagName === "TEMPLATE");
  return {
    flag: entry.article.dataset.richResponse || null,
    rawParagraphGone: !entry.content.children.includes(entry.paragraph),
    sourceText: source ? source.content.textContent : null,
    richCount: visible.filter((child) => child.hasClass("rich-response")).length,
    // The answer text must exist exactly once in the renderable content.
    visibleText: visible.map((child) => child.textContent).join(""),
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

// A status note is never taken for the answer: the real answer paragraph is
// the one enhanced, and the notice keeps its own single copy.
const noticed = makeArticle("# 답 제목\n- 답 항목", "completed", false, true);
enhanceAssistantMessage(noticed.article);
const noticedState = snapshot(noticed);

console.log(JSON.stringify({ first, whileStreaming, completed, errorState, storedState, noticedState }));
'''
    result = json.loads(_run_node(script))

    def locked(visible):
        return {"flag": None, "rawParagraphGone": False, "sourceText": None, "richCount": 0, "visibleText": visible}

    assert result["first"] == locked("# 제")
    assert result["whileStreaming"] == locked("# 제목\n- 항목 1\n- 항목 2")
    answer_text = "# 제목\n- 항목 1\n- 항목 2"
    assert result["completed"] == {
        "flag": "true",
        "rawParagraphGone": True,
        "sourceText": answer_text,
        "richCount": 1,
        "visibleText": "제목항목 1항목 2",
    }
    assert result["completed"]["visibleText"].count("제목") == 1
    assert result["errorState"] == locked("# 부분 응답")
    assert result["storedState"]["flag"] == "true"
    assert result["storedState"]["rawParagraphGone"] is True
    assert result["storedState"]["sourceText"] == "# 저장된 제목\n- 저장 항목"
    assert result["storedState"]["richCount"] == 1
    assert result["storedState"]["visibleText"].count("저장 항목") == 1
    assert result["noticedState"]["flag"] == "true"
    assert result["noticedState"]["sourceText"] == "# 답 제목\n- 답 항목"
    assert result["noticedState"]["richCount"] == 1
    # The notice paragraph survives untouched next to the single rich answer.
    assert result["noticedState"]["visibleText"].startswith("웹 근거를 확인하지 못했습니다.")
    assert result["noticedState"]["visibleText"].count("답 제목") == 1


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
    # 대표 결정 11-03: 수동 검색 버튼 제거. 검색/리서치는 서버가 자동 선택하고
    # search-sources.js는 완료 응답의 evidence만 렌더링한다(요청 변조 없음).
    rich = _source(RICH_PATH)
    search = _source(SEARCH_PATH)
    html = _source(ROOT / "static" / "index.html")

    assert "fetch(" not in rich
    assert "PadiemChatToolBridge" not in rich
    for identifier in ("webSearchButton", "deepResearchButton", "webSearchStarterButton"):
        assert f'id="{identifier}"' not in html
    assert "payload.tool" not in search
    assert '"/api/chat/stream"' not in search
    assert '"/api/chat"' not in search
    assert "window.PadiemSearchSources = Object.freeze({ render: renderSources });" in search


def test_chat_transport_stays_out_of_response_renderers() -> None:
    rich = _source(RICH_PATH)
    search = _source(SEARCH_PATH)
    transport = _source(TRANSPORT_PATH)

    assert "fetch(" not in rich
    assert "PadiemChatToolBridge" not in rich
    assert "fetch(" not in search
    assert '"/api/chat/stream"' in transport
    assert '"/api/chat"' in transport


def test_thought_summary_redacts_identifiers_paths_and_url_queries() -> None:
    app = _source(APP_PATH)
    start = app.index("    function safeThoughtSummary(value) {")
    end = app.index("\n    function renderThoughtSummary", start)
    sanitizer = app[start:end]
    raw = (
        "run_id=run_123 trace_ID=trace_ABC dsp_456 pcr_789 evt_ABC "
        "UUID 123e4567-e89b-12d3-a456-426614174000 "
        "hex abcdef0123456789abcdef0123456789 "
        "/app/work/job.txt C:\\private\\job.txt ~/private/job.txt "
        "https://example.test/path?token=secret%2Fvalue&key=hidden"
    )
    script = (
        "const app = " + json.dumps(sanitizer, ensure_ascii=True) + ";\n"
        "const raw = " + json.dumps(raw, ensure_ascii=True) + ";\n"
        "const safe = new Function('payload', app + '\\nreturn safeThoughtSummary;')({messages: []});\n"
        "process.stdout.write(safe(raw));"
    )
    rendered = _run_node(script)

    for secret in (
        "run_123", "trace_ABC", "dsp_456", "pcr_789", "evt_ABC",
        "123e4567-e89b-12d3-a456-426614174000", "abcdef0123456789abcdef0123456789",
        "/app/work/job.txt", "C:\\private\\job.txt", "~/private/job.txt",
        "token=secret", "key=hidden",
    ):
        assert secret not in rendered
    assert "[internal ID redacted]" in rendered
    assert rendered.count("[file path redacted]") == 3
    assert "[query redacted]" in rendered


def test_streaming_delta_uses_incremental_text_node_updates() -> None:
    app = _source(APP_PATH)
    lifecycle = _source(ROOT / "static" / "message-lifecycle.js")
    stream_start = app.index("  async function requestStreamingAnswer(")
    stream_end = app.index("  async function requestAnswer(", stream_start)
    stream = app[stream_start:stream_end]

    assert "appendStreamDelta?.(answerTextNode, data.delta)" in stream
    assert "paragraph.textContent = answer;" not in stream
    assert "function appendStreamDelta(textNode, delta)" in lifecycle
