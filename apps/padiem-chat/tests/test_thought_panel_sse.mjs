import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import { TextDecoder, TextEncoder } from "node:util";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../static");

class TextNode {
  constructor(value) {
    this.tagName = "#TEXT";
    this.children = [];
    this.parentElement = null;
    this._text = String(value ?? "");
  }

  get textContent() { return this._text; }
  set textContent(value) { this._text = String(value ?? ""); }
}

class Element {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentElement = null;
    this.className = "";
    this.dataset = {};
    this.open = false;
    this.type = "";
    this._text = "";
  }

  get childNodes() { return this.children; }

  get firstChild() { return this.children[0] || null; }

  get nextSibling() {
    const parent = this.parentElement;
    if (!parent) return null;
    const index = parent.children.indexOf(this);
    return index < 0 ? null : parent.children[index + 1] || null;
  }

  appendChild(node) {
    node.parentElement = this;
    this.children.push(node);
    return node;
  }

  append(...nodes) {
    for (const node of nodes) this.appendChild(node);
  }

  removeChild(node) {
    const index = this.children.indexOf(node);
    if (index >= 0) {
      this.children.splice(index, 1);
      node.parentElement = null;
    }
    return node;
  }

  insertBefore(node, reference) {
    if (node.parentElement) node.parentElement.removeChild(node);
    const index = reference ? this.children.indexOf(reference) : -1;
    if (reference && index < 0) throw new Error("reference node is not a child");
    node.parentElement = this;
    if (index < 0) this.children.push(node);
    else this.children.splice(index, 0, node);
    return node;
  }

  setAttribute() {}
  addEventListener() {}

  querySelectorAll() { return []; }

  querySelector(selector) {
    const matches = (node) => selector.startsWith(".")
      ? String(node.className || "").split(/\s+/).includes(selector.slice(1))
      : node.tagName.toLowerCase() === selector.toLowerCase();
    const pending = [...this.children];
    while (pending.length) {
      const node = pending.shift();
      if (matches(node)) return node;
      pending.unshift(...node.children);
    }
    return null;
  }

  get textContent() {
    return this.children.length
      ? this.children.map((node) => node.textContent).join("")
      : this._text;
  }

  set textContent(value) {
    this._text = String(value ?? "");
    this.children = [];
  }
}

async function makeHarness() {
  const window = {};
  const document = {
    createElement: (tagName) => new Element(tagName),
    createTextNode: (value) => new TextNode(value),
    getElementById: () => new Element("main"),
  };
  const context = { window, document, TextDecoder, TextEncoder, console, URL };
  const transport = await readFile(resolve(root, "chat-transport.js"), "utf8");
  const panel = await readFile(resolve(root, "thought-panel.js"), "utf8");
  const rich = await readFile(resolve(root, "rich-response.js"), "utf8");
  runInNewContext(transport, context);
  runInNewContext(rich, context);
  runInNewContext(panel, context);
  return { window, document };
}

function makeArticle(document) {
  const article = new Element("article");
  const body = new Element("div");
  body.className = "assistant-body";
  const content = new Element("div");
  content.className = "assistant-content";
  article.append(body);
  body.append(content);
  return { article, body, content };
}

function makeStatus(document, className = "capability-kit") {
  const section = new Element("section");
  section.className = className;
  section.dataset.orchestrationUi = "kit";
  return section;
}

function thoughtBody(article) {
  return article.querySelector(".orchestration-thought-body");
}

function fakeSseResponse(text) {
  const bytes = new TextEncoder().encode(text);
  let read = false;
  return {
    body: {
      getReader() {
        return {
          async read() {
            if (read) return { done: true, value: undefined };
            read = true;
            return { done: false, value: bytes };
          },
          async cancel() {},
          releaseLock() {},
        };
      },
    },
  };
}

const labels = {
  activeLabel: "생각 중",
  doneLabel: "생각 과정 보기",
  sanitize: (value) => value,
};

