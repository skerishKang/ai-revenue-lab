/* #4657: B66 customer dialogue UX — new chat, previous-dialogue rail, restore
   and assistant Markdown. Drives the real easy-mode.js in a vm with a stub DOM.
   No network, credential or Production action happens here.

   Contract under test:
   - BRAND_NEW_CHAT        the header brand starts a new empty conversation and
                           never deletes a stored dialogue
   - PREVIOUS_LIST         the rail lists/opens/searches only through the
                           owner- and B66-scoped runtime bridge
   - RESTORE_CONTINUE      opening a stored dialogue restores it and the next
                           turn continues the SAME server-owned conversation id
   - ASSISTANT_MARKDOWN    only a real model answer is rendered as Markdown,
                           through the DOM-only renderer, with no markup sink
   - ACCOUNT_SWITCH        a late answer from the previous owner renders nothing
   - QUOTE_INDEPENDENCE    the dialogue rail never touches the saved-quote list
*/
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const SRC = path.join(__dirname, "..");
const Core = require(path.join(SRC, "quote-core.js"));
const History = require(path.join(SRC, "quote-history.js"));
const FileIntake = require(path.join(SRC, "file-intake.js"));
const SafeMarkdown = require(path.join(SRC, "b66-safe-markdown.js"));
const easySource = fs.readFileSync(path.join(SRC, "easy-mode.js"), "utf8");
const htmlSource = fs.readFileSync(path.join(SRC, "index.html"), "utf8");

const DIALOGUE_A = "chat_" + "a".repeat(32);
const DIALOGUE_B = "chat_" + "b".repeat(32);

const tick = () => new Promise((resolve) => setImmediate(resolve));
async function flush() {
  for (let i = 0; i < 12; i += 1) await tick();
  await new Promise((resolve) => setTimeout(resolve, 0));
  for (let i = 0; i < 6; i += 1) await tick();
}

