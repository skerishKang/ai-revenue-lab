/* #4655 — safe assistant-only Markdown presentation for the B66 AI dialogue.

   WHAT THIS IS
     The B66 assistant bubble used `content.textContent = text`, so real model
     output rendered literal delimiters (`1. **한 번에 설명하기**`). This module
     turns common assistant response syntax into DOM nodes instead.

   CONTRACT (must stay true)
     ASSISTANT_ONLY   Only assistant text may be rendered through here. A member's
                      own message must keep plain textContent.
     NO_HTML_INGEST   No markup sink is ever assigned. Every character is
                      written through text nodes, so model HTML cannot become
                      markup.
     UNMATCHED_STAYS  An unpaired `**`, an empty `****` pair and unknown syntax
                      stay literal text. Nothing is silently dropped or repaired.
     NO_TEXT_REWRITE  The stored/returned model text is never modified. This is a
                      presentation layer; the prompt and history keep `**`.
     NO_ENGINE        Deliberately small: bold, paragraph breaks and numbered/
                      bulleted steps. Not a general Markdown engine.
     EXACT_MARKERS    A list keeps the model's own marker text, so a model that
                      writes `5.` never silently displays as `1.`.

   Runs in the browser and in Node (tests inject a document stub). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.B66SafeMarkdown = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var BOLD = "**";
  var ORDERED = /^\s*(\d{1,3})[.)]\s+(.*)$/;
  var BULLET = /^\s*[-*\u2022]\s+(.*)$/;

  // Inline runs for one line. Only a paired `**` becomes strong; anything
  // unpaired is emitted verbatim so the member sees exactly what the model wrote.
  function parseInline(text) {
    var source = typeof text === "string" ? text : String(text == null ? "" : text);
    var runs = [];
    var rest = source;
    while (rest.length) {
      var open = rest.indexOf(BOLD);
      if (open === -1) {
        runs.push({ text: rest, strong: false });
        break;
      }
      var close = rest.indexOf(BOLD, open + BOLD.length);
      if (close === -1) {
        runs.push({ text: rest, strong: false });
        break;
      }
      var inner = rest.slice(open + BOLD.length, close);
      if (open > 0) runs.push({ text: rest.slice(0, open), strong: false });
      if (inner.length) {
        runs.push({ text: inner, strong: true });
      } else {
        // `****` is an empty pair, not emphasis; keep it literal.
        runs.push({ text: BOLD + BOLD, strong: false });
      }
      rest = rest.slice(close + BOLD.length);
    }
    if (!runs.length) runs.push({ text: "", strong: false });
    return runs;
  }

  // Block model: paragraphs plus ordered/bulleted steps. A blank line separates
  // paragraphs; consecutive steps of one kind form a single list.
  function parseBlocks(text) {
    var source = typeof text === "string" ? text : String(text == null ? "" : text);
    var lines = source.replace(/\r\n?/g, "\n").split("\n");
    var blocks = [];
    for (var i = 0; i < lines.length; i += 1) {
      var line = lines[i];
      if (!line.trim()) continue;
      var ordered = ORDERED.exec(line);
      if (ordered) {
        blocks.push({
          kind: "list",
          ordered: true,
          marker: ordered[1] + ".",
          runs: parseInline(ordered[2]),
        });
        continue;
      }
      var bullet = BULLET.exec(line);
      if (bullet) {
        blocks.push({
          kind: "list",
          ordered: false,
          marker: "\u2022",
          runs: parseInline(bullet[1]),
        });
        continue;
      }
      blocks.push({ kind: "paragraph", runs: parseInline(line) });
    }
    return blocks;
  }

  function appendRuns(doc, host, runs) {
    for (var i = 0; i < runs.length; i += 1) {
      var run = runs[i];
      if (!run.text) continue;
      if (run.strong) {
        var strong = doc.createElement("strong");
        strong.textContent = run.text;
        host.appendChild(strong);
      } else {
        host.appendChild(doc.createTextNode(run.text));
      }
    }
  }

  function elementFor(doc, block) {
    if (block.kind === "paragraph") {
      var paragraph = doc.createElement("p");
      paragraph.className = "b66-md-paragraph";
      appendRuns(doc, paragraph, block.runs);
      return paragraph;
    }
    var item = doc.createElement("div");
    item.className = "b66-md-item";
    item.setAttribute("role", "listitem");
    var marker = doc.createElement("span");
    marker.className = "b66-md-marker";
    marker.setAttribute("aria-hidden", "true");
    marker.textContent = block.marker;
    var body = doc.createElement("span");
    body.className = "b66-md-text";
    appendRuns(doc, body, block.runs);
    item.appendChild(marker);
    item.appendChild(body);
    return item;
  }

  // Builds the assistant bubble content. Returns null when it cannot render
  // safely, so a caller can fall back to plain text rather than lose the answer.
  function renderAssistantMarkdown(host, text) {
    if (!host || typeof host.replaceChildren !== "function") return null;
    var doc = host.ownerDocument || (typeof document !== "undefined" ? document : null);
    if (!doc || typeof doc.createElement !== "function") return null;
    var blocks = parseBlocks(text);
    var fragment = doc.createDocumentFragment();
    var list = null;
    var listOrdered = null;
    for (var i = 0; i < blocks.length; i += 1) {
      var block = blocks[i];
      if (block.kind === "list") {
        if (!list || listOrdered !== block.ordered) {
          list = doc.createElement("div");
          list.className = "b66-md-list";
          list.setAttribute("role", "list");
          listOrdered = block.ordered;
          fragment.appendChild(list);
        }
        list.appendChild(elementFor(doc, block));
        continue;
      }
      list = null;
      listOrdered = null;
      fragment.appendChild(elementFor(doc, block));
    }
    host.replaceChildren(fragment);
    return host;
  }

  return Object.freeze({
    parseInline: parseInline,
    parseBlocks: parseBlocks,
    renderAssistantMarkdown: renderAssistantMarkdown,
  });
});