test("fake thought SSE renders a collapsed live panel and settles its label on done", async () => {
  const { window, document } = await makeHarness();
  const { article, body, content } = makeArticle(document);
  const seenDuringStream = [];
  const sse = [
    'event: thought\ndata: {"text":"첫 "}\n\n',
    'event: thought\ndata: {"text":"생각 문장"}\n\n',
    'event: delta\ndata: {"delta":"답"}\n\n',
    'event: done\ndata: {"done":true}\n\n',
  ].join("");

  await window.PadiemChatTransport.readSseEvents(
    fakeSseResponse(sse),
    async (frame) => {
      if (window.PadiemChatThoughtPanel.handleFrame(article, frame, labels)) {
        const details = article.querySelector(".orchestration-thought-summary");
        seenDuringStream.push({
          open: details.open,
          label: details.querySelector("summary").textContent,
          text: thoughtBody(details).textContent,
        });
      }
      if (frame.event === "done") {
        window.PadiemChatThoughtPanel.settle(article, labels.doneLabel);
      }
      return false;
    },
  );

  assert.deepEqual(seenDuringStream, [
    { open: false, label: "생각 중", text: "첫" },
    { open: false, label: "생각 중", text: "첫 생각 문장" },
  ]);
  const details = article.querySelector(".orchestration-thought-summary");
  assert.equal(body.children[0], details);
  assert.equal(body.children[1], content);
  assert.equal(details.open, false);
  assert.equal(details.querySelector("summary").textContent, labels.doneLabel);
  assert.equal(thoughtBody(details).textContent, "첫 생각 문장");
});

test("fake SSE without a thought event does not create a thought panel", async () => {
  const { window, document } = await makeHarness();
  const { article, body } = makeArticle(document);
  const sse = [
    'event: delta\ndata: {"delta":"답"}\n\n',
    'event: done\ndata: {"done":true}\n\n',
  ].join("");

  await window.PadiemChatTransport.readSseEvents(
    fakeSseResponse(sse),
    async (frame) => {
      window.PadiemChatThoughtPanel.handleFrame(article, frame, labels);
      if (frame.event === "done") {
        window.PadiemChatThoughtPanel.settle(article, labels.doneLabel);
      }
      return false;
    },
  );

  assert.equal(article.querySelector(".orchestration-thought-summary"), null);
  assert.equal(body.children.some((node) => node.className === "orchestration-thought-summary"), false);
});

test("work status stays above the thought panel, then the answer", async () => {
  const { window, document } = await makeHarness();
  const { article, body, content } = makeArticle(document);
  const status = makeStatus(document);
  body.insertBefore(status, content);

  window.PadiemChatThoughtPanel.renderSummary(article, "**굵게** 생각합니다.", {
    label: labels.activeLabel,
  });

  assert.deepEqual(
    body.children.map((node) => node.className),
    ["capability-kit", "orchestration-thought-summary", "assistant-content"],
  );
});

test("a later status card is reordered above an existing thought panel", async () => {
  const { window, document } = await makeHarness();
  const { article, body, content } = makeArticle(document);

  window.PadiemChatThoughtPanel.renderSummary(article, "먼저 도착한 생각", {
    label: labels.activeLabel,
  });
  assert.deepEqual(
    body.children.map((node) => node.className),
    ["orchestration-thought-summary", "assistant-content"],
  );

  const status = makeStatus(document);
  body.insertBefore(status, content);
  window.PadiemChatThoughtPanel.reorder(article);

  assert.deepEqual(
    body.children.map((node) => node.className),
    ["capability-kit", "orchestration-thought-summary", "assistant-content"],
  );
});

test("thought markdown uses the answer renderer without injecting HTML", async () => {
  const { window, document } = await makeHarness();
  const { article } = makeArticle(document);

  window.PadiemChatThoughtPanel.renderSummary(
    article,
    '**굵게** _기울임_ `<code>` <img src=x onerror="alert(1)">',
    { label: labels.activeLabel },
  );

  const container = thoughtBody(article);
  assert.equal(container.querySelector("strong").textContent, "굵게");
  assert.equal(container.querySelector("em").textContent, "기울임");
  assert.equal(container.querySelector("code").textContent, "<code>");
  assert.equal(container.querySelector("img"), null);
  assert.ok(container.textContent.includes('<img src=x onerror="alert(1)">'));
  assert.ok(!container.textContent.includes("**굵게**"));
});

test("internal tool identifiers never reach the screen", async () => {
  const { window, document } = await makeHarness();
  const { article } = makeArticle(document);

  window.PadiemChatThoughtPanel.renderSummary(
    article,
    "claw.pc.query_drives 로 드라이브를 확인한 뒤 claw.pc.read_file 을 호출합니다.",
    { label: labels.activeLabel },
  );

  const text = thoughtBody(article).textContent;
  assert.ok(!text.includes("claw.pc.query_drives"));
  assert.ok(!text.includes("claw.pc.read_file"));
  assert.ok(text.includes("[internal tool hidden]"));
  assert.ok(text.includes("드라이브를 확인한 뒤"));
});