function makeElement(tag, doc, register) {
  const listeners = {};
  let idValue = "";
  const node = {
    nodeType: 1, tagName: String(tag).toUpperCase(), children: [],
    listeners, textContent: "", value: "", placeholder: "", disabled: false,
    hidden: false, className: "", type: "", style: {}, dataset: {},
    maxLength: 0, autocomplete: "", scrollTop: 0, scrollHeight: 0,
    clientHeight: 0, ownerDocument: doc, focusCount: 0, _innerHTML: "",
    /* A dynamically created element joins the id lookup, exactly as the real
       document does, so the module's `$("id")` finds what it just appended. */
    get id() { return idValue; },
    set id(value) { idValue = String(value || ""); if (idValue && register) register(idValue, node); },
    get innerHTML() { return this._innerHTML; },
    set innerHTML(value) { this._innerHTML = value; if (value === "") this.children = []; },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener(type, handler) { (listeners[type] = listeners[type] || []).push(handler); },
    removeEventListener() {}, dispatchEvent() { return true; },
    setAttribute(name, value) { this[name] = value; }, removeAttribute() {},
    appendChild(child) { this.children.push(child); return child; },
    append(...items) { this.children.push(...items); },
    before() {}, remove() {}, replaceChildren(...items) { this.children = items; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    scrollIntoView() {}, focus() { this.focusCount += 1; }, click() {}
  };
  return node;
}

function descendants(node, out) {
  const found = out || [];
  (node.children || []).forEach((child) => {
    found.push(child);
    descendants(child, found);
  });
  return found;
}

function buildEnv(options) {
  const opts = options || {};
  const created = [];
  const elements = new Map();
  const documentListeners = {};
  const calls = { chat: [], listDialogues: [], loadDialogue: [], deleteDialogue: [], recent: 0, toast: [] };
  let doc = null;
  const registerElement = (id, node) => { elements.set(id, node); };
  doc = {
    readyState: "complete",
    getElementById(id) {
      if (!elements.has(id)) {
        const el = makeElement("div", doc, registerElement);
        el.id = id;
      }
      return elements.get(id);
    },
    createElement(tag) {
      const el = makeElement(tag, doc, registerElement);
      created.push(el);
      return el;
    },
    createTextNode(text) { return { nodeType: 3, textContent: String(text), children: [] }; },
    createDocumentFragment() { return makeElement("#fragment", doc, registerElement); },
    addEventListener(type, handler) { (documentListeners[type] = documentListeners[type] || []).push(handler); },
    dispatchEvent(event) { (documentListeners[event.type] || []).forEach((fn) => fn(event)); return true; },
    documentElement: { lang: "ko" }
  };

  const historyState = {
    state: {},
    replaceState(state) { this.state = Object.assign({}, state); },
    pushState(state) { this.state = Object.assign({}, state); },
    back() {}
  };

  const bridge = {
    /* A signed-in account with no assigned CGI Skill: exactly the B66 AI
       dialogue case, so the free-form message goes to the model. */
    readiness: () => ({ ready: false, authenticated: true, skillReady: false, profileReady: false }),
    interpret: () => Promise.resolve({ ok: false, code: "probe_interpret_unavailable" }),
    chat: (messages, chatOptions) => {
      calls.chat.push({ messages, options: chatOptions || null });
      if (typeof opts.chat === "function") return opts.chat(messages, chatOptions || {});
      return Promise.resolve(opts.chatResult || { ok: true, answer: "기본 답변", conversation_id: null });
    },
    listDialogues: (query) => {
      calls.listDialogues.push(query);
      return opts.listDialogues
        ? opts.listDialogues(query)
        : Promise.resolve({ ok: true, conversations: [] });
    },
    loadDialogue: (id) => {
      calls.loadDialogue.push(id);
      return opts.loadDialogue
        ? opts.loadDialogue(id)
        : Promise.resolve({ ok: false, code: "conversation_not_found" });
    },
    deleteDialogue: (id) => {
      calls.deleteDialogue.push(id);
      return Promise.resolve(opts.deleteResult || { ok: true });
    }
  };

  const appBridge = {
    getDraft: () => Core.createDefaultDraft(),
    privateStateReadable: () => true,
    getHistoryEnvelope: () => History.normalizeEnvelope(null),
    writeHistoryEnvelope: () => true,
    replaceDraft: () => ({ ok: true }),
    createFreshDraft: () => Core.createDefaultDraft(),
    copyHistoryAsNew: () => Core.createDefaultDraft(),
    toast: (message) => { calls.toast.push(String(message)); },
    focusTaxReview: () => {},
    listRecentQuotes: () => {
      calls.recent += 1;
      return Promise.resolve({ ok: true, authority: "server", envelope: History.normalizeEnvelope(null) });
    },
    recentListAuthority: () => "server"
  };

  const context = vm.createContext({
    setTimeout, clearTimeout, console, Promise,
    QuoteCore: Core, QuoteHistory: History, B66FileIntake: FileIntake,
    B66SafeMarkdown: SafeMarkdown,
    B66QuoteAppBridge: appBridge,
    B66QuoteRuntimeBridge: bridge,
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = (init || {}).detail; } },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    history: historyState,
    location: { href: "https://quick-quote-kr.pages.dev/" },
    confirm: () => true,
    scrollTo() {},
    getComputedStyle: () => ({ getPropertyValue: () => "" }),
    document: doc
  });
  context.window = context;
  context.addEventListener = () => {};
  context.dispatchEvent = () => true;

  vm.runInContext(easySource, context, { filename: "easy-mode.js" });

  return {
    context, doc, elements, created, calls, historyState,
    get: (id) => elements.get(id),
    click: (id) => {
      const el = elements.get(id);
      const handler = el && (el.listeners.click || [])[0];
      if (typeof handler !== "function") throw new Error("no click handler for " + id);
      return handler();
    },
    fireDocument: (type, detail) => (documentListeners[type] || []).forEach((fn) => fn({ type, detail })),
    messageArticles: () => elements.get("easyMessageList").children,
    lastContent: () => {
      const articles = elements.get("easyMessageList").children;
      for (let i = articles.length - 1; i >= 0; i -= 1) {
        const content = descendants(articles[i]).filter((n) => n.className === "easy-message-content");
        if (content.length) return content[0];
      }
      return null;
    }
  };
}

