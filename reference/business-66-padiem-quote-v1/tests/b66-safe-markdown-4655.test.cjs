"use strict";
/* #4655 — the B66 assistant bubble must show real Markdown as formatted text
   without ever ingesting model HTML.

   These are behavioural tests: a minimal document stub records the exact node
   tree the renderer builds, so the assertions are about what a member would see
   rather than about the source text of the module. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const SOURCE_PATH = path.join(__dirname, "..", "b66-safe-markdown.js");
const markdown = require(SOURCE_PATH);

function makeDocument() {
  const doc = {};
  const text = (value) => ({ nodeType: 3, text: String(value) });

  function element(tag) {
    const node = {
      nodeType: 1,
      tagName: String(tag).toUpperCase(),
      childNodes: [],
      attributes: {},
      className: "",
      appendChild(child) {
        this.childNodes.push(child);
        return child;
      },
      setAttribute(name, value) {
        this.attributes[name] = String(value);
      },
      replaceChildren(...nodes) {
        this.childNodes = nodes;
      },
      get ownerDocument() {
        return doc;
      },
    };
    // Model the DOM accessor: assigning textContent replaces the children with
    // one text node, and reading it concatenates them. A plain property here
    // would hide exactly the text-safety behaviour under test.
    Object.defineProperty(node, "textContent", {
      get() {
        return this.childNodes.map((child) => (child.nodeType === 3 ? child.text : "")).join("");
      },
      set(value) {
        this.childNodes = value === "" ? [] : [text(value)];
      },
      configurable: true,
    });
    return node;
  }

  doc.createElement = (tag) => element(tag);
  doc.createTextNode = (value) => text(value);
  doc.createDocumentFragment = () => element("#fragment");
  return doc;
}

function escapeText(value) {
  return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function serialize(node) {
  if (!node) return "";
  if (node.nodeType === 3) return escapeText(node.text);
  const attrs = [];
  if (node.className) attrs.push('class="' + node.className + '"');
  for (const name of Object.keys(node.attributes).sort()) {
    attrs.push(name + '="' + node.attributes[name] + '"');
  }
  const tag = node.tagName.toLowerCase();
  const open = "<" + tag + (attrs.length ? " " + attrs.join(" ") : "") + ">";
  return open + node.childNodes.map(serialize).join("") + "</" + tag + ">";
}

function render(value) {
  const doc = makeDocument();
  const host = doc.createElement("div");
  markdown.renderAssistantMarkdown(host, value);
  return serialize(host);
}

function count(value, pattern) {
  return (value.match(pattern) || []).length;
}

/* ── the observed production regression ────────────────────────────── */
{
  // The exact owner-reported production output.
  const out = render("1. **한 번에 설명하기**\n2. **질문에 답하며 작성하기**");
  assert.match(out, /<strong>한 번에 설명하기<\/strong>/);
  assert.match(out, /<strong>질문에 답하며 작성하기<\/strong>/);
  assert.doesNotMatch(out, /\*\*/, "no literal delimiter may survive a paired bold");
  assert.match(out, /class="b66-md-marker"[^>]*>1\.</);
  assert.match(out, /class="b66-md-marker"[^>]*>2\.</);
}

/* ── unmatched syntax stays literal ────────────────────────────────── */
{
  assert.match(render("아직 **닫히지 않음"), /\*\*닫히지 않음/);
  assert.doesNotMatch(render("아직 **닫히지 않음"), /<strong>/);
  assert.match(render("빈 쌍 **** 은 그대로"), /\*\*\*\*/);
  assert.doesNotMatch(render("빈 쌍 **** 은 그대로"), /<strong>/);
}

/* ── the model's own numbering is never rewritten ──────────────────── */
{
  const out = render("5. 다섯째\n7. 일곱째");
  assert.match(out, /class="b66-md-marker"[^>]*>5\.</);
  assert.match(out, /class="b66-md-marker"[^>]*>7\.</);
  assert.doesNotMatch(out, />1\.</, "a non-sequential list must not be renumbered");

  const bullets = render("- 첫째\n- 둘째");
  assert.equal(count(bullets, /class="b66-md-marker"/g), 2);
  assert.match(bullets, /\u2022/);
}

/* ── paragraphs and lists are separate readable blocks ─────────────── */
{
  const out = render("첫 문단입니다.\n\n- 항목 하나\n- 항목 둘");
  assert.equal(count(out, /class="b66-md-paragraph"/g), 1);
  assert.equal(count(out, /class="b66-md-list"/g), 1, "consecutive bullets share one list");
  assert.equal(count(out, /role="listitem"/g), 2);
  assert.match(out, /role="list"/);
}

/* ── no HTML ingestion, ever ───────────────────────────────────────── */
{
  const out = render('<img src=x onerror="window.pwned=true"> **굵게**');
  assert.doesNotMatch(out, /<img/);
  assert.match(out, /&lt;img src=x onerror="window\.pwned=true"&gt;/);
  assert.match(out, /<strong>굵게<\/strong>/);
}

{
  const source = fs.readFileSync(SOURCE_PATH, "utf8");
  for (const sink of ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"]) {
    assert.ok(!source.includes(sink), sink + " must not appear in the renderer");
  }
  assert.match(source, /createTextNode/, "text must be written through text nodes");
}

/* ── the stored model text is never rewritten ──────────────────────── */
{
  const original = "**한 번에 설명하기** 그리고 이것도";
  const copy = String(original);
  markdown.parseBlocks(original);
  assert.equal(original, copy, "the presentation layer must not mutate its input");
  assert.deepEqual(markdown.parseInline(original), [
    { text: "한 번에 설명하기", strong: true },
    { text: " 그리고 이것도", strong: false },
  ]);

  // Every visible character of a multi-line answer survives parsing: only the
  // emphasis delimiters are consumed, and the step markers are kept verbatim.
  const answer = "1. **한 번에 설명하기**\n- 그리고 **이것도**";
  const reassembled = markdown
    .parseBlocks(answer)
    .map((block) => (block.marker ? block.marker : "") + block.runs.map((run) => run.text).join(""))
    .join("")
    .replace(/\s/g, "");
  assert.equal(reassembled, "1.한번에설명하기\u2022그리고이것도");
}

/* ── unsafe hosts fail closed so a caller can fall back ───────────── */
{
  assert.equal(markdown.renderAssistantMarkdown(null, "**x**"), null);
  assert.equal(markdown.renderAssistantMarkdown({}, "**x**"), null);
}

console.log("b66-safe-markdown-4655: all assertions passed");