test("tool-call names are hidden even when they sit inside a sentence", async () => {
  const { window, document } = await makeHarness();
  const { article } = makeArticle(document);

  const hidden = [
    "claw.pc_shell",
    "claw.pc.query_drives",
    "padiem.drive.read",
    "padiem.xxx",
    "mcp.tools.list",
    "tool.web_search",
  ];
  for (const identifier of hidden) {
    window.PadiemChatThoughtPanel.renderSummary(
      article,
      `도구 ${identifier} 를 실행합니다.`,
      { label: labels.activeLabel },
    );
    const text = thoughtBody(article).textContent;
    assert.ok(!text.includes(identifier), `${identifier} must be hidden`);
    assert.ok(text.includes("[internal tool hidden]"), `${identifier} must be replaced`);
    assert.ok(text.includes("도구"), "surrounding copy stays");
  }
});

test("product domains, URLs and email addresses are never hidden", async () => {
  const { window, document } = await makeHarness();
  const { article } = makeArticle(document);

  const kept = [
    "padiem.net",
    "chat.padiem.net",
    "https://chat.padiem.net/x",
    "http://mcp.example.com/a?b=1",
    "tool.example.com",
    "www.padiem.net",
    "claw.example.org",
    "user@chat.padiem.net",
    "문의는 help@padiem.net 으로 주세요.",
  ];
  for (const address of kept) {
    window.PadiemChatThoughtPanel.renderSummary(
      article,
      address,
      { label: labels.activeLabel },
    );
    const text = thoughtBody(article).textContent;
    assert.equal(text, address);
    assert.ok(!text.includes("[internal tool hidden]"), `${address} must stay visible`);
  }
});

test("the hidden-tool copy follows the active locale", async () => {
  const { window, document } = await makeHarness();
  const { article } = makeArticle(document);
  window.__padiemLocale = {
    text: (key) => (key === "internal-tool-hidden" ? "[내부 도구]" : key),
  };

  window.PadiemChatThoughtPanel.renderSummary(
    article,
    "claw.pc_shell 로 확인합니다.",
    { label: labels.activeLabel },
  );

  const text = thoughtBody(article).textContent;
  assert.ok(!text.includes("claw.pc_shell"));
  assert.ok(text.includes("[내부 도구]"));
  assert.ok(!text.includes("[internal tool hidden]"));
});

test("the hidden-tool placeholder is declared in Korean and English", async () => {
  const locale = await readFile(resolve(root, "locale.js"), "utf8");

  assert.ok(locale.includes('"internal-tool-hidden": "[내부 도구]",'));
  assert.ok(locale.includes('"internal-tool-hidden": "[internal tool hidden]",'));
});

test("#7459: thought_reset folds an open thought panel and replaces aborted thought on retry", async () => {
  const { window, document } = await makeHarness();
  const { article } = makeArticle(document);

  const ndjsonResponse = {
    headers: { get: (name) => (String(name).toLowerCase() === "content-type" ? "application/x-ndjson" : null) },
    body: fakeSseResponse(
      [
        JSON.stringify({ type: "meta", stream: true }),
        JSON.stringify({ type: "thought", text: "1차 후보의 미완성 생각" }),
        JSON.stringify({ type: "thought_reset" }),
        JSON.stringify({ type: "thought", text: "2차 후보의 새 생각" }),
        JSON.stringify({ type: "delta", text: "최종 답변" }),
        JSON.stringify({ type: "done", done: true }),
      ].join("\n") + "\n",
    ).body,
  };

  const foldedSnapshots = [];
  await window.PadiemChatTransport.readSseEvents(ndjsonResponse, async (frame) => {
    if (frame.event === "thought" && !article.querySelector(".orchestration-thought-summary")) {
      window.PadiemChatThoughtPanel.handleFrame(article, frame, labels);
      // 사용자가 스트리밍 도중 생각 패널을 펼쳐 본 상태를 재현
      article.querySelector(".orchestration-thought-summary").open = true;
      return false;
    }
    if (window.PadiemChatThoughtPanel.handleFrame(article, frame, labels)) {
      const details = article.querySelector(".orchestration-thought-summary");
      foldedSnapshots.push({ event: frame.event, open: details.open, text: thoughtBody(details).textContent });
      return false;
    }
    if (frame.event === "done") {
      window.PadiemChatThoughtPanel.settle(article, labels.doneLabel);
    }
    return false;
  });

  assert.equal(foldedSnapshots[0].event, "thought_reset");
  assert.equal(foldedSnapshots[0].open, false);
  const details = article.querySelector(".orchestration-thought-summary");
  assert.equal(details.open, false);
  assert.equal(details.querySelector("summary").textContent, labels.doneLabel);
  assert.equal(thoughtBody(details).textContent, "2차 후보의 새 생각");
});