async function ask(env, text) {
  const composer = env.get("easyComposer");
  composer.value = text;
  const send = env.get("easySend");
  const handler = (send.listeners.click || [])[0];
  handler();
  await flush();
}

/* ── static contract ─────────────────────────────────────────────────────── */
function testStaticSurface() {
  assert.ok(htmlSource.includes('id="brandHome"'),
    "the header brand must be a real interactive element");
  assert.ok(/<button class="brand-home" id="brandHome" type="button"/.test(htmlSource),
    "the brand must be a keyboard-accessible button");
  assert.ok(htmlSource.includes('id="aiDialogueStarter"') &&
    htmlSource.includes("<strong>이전 AI 대화</strong>"),
    "the home grid must offer an explicit previous-AI-dialogue entry");
  assert.ok(htmlSource.indexOf("b66-safe-markdown.js") < htmlSource.indexOf("easy-mode.js"),
    "the safe Markdown renderer must load before easy-mode");
  assert.ok(easySource.includes('$("brandHome").addEventListener("click", () => showHome());'),
    "the brand must start a new conversation");
  assert.ok(easySource.includes("function showAiDialogues(") &&
    easySource.includes("function openAiDialogue(") &&
    easySource.includes("function deleteAiDialogue("),
    "the previous-dialogue rail must be implemented");
  // No markup sink for any dialogue text: every innerHTML assignment clears.
  const assignments = easySource.match(/\.innerHTML\s*=\s*[^;]+;/g) || [];
  assert.ok(assignments.length > 0, "the module clears panels via innerHTML");
  assignments.forEach((line) => {
    assert.ok(/\.innerHTML\s*=\s*"";/.test(line), "unsafe innerHTML assignment: " + line);
  });
  console.log("B66_DIALOGUE_UX_STATIC=PASS");
}

/* ── new chat ────────────────────────────────────────────────────────────── */
async function testBrandStartsANewChatWithoutDeleting() {
  const env = buildEnv({
    chatResult: { ok: true, answer: "**첫 답변**", conversation_id: DIALOGUE_A }
  });
  await ask(env, "첫 질문");
  assert.equal(env.calls.chat.length, 1);
  assert.equal(env.calls.chat[0].options.conversationId, null,
    "a new chat must not name a conversation id");

  env.click("brandHome");
  assert.equal(env.get("easyMessageList").children.length, 0,
    "the brand must clear the transcript for a new conversation");
  assert.equal(env.calls.deleteDialogue.length, 0,
    "the brand must never delete a stored dialogue");

  await ask(env, "두 번째 질문");
  assert.equal(env.calls.chat.length, 2);
  assert.equal(env.calls.chat[1].options.conversationId, null,
    "a new conversation after the brand click must not continue the old one");
  console.log("B66_BRAND_NEW_CHAT=PASS");
}

