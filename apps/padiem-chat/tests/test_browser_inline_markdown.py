from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RICH_PATH = ROOT / "static" / "rich-response.js"


def _rich_runtime() -> str:
    rich = RICH_PATH.read_text(encoding="utf-8")
    start = rich.index("  const HEADING_PATTERN")
    end = rich.index("  const messageObserver", start)
    return rich[start:end]


def _run_node(script: str) -> dict:
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip())


def test_inline_markdown_renders_safe_dom_nodes_across_blocks() -> None:
    runtime = _rich_runtime()
    script = r'''
class TextNode {
  constructor(value) {
    this.tagName = "#TEXT";
    this.children = [];
    this.parentNode = null;
    this._text = String(value ?? "");
  }
  get textContent() { return this._text; }
  set textContent(value) { this._text = String(value ?? ""); }
}

class Element {
  constructor(tagName) {
    this.tagName = String(tagName || "div").toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.className = "";
    this.hidden = false;
    this.href = "";
    this.target = "";
    this.rel = "";
    this._text = "";
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
    return this.children.filter((child) => child.tagName !== "#TEXT").length;
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
}

const document = {
  createElement(tagName) { return new Element(tagName); },
  createTextNode(value) { return new TextNode(value); },
};
'''+ runtime + r'''

function descendants(root, tagName) {
  const wanted = String(tagName).toUpperCase();
  const found = [];
  const stack = [...root.children];
  while (stack.length) {
    const node = stack.shift();
    if (node.tagName === wanted) found.push(node);
    stack.unshift(...(node.children || []));
  }
  return found;
}

const source = [
  "# **굵은 제목**",
  "- *기울임 항목*과 `inline_code`",
  "",
  "본문 **굵게** _기울임_ `코드` [안전 링크](https://example.com/docs) [위험 링크](javascript:alert(1))",
  "",
  "> **인용 강조**",
  "",
  "| **열 A** | 열 B |",
  "| --- | --- |",
  "| `셀 코드` | *셀 강조* |",
].join("\n");

const rich = buildRichResponse(source);
const links = descendants(rich, "a").map((node) => ({
  text: node.textContent,
  href: node.href,
  target: node.target,
  rel: node.rel,
}));

console.log(JSON.stringify({
  text: rich.textContent,
  strong: descendants(rich, "strong").map((node) => node.textContent),
  em: descendants(rich, "em").map((node) => node.textContent),
  code: descendants(rich, "code").map((node) => node.textContent),
  links,
  headings: descendants(rich, "h3").map((node) => node.textContent),
  items: descendants(rich, "li").map((node) => node.textContent),
  tableHeaders: descendants(rich, "th").map((node) => node.textContent),
  tableCells: descendants(rich, "td").map((node) => node.textContent),
}));
'''

    result = _run_node(script)

    assert result["strong"] == ["굵은 제목", "굵게", "인용 강조", "열 A"]
    assert result["em"] == ["기울임 항목", "기울임", "셀 강조"]
    assert result["code"] == ["inline_code", "코드", "셀 코드"]
    assert result["headings"] == ["굵은 제목"]
    assert result["items"] == ["기울임 항목과 inline_code"]
    assert result["tableHeaders"] == ["열 A", "열 B"]
    assert result["tableCells"] == ["셀 코드", "셀 강조"]
    assert result["links"] == [
        {
            "text": "안전 링크",
            "href": "https://example.com/docs",
            "target": "_blank",
            "rel": "noopener noreferrer",
        }
    ]
    assert "[위험 링크](javascript:alert(1))" in result["text"]


def test_inline_code_does_not_recursively_activate_markdown() -> None:
    runtime = _rich_runtime()
    script = r'''
class TextNode {
  constructor(value) { this.tagName = "#TEXT"; this.children = []; this._text = String(value ?? ""); }
  get textContent() { return this._text; }
  set textContent(value) { this._text = String(value ?? ""); }
}
class Element {
  constructor(tagName) { this.tagName = String(tagName).toUpperCase(); this.children = []; this.className = ""; this.dataset = {}; this._text = ""; }
  get textContent() { return this.children.length ? this.children.map((child) => child.textContent).join("") : this._text; }
  set textContent(value) { this._text = String(value ?? ""); this.children = []; }
  get childElementCount() { return this.children.filter((child) => child.tagName !== "#TEXT").length; }
  appendChild(child) { this.children.push(child); return child; }
  append(...nodes) { nodes.forEach((node) => this.appendChild(node)); }
  addEventListener() {}
}
const document = {
  createElement(tagName) { return new Element(tagName); },
  createTextNode(value) { return new TextNode(value); },
};
'''+ runtime + r'''
const rich = buildRichResponse("`**literal** [x](https://example.com)`");
const paragraph = rich.children[0];
const code = paragraph.children.find((node) => node.tagName === "CODE");
console.log(JSON.stringify({
  paragraphText: paragraph.textContent,
  codeText: code ? code.textContent : null,
  childTags: paragraph.children.filter((node) => node.tagName !== "#TEXT").map((node) => node.tagName),
}));
'''

    result = _run_node(script)
    assert result == {
        "paragraphText": "**literal** [x](https://example.com)",
        "codeText": "**literal** [x](https://example.com)",
        "childTags": ["CODE"],
    }


def test_html_like_payload_and_intraword_underscores_remain_exact_literal_text() -> None:
    runtime = _rich_runtime()
    script = r'''
class TextNode {
  constructor(value) { this.tagName = "#TEXT"; this.children = []; this._text = String(value ?? ""); }
  get textContent() { return this._text; }
  set textContent(value) { this._text = String(value ?? ""); }
}
class Element {
  constructor(tagName) { this.tagName = String(tagName).toUpperCase(); this.children = []; this.className = ""; this.dataset = {}; this._text = ""; }
  get textContent() { return this.children.length ? this.children.map((child) => child.textContent).join("") : this._text; }
  set textContent(value) { this._text = String(value ?? ""); this.children = []; }
  get childElementCount() { return this.children.filter((child) => child.tagName !== "#TEXT").length; }
  appendChild(child) { this.children.push(child); return child; }
  append(...nodes) { nodes.forEach((node) => this.appendChild(node)); }
  addEventListener() {}
}
const document = {
  createElement(tagName) { return new Element(tagName); },
  createTextNode(value) { return new TextNode(value); },
};
'''+ runtime + r'''
const payload = '<img src=x onerror="window.__PADIEM_HTML_EXECUTED = true">';
const rich = buildRichResponse(payload);
const paragraph = rich.children[0];
console.log(JSON.stringify({
  text: paragraph.textContent,
  childTags: paragraph.children.filter((node) => node.tagName !== "#TEXT").map((node) => node.tagName),
}));
'''

    result = _run_node(script)
    assert result == {
        "text": '<img src=x onerror="window.__PADIEM_HTML_EXECUTED = true">',
        "childTags": [],
    }
