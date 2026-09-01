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
    end = rich.index("  const messageObserver", start)
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


def test_composer_disabled_state_is_the_single_rich_enhancement_gate() -> None:
    rich = _source(RICH_PATH)
    start = rich.index("  function canEnhanceAnswers() {")
    end = rich.index("  function enhanceAssistantMessage(", start)
    helper = rich[start:end]

    result = json.loads(
        _run_node(
            "let messageInput = { disabled: true };\n"
            + helper
            + "\nconst during = canEnhanceAnswers();\n"
            + "messageInput.disabled = false;\n"
            + "const after = canEnhanceAnswers();\n"
            + "console.log(JSON.stringify({ during, after }));"
        )
    )

    assert result == {"during": False, "after": True}


def test_progressive_rich_response_executes_only_after_final_dom_settles() -> None:
    runtime = _rich_runtime()
    script = r'''
class TextNode {
  constructor(value) {
    this.tagName = "#TEXT";
    this.children = [];
    this.parentNode = null;
    this._text = String(value ?? "");
  }

  get textContent() {
    return this._text;
  }

  set textContent(value) {
    this._text = String(value ?? "");
  }

  hasClass() {
    return false;
  }
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
    this.classList = {
      add: (...names) => names.forEach((name) => this._classes.add(name)),
    };
  }

  get textContent() {
    if (this.children.length) return this.children.map((child) => child.textContent).join("");
    return this._text;
  }

  set textContent(value) {
    this._text = String(value ?? "");
    this.children = [];
  }

  get childElementCount() {
    return this.children.length;
  }

  hasClass(name) {
    return this._classes.has(name) || String(this.className).split(/\s+/).includes(name);
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  append(...nodes) {
    nodes.forEach((node) => this.appendChild(node));
  }

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

const document = {
  createElement(tagName) { return new Element(tagName); },
  createTextNode(value) { return new TextNode(value); },
};
const messageInput = { disabled: true };
const messageList = {
  active: [],
  querySelectorAll(selector) {
    if (selector !== ".assistant-message") throw new Error("unexpected selector");
    return this.active;
  },
};
'''+ runtime + r'''

function makeArticle(text, withError = false) {
  const article = new Element("article");
  article.className = "assistant-message";
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

function findRich(content) {
  return content.children.find((child) => child.hasClass("rich-response")) || null;
}

function snapshot(entry) {
  return {
    flag: entry.article.dataset.richResponse || null,
    hidden: entry.paragraph.hidden,
    richCount: entry.content.children.filter((child) => child.hasClass("rich-response")).length,
  };
}

function richShape(entry) {
  const rich = findRich(entry.content);
  if (!rich) return null;
  const heading = rich.children[0] || null;
  const list = rich.children[1] || null;
  return {
    flag: entry.article.dataset.richResponse || null,
    hidden: entry.paragraph.hidden,
    sourceText: entry.paragraph.textContent,
    richCount: entry.content.children.filter((child) => child.hasClass("rich-response")).length,
    headingTag: heading ? heading.tagName : null,
    heading: heading ? heading.textContent : null,
    listTag: list ? list.tagName : null,
    items: list ? list.children.map((child) => child.textContent) : [],
  };
}

// Progressive stream: every mutation-equivalent trigger while in flight must fail closed.
const progressive = makeArticle("# 제");
messageList.active = [progressive.article];
messageInput.disabled = true;
enhanceAllAnswers();
const first = snapshot(progressive);
progressive.paragraph.textContent = "# 제목\n- 항목 1";
enhanceAllAnswers();
const middle = snapshot(progressive);
progressive.paragraph.textContent = "# 제목\n- 항목 1\n- 항목 2";
enhanceAllAnswers();
const finalWhileActive = snapshot(progressive);

// app.js finally releases the composer; the disabled-attribute observer calls this entry point.
messageInput.disabled = false;
enhanceAllAnswers();
enhanceAllAnswers();
const done = richShape(progressive);

// delta + delta + done can be parsed in one network turn; release still occurs only after final text.
const sameChunk = makeArticle("# 제");
messageList.active = [sameChunk.article];
messageInput.disabled = true;
enhanceAllAnswers();
sameChunk.paragraph.textContent = "# 제목\n";
enhanceAllAnswers();
sameChunk.paragraph.textContent = "# 제목\n- 항목 1\n- 항목 2";
enhanceAllAnswers();
const sameChunkBeforeRelease = snapshot(sameChunk);
messageInput.disabled = false;
enhanceAllAnswers();
const sameChunkDone = richShape(sameChunk);

// Post-start stream error must remain raw partial text because the existing error guard wins after unlock.
const errored = makeArticle("# 부분 응답", true);
messageList.active = [errored.article];
messageInput.disabled = false;
enhanceAllAnswers();
const errorState = snapshot(errored);

// Stored/completed answers are still eligible when no request is active.
const stored = makeArticle("# 저장된 제목\n- 저장 항목 1\n- 저장 항목 2");
messageList.active = [stored.article];
messageInput.disabled = false;
enhanceAllAnswers();
const storedState = richShape(stored);

console.log(JSON.stringify({
  first,
  middle,
  finalWhileActive,
  done,
  sameChunkBeforeRelease,
  sameChunkDone,
  errorState,
  storedState,
}));
'''

    result = json.loads(_run_node(script))

    locked = {"flag": None, "hidden": False, "richCount": 0}
    assert result["first"] == locked
    assert result["middle"] == locked
    assert result["finalWhileActive"] == locked

    expected_done = {
        "flag": "true",
        "hidden": True,
        "sourceText": "# 제목\n- 항목 1\n- 항목 2",
        "richCount": 1,
        "headingTag": "H3",
        "heading": "제목",
        "listTag": "UL",
        "items": ["항목 1", "항목 2"],
    }
    assert result["done"] == expected_done
    assert result["sameChunkBeforeRelease"] == locked
    assert result["sameChunkDone"] == expected_done
    assert result["errorState"] == locked
    assert result["storedState"] == {
        "flag": "true",
        "hidden": True,
        "sourceText": "# 저장된 제목\n- 저장 항목 1\n- 저장 항목 2",
        "richCount": 1,
        "headingTag": "H3",
        "heading": "저장된 제목",
        "listTag": "UL",
        "items": ["저장 항목 1", "저장 항목 2"],
    }


def test_stream_lifecycle_and_disabled_attribute_observer_remain_authoritative() -> None:
    rich = _source(RICH_PATH)
    app = _source(APP_PATH)

    assert 'const messageInput = document.getElementById("messageInput");' in rich
    assert 'lifecycleObserver.observe(messageInput, { attributes: true, attributeFilter: ["disabled"] });' in rich
    assert "if (canEnhanceAnswers()) enhanceAllAnswers();" in rich

    assert "input.disabled = inFlight;" in app
    assert "paragraph.textContent = answer;" in app
    request_start = app.index("  async function requestAnswer(")
    request_end = app.index("  async function submitPrompt(", request_start)
    request_source = app[request_start:request_end]
    assert "inFlight = true;" in request_source
    finally_start = request_source.index("    } finally {")
    request_finally = request_source[finally_start:]
    assert request_finally.index("inFlight = false;") < request_finally.index("updateComposer();")


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