/* ── previous list / search / states ─────────────────────────────────────── */
async function testPreviousDialogueRailListsSearchesAndOpens() {
  const env = buildEnv({
    listDialogues: () => Promise.resolve({
      ok: true,
      conversations: [
        { conversation_id: DIALOGUE_A, title: "철근 견적", updated_at: "2026-10-14T01:00:00Z" },
        { conversation_id: DIALOGUE_B, title: "배관 견적", updated_at: "2026-10-13T01:00:00Z" }
      ]
    }),
    loadDialogue: () => Promise.resolve({
      ok: true,
      conversation: {
        conversation_id: DIALOGUE_A,
        title: "철근 견적",
        messages: [
          { role: "user", content: "철근 견적 알려줘" },
          { role: "assistant", content: "**네**, 알려드릴게요" }
        ]
      }
    })
  });
  env.click("aiDialogueStarter");
  await flush();
  assert.deepEqual(env.calls.listDialogues, [""], "opening the rail lists the owner's dialogue");
  assert.equal(env.calls.recent, 0, "the dialogue rail must not read the saved-quote list");

  const results = env.get("easyDialogueResults");
  const cards = results.children.filter((n) => String(n.className).includes("easy-dialogue-card"));
  assert.equal(cards.length, 2, "both stored dialogues must be listed");

  // Search is bounded and reaches the bridge as a plain query string.
  const search = env.get("easyDialogueSearch");
  search.value = "철근";
  (search.listeners.input || [])[0]();
  await new Promise((resolve) => setTimeout(resolve, 320));
  await flush();
  assert.equal(env.calls.listDialogues[env.calls.listDialogues.length - 1], "철근",
    "a typed query must reach the bridge");
  assert.equal(env.calls.recent, 0, "searching dialogue must not touch the quote list");

  // Open restores the stored transcript through the bridge.
  env.click("aiDialogueStarter");
  await flush();
  const openButton = descendants(env.get("easyDialogueResults"))
    .find((n) => n.textContent === "이어서 대화" && (n.listeners.click || []).length);
  assert.ok(openButton, "each listed dialogue must offer an open action");
  openButton.listeners.click[0]();
  await flush();
  assert.deepEqual(env.calls.loadDialogue, [DIALOGUE_A], "opening loads the chosen id");
  assert.equal(env.calls.recent, 0, "restoring dialogue must not touch the quote list");

  const restored = env.get("easyMessageList").children;
  assert.equal(restored.length, 2, "the stored transcript must be restored");
  const content = env.lastContent();
  const strong = descendants(content).filter((n) => n.tagName === "STRONG");
  assert.equal(strong.length, 1, "a restored assistant answer is Markdown-rendered");
  assert.equal(strong[0].textContent, "네");
  console.log("B66_PREVIOUS_DIALOGUE_RAIL=PASS");
}

async function testRailRendersLoadingEmptyAndErrorStates() {
  const empty = buildEnv({ listDialogues: () => Promise.resolve({ ok: true, conversations: [] }) });
  empty.click("aiDialogueStarter");
  await flush();
  const emptyNote = descendants(empty.get("easyDialogueResults"))
    .find((n) => n.className === "easy-history-empty");
  assert.ok(emptyNote && emptyNote.textContent.includes("아직 저장된 AI 대화가 없습니다"),
    "an empty rail must say so");

  let failing = true;
  const error = buildEnv({
    listDialogues: () => Promise.resolve(failing
      ? { ok: false, code: "dialogue_history_unavailable" }
      : { ok: true, conversations: [] })
  });
  error.click("aiDialogueStarter");
  await flush();
  const errorHost = error.get("easyDialogueResults");
  const errorNote = descendants(errorHost).find((n) => n.className === "easy-history-empty");
  assert.ok(errorNote && errorNote.textContent.includes("불러오지 못했습니다"),
    "a failed rail must show a bounded error");
  const retry = descendants(errorHost).find((n) => n.textContent === "다시 시도");
  assert.ok(retry, "a failed rail must offer a retry");
  failing = false;
  retry.listeners.click[0]();
  await flush();
  assert.ok(descendants(error.get("easyDialogueResults"))
    .some((n) => n.textContent.includes("아직 저장된 AI 대화가 없습니다")),
    "retry must re-read the rail");
  console.log("B66_RAIL_STATES=PASS");
}

