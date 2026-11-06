import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import { TextDecoder, TextEncoder } from "node:util";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../static");

class Element {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentElement = null;
    this.className = "";
    this.open = false;
    this._text = "";
  }

  append(...nodes) {
    for (const node of nodes) {
      node.parentElement = this;
      this.children.push(node);
    }
  }

  insertBefore(node, reference) {
    const index = this.children.indexOf(reference);
    if (index < 0) throw new Error("reference node is not a child");
    node.parentElement = this;
    this.children.splice(index, 0, node);
    return node;
  }

  querySelector(selector) {
    const matches = (node) => selector.startsWith(".")
      ? node.className.split(/\s+/).includes(selector.slice(1))
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
  const document = { createElement: (tagName) => new Element(tagName) };
  const context = { window, document, TextDecoder, TextEncoder, console };
  const transport = await readFile(resolve(root, "chat-transport.js"), "utf8");
  const panel = await readFile(resolve(root, "thought-panel.js"), "utf8");
  runInNewContext(transport, context);
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
  activeLabel: "생각 중…",
  doneLabel: "생각 과정 보기",
  sanitize: (value) => value,
};

test("fake thought SSE renders a collapsed live panel and settles its label on done", async () => {
  const { window, document } = await makeHarness();
  const { article, body, content } = makeArticle(document);
  const seenDuringStream = [];
  const sse = [
    'event: thought\ndata: {"text":"첫 "}\n\n',
    'event: thought\ndata: {"text":"생각 조각"}\n\n',
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
          text: details.querySelector("p").textContent,
        });
      }
      if (frame.event === "done") {
        window.PadiemChatThoughtPanel.settle(article, labels.doneLabel);
      }
      return false;
    },
  );

  assert.deepEqual(seenDuringStream, [
    { open: false, label: "생각 중…", text: "첫 " },
    { open: false, label: "생각 중…", text: "첫 생각 조각" },
  ]);
  const details = article.querySelector(".orchestration-thought-summary");
  assert.equal(body.children[0], details);
  assert.equal(body.children[1], content);
  assert.equal(details.open, false);
  assert.equal(details.querySelector("summary").textContent, "생각 과정 보기");
  assert.equal(details.querySelector("p").textContent, "첫 생각 조각");
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
