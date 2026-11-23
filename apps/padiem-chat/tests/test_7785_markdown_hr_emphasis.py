"""#7785: '---' / '*' left as literal text must render as real markdown.

The rich renderer is addressed directly (it is the single answer surface):
a horizontal rule becomes <hr>, ** / __ become <strong>, * / _ become <em>,
*** / ___ become <strong><em>, and code stays literal. Every node is
createElement/textContent only, so an injected <script>/event attribute is
text, never markup.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.handoff_direct_markdown_source import (
    app_js, chat_routes, conversation_js, history_js, home_choices_js, index_html,
    read, run_history_js, six_panel_css, streaming_js,
)

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RICH_PATH = ROOT / "static" / "rich-response.js"


def _rich_runtime() -> str:
    rich = read(RICH_PATH)
    start = rich.index("  const HEADING_PATTERN")
    end = rich.index('  messageList.addEventListener("padiem:message-lifecycle"', start)
    return rich[start:end]


def _run_node(script: str) -> dict:
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout.strip())


_RUNTIME_PREFIX = r'''
class TextNode {
  constructor(value) { this.tagName = "#TEXT"; this.children = []; this._text = String(value ?? ""); }
  get textContent() { return this._text; }
  set textContent(value) { this._text = String(value ?? ""); }
}
class Element {
  constructor(tagName) { this.tagName = String(tagName || "div").toUpperCase(); this.children = []; this.className = ""; this.dataset = {}; this._text = ""; }
  get textContent() { return this.children.length ? this.children.map((c) => c.textContent).join("") : this._text; }
  set textContent(value) { this._text = String(value ?? ""); this.children = []; }
  get childElementCount() { return this.children.filter((c) => c.tagName !== "#TEXT").length; }
  appendChild(child) { this.children.push(child); return child; }
  append(...nodes) { nodes.forEach((n) => this.appendChild(n)); }
  addEventListener() {}
}
const document = {
  createElement(tagName) { return new Element(tagName); },
  createTextNode(value) { return new TextNode(value); },
};
'''


def test_horizontal_rules_render_as_hr_and_break_paragraphs() -> None:
    script = _RUNTIME_PREFIX + _rich_runtime() + r'''
const rich = buildRichResponse("---\n본문\n***\n본문2\n___\n본문3");
console.log(JSON.stringify({
  tags: rich.children.map((n) => n.tagName),
  ruleClass: rich.children.filter((n) => n.tagName === "HR").map((n) => n.className),
  text: rich.textContent,
}));
'''
    result = _run_node(script)
    assert result["tags"] == ["HR", "P", "HR", "P", "HR", "P"]
    assert result["ruleClass"] == ["rich-response-rule"] * 3
    assert "---" not in result["text"]
    assert "***" not in result["text"]
    assert "___" not in result["text"]
    assert "본문" in result["text"]


def test_bold_and_italic_forms_render_without_markers() -> None:
    script = _RUNTIME_PREFIX + _rich_runtime() + r'''
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
const rich = buildRichResponse("**굵게** *기울임* __굵게2__ _기울임2_ ***굵게기울임*** ___굵게기울임2___");
console.log(JSON.stringify({
  text: rich.textContent,
  strong: descendants(rich, "strong").map((n) => n.textContent),
  em: descendants(rich, "em").map((n) => n.textContent),
  strongEm: descendants(rich, "strong").map((s) => s.children.filter((c) => c.tagName === "EM").map((e) => e.textContent)),
}));
'''
    result = _run_node(script)
    assert result["strong"] == ["굵게", "굵게2", "굵게기울임", "굵게기울임2"]
    assert result["em"] == ["기울임", "기울임2", "굵게기울임", "굵게기울임2"]
    assert result["strongEm"] == [[], [], ["굵게기울임"], ["굵게기울임2"]]
    assert "**" not in result["text"] and "__" not in result["text"]
    assert "굵게기울임" in result["text"]


def test_lists_and_code_blocks_keep_their_contract() -> None:
    script = _RUNTIME_PREFIX + _rich_runtime() + r'''
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
const source = "- 항목1\n- 항목2\n\n```\n--- not a rule **still code**\n```\n\n`**not bold**` and `---` inline";
const rich = buildRichResponse(source);
console.log(JSON.stringify({
  items: descendants(rich, "li").map((n) => n.textContent),
  hrs: descendants(rich, "hr").length,
  codeBlocks: descendants(rich, "code").map((n) => n.textContent),
  text: rich.textContent,
}));
'''
    result = _run_node(script)
    assert result["items"] == ["항목1", "항목2"]
    # The fenced "---" and the inline `---` stay code; no rule is minted.
    assert result["hrs"] == 0
    assert "--- not a rule **still code**" in result["codeBlocks"]
    assert "**not bold**" in result["codeBlocks"]
    assert "---" in result["codeBlocks"]


def test_injected_markup_stays_literal_text() -> None:
    script = _RUNTIME_PREFIX + _rich_runtime() + r'''
const payload = '<script>alert(1)</script> <img src=x onerror="window.__PADIEM_HTML_EXECUTED = true">';
const rich = buildRichResponse(payload);
const paragraph = rich.children[0];
console.log(JSON.stringify({
  text: paragraph.textContent,
  childTags: paragraph.children.filter((n) => n.tagName !== "#TEXT").map((n) => n.tagName),
}));
'''
    result = _run_node(script)
    assert result["text"] == '<script>alert(1)</script> <img src=x onerror="window.__PADIEM_HTML_EXECUTED = true">'
    assert result["childTags"] == []