/* ── restore then continue the SAME conversation ─────────────────────────── */
async function testRestoredDialogueContinuesTheSameConversation() {
  const env = buildEnv({
    chatResult: { ok: true, answer: "이어쓴 답변", conversation_id: DIALOGUE_A },
    listDialogues: () => Promise.resolve({
      ok: true,
      conversations: [{ conversation_id: DIALOGUE_A, title: "철근 견적", updated_at: "2026-10-14T01:00:00Z" }]
    }),
    loadDialogue: () => Promise.resolve({
      ok: true,
      conversation: {
        conversation_id: DIALOGUE_A,
        messages: [{ role: "user", content: "원래 질문" }, { role: "assistant", content: "원래 답변" }]
      }
    })
  });
  env.click("aiDialogueStarter");
  await flush();
  const open = descendants(env.get("easyDialogueResults"))
    .find((n) => n.textContent === "이어서 대화" && (n.listeners.click || []).length);
  assert.ok(open, "the listed dialogue must be openable");
  open.listeners.click[0]();
  await flush();
  assert.deepEqual(env.calls.loadDialogue, [DIALOGUE_A]);

  await ask(env, "이어서 질문");
  assert.equal(env.calls.chat.length, 1);
  assert.equal(env.calls.chat[0].options.conversationId, DIALOGUE_A,
    "a continued turn must carry the restored server-owned conversation id");
  assert.equal(env.calls.chat[0].messages[env.calls.chat[0].messages.length - 1].content, "이어서 질문");
  console.log("B66_RESTORE_CONTINUE=PASS");
}

/* ── assistant Markdown ──────────────────────────────────────────────────── */
async function testAssistantMarkdownIsRenderedWithoutAMarkupSink() {
  const env = buildEnv({
    chatResult: {
      ok: true,
      answer: "1. **한 번에 설명하기**\n2. 질문에 답하며 작성하기\n\n<img src=x onerror=alert(1)>\n<script>alert(2)</script>",
      conversation_id: DIALOGUE_A
    }
  });
  await ask(env, "설명해줘");
  const content = env.lastContent();
  assert.ok(content, "an assistant answer must render");
  const nodes = descendants(content);
  const strong = nodes.filter((n) => n.tagName === "STRONG").map((n) => n.textContent);
  assert.deepEqual(strong, ["한 번에 설명하기"], "paired ** must become <strong>");
  const items = nodes.filter((n) => n.className === "b66-md-item");
  assert.equal(items.length, 2, "two numbered steps must render as two list items");
  assert.ok(nodes.some((n) => n.textContent.includes("<img src=x onerror=alert(1)>")),
    "model HTML must stay literal text");
  assert.ok(!nodes.some((n) => n.tagName === "IMG"), "no image element may be created");
  assert.ok(!nodes.some((n) => n.tagName === "SCRIPT"), "no script element may be created");

  // The user's own turn stays plain text, never Markdown.
  const userArticle = env.get("easyMessageList").children[0];
  const bubble = descendants(userArticle).find((n) => n.className === "easy-message-bubble");
  assert.ok(bubble && bubble.children.length === 0, "a user bubble keeps plain textContent");
  console.log("B66_ASSISTANT_MARKDOWN=PASS");
}

/* ── account switch drops the previous owner's dialogue ──────────────────── */
async function testAccountSwitchDropsThePreviousOwnersDialogue() {
  let resolveList = null;
  const env = buildEnv({
    listDialogues: () => new Promise((resolve) => { resolveList = resolve; })
  });
  env.click("aiDialogueStarter");
  await flush();
  // The account boundary changes while the previous owner's read is in flight.
  env.fireDocument("b66:account-scope-changed", { privateStateReadable: false, action: null });
  resolveList({
    ok: true,
    conversations: [{ conversation_id: DIALOGUE_A, title: "이전 소유자 대화", updated_at: "x" }]
  });
  await flush();
  const leaked = descendants(env.get("easyDialogueResults") || makeElement("div", env.doc))
    .some((n) => n.textContent.includes("이전 소유자 대화"));
  assert.ok(!leaked, "a late answer from the previous owner must not render");
  assert.equal(env.get("easyMessageList").children.length, 0,
    "the account switch must clear the transcript");
  console.log("B66_DIALOGUE_ACCOUNT_SWITCH=PASS");
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

/* #4657 P0-B: a restore that resolves after the customer pressed new chat must
   not overwrite the new chat. */
async function testALateRestoreCannotOverwriteANewChat() {
  const gate = deferred();
  const env = buildEnv({
    listDialogues: () => Promise.resolve({
      ok: true,
      conversations: [{ conversation_id: DIALOGUE_A, title: "철근 견적", updated_at: "2026-10-14T01:00:00Z" }]
    }),
    loadDialogue: (id) => gate.promise.then(() => ({
      ok: true,
      conversation: {
        conversation_id: id,
        messages: [{ role: "user", content: "원래 질문" }, { role: "assistant", content: "**원래** 답변" }]
      }
    }))
  });
  env.click("aiDialogueStarter");
  await flush();
  const open = descendants(env.get("easyDialogueResults"))
    .find((n) => n.textContent === "이어서 대화" && (n.listeners.click || []).length);
  assert.ok(open, "the listed dialogue must be openable");
  open.listeners.click[0]();
  await flush();
  assert.deepEqual(env.calls.loadDialogue, [DIALOGUE_A]);

  // New chat while the restore read is still in flight.
  env.click("brandHome");
  await flush();
  assert.equal(env.get("easyMessageList").children.length, 0, "new chat clears the transcript");

  gate.resolve();
  await flush();
  assert.equal(env.get("easyMessageList").children.length, 0,
    "a late restore must not repopulate the new chat");
  console.log("B66_LATE_RESTORE_NEW_CHAT=PASS");
}

/* #4657 P0-B: the same for a late restore *rejection*. */
async function testALateRestoreRejectionCannotOverwriteANewChat() {
  const gate = deferred();
  const env = buildEnv({
    listDialogues: () => Promise.resolve({
      ok: true,
      conversations: [{ conversation_id: DIALOGUE_A, title: "철근 견적", updated_at: "x" }]
    }),
    loadDialogue: () => gate.promise.then(() => { throw new Error("restore failed"); })
  });
  env.click("aiDialogueStarter");
  await flush();
  const open = descendants(env.get("easyDialogueResults"))
    .find((n) => n.textContent === "이어서 대화" && (n.listeners.click || []).length);
  open.listeners.click[0]();
  await flush();

  env.click("brandHome");
  await flush();
  gate.resolve();
  await flush();
  assert.equal(env.get("easyMessageList").children.length, 0,
    "a late restore rejection must not paint an error into the new chat");
  console.log("B66_LATE_RESTORE_REJECTION_NEW_CHAT=PASS");
}

/* #4657 P0-B: navigating into a non-dialogue mode also discards a late restore. */
async function testALateRestoreCannotOverwriteADirectQuietMode() {
  const gate = deferred();
  const env = buildEnv({
    listDialogues: () => Promise.resolve({
      ok: true,
      conversations: [{ conversation_id: DIALOGUE_A, title: "철근 견적", updated_at: "x" }]
    }),
    loadDialogue: () => gate.promise.then(() => ({
      ok: true,
      conversation: { conversation_id: DIALOGUE_A, messages: [{"role": "user", "content": "늦은 질문"}] }
    }))
  });
  env.click("aiDialogueStarter");
  await flush();
  const open = descendants(env.get("easyDialogueResults"))
    .find((n) => n.textContent === "이어서 대화" && (n.listeners.click || []).length);
  open.listeners.click[0]();
  await flush();

  env.click("directModeButton");
  await flush();
  gate.resolve();
  await flush();
  const nodes = descendants(env.get("easyMessageList"));
  assert.ok(!nodes.some((n) => n.textContent.includes("늦은 질문")),
    "a late restore must not land in the direct-quote view");
  console.log("B66_LATE_RESTORE_DIRECT_MODE=PASS");
}

/* #4657 P0-C: an in-flight model answer may not repopulate a new chat. */
async function testAnInFlightAnswerCannotRepopulateANewChat() {
  const gate = deferred();
  const env = buildEnv({
    chat: () => gate.promise.then(() => ({
      ok: true,
      answer: "**늦은 답변**",
      conversation_id: DIALOGUE_A,
      dialogue_saved: true
    }))
  });
  env.click("freeChatStarter");
  const composer = env.get("easyComposer");
  composer.value = "첫 질문";
  (env.get("easySend").listeners.click || [])[0]();
  await flush();
  assert.equal(env.calls.chat.length, 1);
  assert.ok(descendants(env.get("easyMessageList")).some((n) => n.textContent.includes("답변을 작성하고 있습니다")),
    "the pending notice must be visible while the model runs");
  const inFlight = env.get("easyMessageList").children.length;

  // New chat while the model answer is still in flight.
  env.click("brandHome");
  await flush();
  const cleared = env.get("easyMessageList").children.length;
  gate.resolve();
  await flush();

  assert.equal(cleared, 0);
  assert.equal(env.get("easyMessageList").children.length, 0,
    "a late answer must not repopulate the new chat");
  const nodes = descendants(env.get("easyMessageList"));
  assert.ok(!nodes.some((n) => n.textContent.includes("늦은 답변")),
    "no late answer text may appear");
  assert.ok(!nodes.some((n) => n.textContent.includes("답변을 작성하고 있습니다")),
    "no late pending notice may appear");
  assert.equal(env.get("easyComposerNote").textContent, "",
    "a late answer must not install the unsaved notice either");
  // A follow-up must start a brand-new conversation, not the old one.
  env.click("freeChatStarter");
  const next = env.get("easyComposer");
  next.value = "다음 질문";
  (env.get("easySend").listeners.click || [])[0]();
  await flush();
  assert.equal(env.calls.chat[1].options.conversationId, null,
    "the next turn must not wear the discarded conversation id");
  console.log("B66_INFLIGHT_ANSWER_NEW_CHAT=PASS");
}

/* #4657 P1 honesty: an answer the server could not save is labelled as such. */
async function testAnUnsavedAnswerIsLabelled() {
  const env = buildEnv({
    chatResult: { ok: true, answer: "저장 실패 답변", conversation_id: null, dialogue_saved: false }
  });
  env.click("freeChatStarter");
  const composer = env.get("easyComposer");
  composer.value = "질문";
  (env.get("easySend").listeners.click || [])[0]();
  await flush();
  const note = env.get("easyComposerNote").textContent;
  assert.ok(note.includes("저장되지 않았습니다"),
    "an unsaved answer must be reported as unsaved");
  console.log("B66_UNSAVED_ANSWER_HONESTY=PASS");
}

/* #4657 P0-C: the accepted one-shot CGI path is guarded the same way. */
async function testAnInFlightCgiResultCannotRepopulateANewChat() {
  const gate = deferred();
  const env = buildEnv();
  env.context.window.B66QuoteRuntimeBridge.readiness =
    () => ({ ready: true, authenticated: true, skillReady: true, profileReady: true });
  env.context.window.B66QuoteRuntimeBridge.interpret = () =>
    gate.promise.then(() => ({ ok: true, draft: env.context.QuoteCore.createDefaultDraft() }));
  const composer = env.get("easyComposer");
  composer.value = "대한건설 배관 100미터";
  (env.get("easySend").listeners.click || [])[0]();
  await flush();

  env.click("brandHome");
  await flush();
  gate.resolve();
  await flush();
  assert.equal(env.get("easyMessageList").children.length, 0,
    "a late one-shot CGI result must not repopulate the new chat");
  console.log("B66_LATE_CGI_RESULT_NEW_CHAT=PASS");
}

(async () => {
  testStaticSurface();
  await testBrandStartsANewChatWithoutDeleting();
  await testPreviousDialogueRailListsSearchesAndOpens();
  await testRailRendersLoadingEmptyAndErrorStates();
  await testRestoredDialogueContinuesTheSameConversation();
  await testAssistantMarkdownIsRenderedWithoutAMarkupSink();
  await testAccountSwitchDropsThePreviousOwnersDialogue();
  await testALateRestoreCannotOverwriteANewChat();
  await testALateRestoreRejectionCannotOverwriteANewChat();
  await testALateRestoreCannotOverwriteADirectQuietMode();
  await testAnInFlightAnswerCannotRepopulateANewChat();
  await testAnUnsavedAnswerIsLabelled();
  await testAnInFlightCgiResultCannotRepopulateANewChat();
  console.log("B66_DIALOGUE_UX_RUNTIME=PASS");
  console.log("PRODUCTION_MUTATION=0");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
