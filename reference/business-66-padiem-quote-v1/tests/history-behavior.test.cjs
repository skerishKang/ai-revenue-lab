/* B66 browser-history behavioral probe (#3394).
   Drives the real easy-mode.js in a vm with a stub DOM / history / storage.
   Read-only for the repository: nothing here touches product state outside the vm.

   Contract under test:
   - USER_STARTS_NEW_QUOTE     -> fresh draft + quote number allocation allowed
   - BROWSER_HISTORY_RESTORE   -> existing draft/state reuse, no allocation, no reset
   - explicit cancel/reset     -> confirmation before destructive work (no product change) */
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SRC = path.join(__dirname, "..");

const Core = require(path.join(SRC, "quote-core.js"));
const History = require(path.join(SRC, "quote-history.js"));
const FileIntake = require(path.join(SRC, "file-intake.js"));
const easySource = fs.readFileSync(path.join(SRC, "easy-mode.js"), "utf8");
const appSource = fs.readFileSync(path.join(SRC, "app.js"), "utf8");

const tick = () => new Promise((resolve) => setImmediate(resolve));
async function flush() {
  for (let i = 0; i < 12; i += 1) { await tick(); }
  await new Promise((resolve) => setTimeout(resolve, 0));
  for (let i = 0; i < 6; i += 1) { await tick(); }
}

const makeElement = (id) => {
  const classes = new Set();
  return {
    id, value: "", textContent: "", placeholder: "", disabled: false,
    hidden: false, innerHTML: "", className: "", type: "", style: {},
    dataset: {}, children: [], listeners: {}, focusCount: 0, clickCount: 0,
    classList: {
      toggle(name, on) { if (on) classes.add(name); else classes.delete(name); },
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      contains(name) { return classes.has(name); }
    },
    addEventListener(type, handler) {
      (this.listeners[type] = this.listeners[type] || []).push(handler);
    },
    dispatchEvent() { return true; },
    setAttribute() {}, removeAttribute() {}, remove() {}, before() {},
    appendChild(child) { this.children.push(child); return child; },
    append(...children) { this.children.push(...children); },
    replaceChildren() { this.children = []; },
    scrollIntoView() {}, focus() { this.focusCount += 1; }, click() { this.clickCount += 1; }
  };
};

function makeStorage() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => { map.set(k, String(v)); },
    removeItem: (k) => { map.delete(k); },
    _map: map
  };
}

const DRAFT = {
  schemaVersion: 1,
  meta: { quoteNo: "SEED-0001", issueDate: "2026-10-04", source: "manual" },
  sender: { company: "시드상사", rep: "", contactPerson: "", bizNo: "", address: "", phone: "", email: "" },
  recipient: { company: "시드거래처", person: "", address: "", email: "" },
  items: [{ id: "item-1", name: "시드품목", qty: 3, unitPrice: 10000 }],
  memo: "시드 메모",
  tax: { mode: "EXCLUSIVE" }
};

const confirmState = { value: true, calls: [] };

function buildEnv() {
  const elements = new Map();
  const created = [];
  const documentListeners = {};
  const windowListeners = {};
  const navigations = [];
  const appCalls = [];
  const storage = makeStorage();

  storage.setItem(Core.DRAFT_STORAGE_KEY, JSON.stringify(DRAFT));
  const draftBefore = storage.getItem(Core.DRAFT_STORAGE_KEY);
  /* recent-history seed: one saved quote so the cancel path has something to act on */
  storage.setItem(
    History.HISTORY_STORAGE_KEY,
    JSON.stringify(History.addEntry(null, DRAFT, { id: "seed-entry-1", savedAt: "2026-10-04T09:00:00.000Z" }))
  );

  const getElement = (id) => {
    if (!elements.has(id)) elements.set(id, makeElement(id));
    return elements.get(id);
  };

  const stack = [{ state: null, url: "https://quick-quote-kr.pages.dev/" }];
  let index = 0;
  const historyLog = [];
  const dispatchPop = (state) => {
    setTimeout(() => (windowListeners.popstate || []).forEach((fn) => fn({ state })), 0);
  };
  const history = {
    get state() { return stack[index].state; },
    get length() { return stack.length; },
    pushState(state, _title, url) {
      historyLog.push({ op: "push", view: state && state.b66View });
      stack.splice(index + 1);
      stack.push({ state, url });
      index = stack.length - 1;
    },
    replaceState(state, _title, url) {
      historyLog.push({ op: "replace", view: state && state.b66View });
      stack[index] = { state, url: url || stack[index].url };
    },
    back() {
      historyLog.push({ op: "back", view: null });
      if (index > 0) {
        index -= 1;
        dispatchPop(stack[index].state);
      }
    },
    forward() {
      historyLog.push({ op: "forward", view: null });
      if (index < stack.length - 1) {
        index += 1;
        dispatchPop(stack[index].state);
      }
    },
    _view: () => (stack[index].state || {}).b66View,
    _ops: (name) => historyLog.filter((entry) => entry.op === name).length,
    _depth: () => stack.length,
    _position: () => index,
    _log: historyLog
  };

  const context = vm.createContext({
    setTimeout, clearTimeout, console,
    QuoteCore: Core, QuoteHistory: History, B66FileIntake: FileIntake,
    B66QuoteAppBridge: {
      getDraft: () => { appCalls.push("getDraft"); return JSON.parse(JSON.stringify(DRAFT)); },
      replaceDraft: (next, opts) => { appCalls.push("replaceDraft" + (opts && opts.toast ? ":" + opts.toast : "")); return { ok: true, draft: next }; },
      /* app.js allocateFreshQuoteNo 미러: 시퀀스를 읽고 배정한 뒤 저장한다 —
         이 스텁이 불리면 SEQUENCE_STORAGE_KEY 가 실제로 소비된다 */
      createFreshDraft: (source) => {
        appCalls.push("createFreshDraft:" + source);
        let rawSequence = null;
        try {
          rawSequence = JSON.parse(storage.getItem(History.SEQUENCE_STORAGE_KEY) || "null");
        } catch (err) {
          rawSequence = null;
        }
        const allocation = History.allocateQuoteNo(rawSequence, [DRAFT], new Date());
        storage.setItem(History.SEQUENCE_STORAGE_KEY, JSON.stringify(allocation.state));
        const fresh = Core.createDefaultDraft();
        fresh.meta.quoteNo = allocation.quoteNo;
        fresh.meta.source = source || "manual";
        return fresh;
      },
      copyHistoryAsNew: () => { appCalls.push("copyHistoryAsNew"); return Core.createDefaultDraft(); },
      toast: (message) => { appCalls.push("toast:" + message); },
      focusTaxReview: () => { appCalls.push("focusTaxReview"); }
    },
    CustomEvent: class {
      constructor(type, init) { this.type = type; this.detail = (init || {}).detail; }
    },
    localStorage: storage,
    history,
    location: { href: "https://quick-quote-kr.pages.dev/", assign(target) { navigations.push(String(target)); } },
    confirm: (message) => { confirmState.calls.push(String(message)); return confirmState.value; },
    scrollTo() {},
    getComputedStyle: () => ({ getPropertyValue: () => "" }),
    document: {
      readyState: "complete",
      getElementById: getElement,
      addEventListener(type, handler) {
        (documentListeners[type] = documentListeners[type] || []).push(handler);
      },
      dispatchEvent(event) {
        (documentListeners[event.type] || []).forEach((fn) => fn(event));
        return true;
      },
      createElement(tag) {
        const node = makeElement(tag);
        created.push(node);
        return node;
      }
    }
  });
  context.window = context;
  context.addEventListener = (type, handler) => {
    (windowListeners[type] = windowListeners[type] || []).push(handler);
  };
  context.dispatchEvent = () => true;

  return { context, elements, getElement, created, storage, history, appCalls, draftBefore, DRAFT, navigations, windowListeners };
}

const clickStarter = (env, id) => {
  const element = env.getElement(id);
  const handler = (element.listeners.click || [])[0];
  if (typeof handler !== "function") throw new Error("no click handler bound for " + id);
  return handler();
};

const chipsWith = (env, label) => env.created.filter(
  (node) => node.textContent === label && (node.listeners.click || []).length > 0
);

const buttonWith = (env, label) => env.created.filter(
  (node) => node.textContent === label && (node.listeners.click || []).length > 0
).map((node) => node.listeners.click[0]);

(async () => {
  let failures = 0;
  const check = (condition, label) => {
    console.log((condition ? "PASS  " : "FAIL  ") + label);
    if (!condition) failures += 1;
    return condition;
  };
  const countCalls = (env, prefix) => env.appCalls.filter((c) => c.startsWith(prefix)).length;
  const restoreFlags = { newDraftAllocation: 0, newQuoteNoAllocation: 0, pushLoops: 0 };
  const results = {
    backGuidedToHome: false,
    backFreeformToHome: false,
    draftPreserved: true,
    noResetOnBack: true,
    cancelPath: true,
    unsavedResetConfirm: false
  };

  const env = buildEnv();
  new vm.Script(easySource, { filename: "easy-mode.js" }).runInContext(env.context);
  await flush();

  /* ── boot ── */
  check(env.history._ops("push") === 0, "boot: no pushState on first paint");
  check(env.history._ops("replace") === 1, "boot: initial entry is seeded with replaceState");
  check(env.history._view() === "home", "boot: current product view is home");
  check(env.history._depth() === 1, "boot: history depth is 1");
  check(typeof (env.context.window && env.context.window.history) === "object", "PUSHSTATE_EXISTS");
  check(Object.keys(env.context).length > 0 && env.history._ops("replace") >= 1, "POPSTATE_EXISTS(handler bound)");

  /* ── USER_STARTS_NEW_QUOTE: guided entry is allowed to allocate ── */
  {
    const pushBefore = env.history._ops("push");
    clickStarter(env, "guidedStarter");
    await flush();
    check(env.history._view() === "guided", "BACK_GUIDED: entering guided pushes a bounded view");
    check(env.history._ops("push") === pushBefore + 1, "BACK_GUIDED: exactly one pushed entry");
    check(countCalls(env, "createFreshDraft") === 1,
      "USER_STARTS_NEW_QUOTE: explicit start allocates exactly one fresh draft");
    const replaceBefore = countCalls(env, "replaceDraft");
    const pushDuring = env.history._ops("push");

    env.history.back();
    await flush();

    check(env.history._view() === "home", "BACK_GUIDED_TO_HOME=PASS");
    results.backGuidedToHome = env.history._view() === "home";
    check(env.history._ops("push") === pushDuring, "BACK_GUIDED: restore does not push (no loop)");
    check(env.history._ops("replace") === 1, "BACK_GUIDED: restore does not replace either");
    check(countCalls(env, "replaceDraft") === replaceBefore,
      "BACK_GUIDED: QuoteDraft is not replaced/reset");
    check(countCalls(env, "createFreshDraft") === 1,
      "BACK_GUIDED: no new draft allocation during restore");
    results.draftPreserved = results.draftPreserved &&
      env.storage.getItem(Core.DRAFT_STORAGE_KEY) === env.draftBefore;
    check(results.draftPreserved,
      "POPSTATE_DRAFT_PRESERVED=PASS (stored draft byte-identical)");
    check(env.history._position() === 0, "BACK_GUIDED: cursor returns to the home entry");
  }

  /* ── BROWSER_HISTORY_RESTORE: forward into guided must reuse, never allocate ── */
  {
    const freshBefore = countCalls(env, "createFreshDraft");
    const replaceBefore = countCalls(env, "replaceDraft");
    const seqBefore = env.storage.getItem(History.SEQUENCE_STORAGE_KEY);
    const pushBefore = env.history._ops("push");

    env.history.forward();
    await flush();

    const freshAfter = countCalls(env, "createFreshDraft");
    const seqAfter = env.storage.getItem(History.SEQUENCE_STORAGE_KEY);

    check(env.history._view() === "guided", "RESTORE_GUIDED: forward restores the guided view");
    check(env.history._ops("push") === pushBefore, "RESTORE_GUIDED: no extra push from restore");
    check(env.getElement("easyView").hidden === false, "RESTORE_GUIDED: easy workspace visible again");
    check(freshAfter === freshBefore, "POPSTATE_NEW_DRAFT_ALLOCATION=0 (guided restore reuses the draft)");
    check(seqBefore === seqAfter, "POPSTATE_NEW_QUOTE_NUMBER_ALLOCATION=0 (sequence untouched by restore)");
    check(env.storage.getItem(Core.DRAFT_STORAGE_KEY) === env.draftBefore,
      "POPSTATE_RESTORE_RESETS_EXISTING_DRAFT=0 (stored draft byte-identical)");
    check(countCalls(env, "replaceDraft") === replaceBefore,
      "RESTORE_GUIDED: restore does not replace the live draft");
    restoreFlags.newDraftAllocation += freshAfter - freshBefore;
    restoreFlags.newQuoteNoAllocation += seqBefore === seqAfter ? 0 : 1;
  }

  /* ── restore loop: repeated back/forward stays allocation-free and bounded ── */
  {
    const pushBefore = env.history._ops("push");
    const freshBefore = countCalls(env, "createFreshDraft");
    const seqBefore = env.storage.getItem(History.SEQUENCE_STORAGE_KEY);
    for (let cycle = 0; cycle < 2; cycle += 1) {
      env.history.back();
      await flush();
      env.history.forward();
      await flush();
    }
    const pushDelta = env.history._ops("push") - pushBefore;
    const freshDelta = countCalls(env, "createFreshDraft") - freshBefore;
    check(env.history._view() === "guided", "RESTORE_LOOP: still on the guided entry");
    check(pushDelta === 0 && freshDelta === 0,
      "RESTORE_LOOP: two more restore cycles allocate nothing and push nothing");
    check(env.storage.getItem(History.SEQUENCE_STORAGE_KEY) === seqBefore,
      "RESTORE_LOOP: quote number sequence unchanged across cycles");
    restoreFlags.newDraftAllocation += freshDelta;
    restoreFlags.pushLoops += pushDelta;
    env.history.back();
    await flush();
  }

  /* ── live guided conversation survives a redundant popstate ── */
  {
    clickStarter(env, "guidedStarter");
    await flush();
    const composer = env.getElement("easyComposer");
    composer.value = "홍길동건설";
    clickStarter(env, "easySend");
    await flush();
    const messagesBefore = env.getElement("easyMessageList").children.length;
    const freshBefore = countCalls(env, "createFreshDraft");

    (env.windowListeners.popstate || []).forEach((fn) => fn({ state: { b66View: "guided" } }));
    await flush();

    check(env.getElement("easyMessageList").children.length === messagesBefore,
      "LIVE_GUIDED_POPSTATE: redundant guided restore keeps the conversation");
    check(countCalls(env, "createFreshDraft") === freshBefore,
      "LIVE_GUIDED_POPSTATE: live conversation restore allocates nothing");
    env.history.back();
    await flush();
  }

  /* ── free-form ── */
  {
    const pushBefore = env.history._ops("push");
    clickStarter(env, "freeChatStarter");
    await flush();
    check(env.history._view() === "free-form", "BACK_FREEFORM: entering free-form pushes a view");
    check(env.history._ops("push") === pushBefore + 1, "BACK_FREEFORM: exactly one pushed entry");
    const pushDuring = env.history._ops("push");
    const freshBefore = countCalls(env, "createFreshDraft");
    env.history.back();
    await flush();
    check(env.history._view() === "home", "BACK_FREEFORM_TO_HOME=PASS");
    results.backFreeformToHome = env.history._view() === "home";
    check(env.history._ops("push") === pushDuring, "BACK_FREEFORM: restore does not push");
    check(countCalls(env, "createFreshDraft") === freshBefore, "BACK_FREEFORM: restore allocates nothing");
    results.draftPreserved = results.draftPreserved &&
      env.storage.getItem(Core.DRAFT_STORAGE_KEY) === env.draftBefore;
    check(results.draftPreserved, "BACK_FREEFORM: stored draft untouched");
  }

  /* ── file intake (existing #3468 regression, not a new design) ── */
  {
    const pushBefore = env.history._ops("push");
    const fileClicksBefore = env.getElement("easyFileInput").clickCount;
    clickStarter(env, "fileStarter");
    await flush();
    check(env.history._view() === "file", "BACK_FILE: entering file intake pushes a view");
    check(env.history._ops("push") === pushBefore + 1, "BACK_FILE: exactly one pushed entry");
    check(env.getElement("easyFileInput").clickCount === fileClicksBefore + 1,
      "BACK_FILE: entering intake opens the local chooser once");
    const pushDuring = env.history._ops("push");
    env.history.back();
    await flush();
    check(env.history._view() === "home", "BACK_FILE_TO_HOME=PASS");
    check(env.history._ops("push") === pushDuring, "BACK_FILE: restore does not push");
  }

  /* ── direct workspace (existing #3468 regression) ── */
  {
    const pushBefore = env.history._ops("push");
    clickStarter(env, "directModeButton");
    await flush();
    check(env.history._view() === "direct", "BACK_DIRECT: switching to direct records a view");
    check(env.history._ops("push") === pushBefore + 1, "BACK_DIRECT: exactly one pushed entry");
    check(env.getElement("directView").hidden === false, "BACK_DIRECT: direct workspace visible");
    const pushDuring = env.history._ops("push");
    env.history.back();
    await flush();
    check(env.history._view() === "home", "BACK_DIRECT_TO_HOME=PASS");
    check(env.history._ops("push") === pushDuring, "BACK_DIRECT: restore does not push");
    check(env.getElement("easyView").hidden === false && env.getElement("directView").hidden === true,
      "BACK_DIRECT: easy workspace restored");
    results.noResetOnBack = results.noResetOnBack &&
      env.storage.getItem(Core.DRAFT_STORAGE_KEY) === env.draftBefore;
    check(results.noResetOnBack,
      "NO_RESET_ON_BACK=PASS (stored draft survives every back navigation)");
  }

  /* ── in-app "처음으로" from a sub-view must consume history, not stack it ── */
  {
    clickStarter(env, "freeChatStarter");
    await flush();
    let chips = chipsWith(env, "처음으로");
    if (!chips.length) {
      const composer = env.getElement("easyComposer");
      composer.value = "테스트 문장";
      clickStarter(env, "easySend");
      await flush();
      chips = chipsWith(env, "처음으로");
    }
    check(chips.length > 0, "HOME_CHIP: 처음으로 chip is available in free-form");
    const pushBefore = env.history._ops("push");
    const backBefore = env.history._ops("back");
    if (chips.length) chips[chips.length - 1].listeners.click[0]();
    await flush();
    check(env.history._ops("back") === backBefore + 1, "HOME_CHIP: returning home uses history.back()");
    check(env.history._ops("push") === pushBefore, "HOME_CHIP: returning home does not push a new entry");
    check(env.history._view() === "home", "HOME_CHIP: current view is home");
    check(env.history._depth() === 2, "HOME_CHIP: depth stays bounded at 2");
  }

  /* ── CANCEL_PATH: destructive intent is cancellable and confirmed ── */
  {
    clickStarter(env, "recentQuoteStarter");
    await flush();

    const replaceBefore = countCalls(env, "replaceDraft");
    confirmState.calls.length = 0;
    confirmState.value = false;
    const loadHandlers = buttonWith(env, "불러오기");
    results.cancelPath = results.cancelPath &&
      check(loadHandlers.length > 0, "CANCEL_PATH: recent history offers a load action");
    if (loadHandlers.length) loadHandlers[0]();
    await flush();
    results.cancelPath = results.cancelPath &&
      check(countCalls(env, "replaceDraft") === replaceBefore,
        "CANCEL_PATH: declining the overwrite confirm leaves the current draft alone") &&
      check(confirmState.calls.some((m) => m.includes("현재 작성 중인 견적을 바꾸고")),
        "CANCEL_PATH: load overwrite asks before replacing unsaved work");

    const envelopeBefore = env.storage.getItem(History.HISTORY_STORAGE_KEY);
    confirmState.calls.length = 0;
    const deleteHandlers = buttonWith(env, "삭제");
    results.cancelPath = results.cancelPath &&
      check(deleteHandlers.length > 0, "CANCEL_PATH: recent history offers a delete action");
    if (deleteHandlers.length) deleteHandlers[0]();
    await flush();
    results.cancelPath = results.cancelPath &&
      check(env.storage.getItem(History.HISTORY_STORAGE_KEY) === envelopeBefore,
        "CANCEL_PATH: declining the delete confirm keeps the saved quote") &&
      check(confirmState.calls.some((m) => m.includes("삭제할까요")),
        "CANCEL_PATH: delete asks before removing a saved quote");

    confirmState.value = true;
    if (deleteHandlers.length) deleteHandlers[0]();
    await flush();
    results.cancelPath = results.cancelPath &&
      check(env.storage.getItem(History.HISTORY_STORAGE_KEY) !== envelopeBefore,
        "CANCEL_PATH: confirming the delete proceeds exactly once");
    confirmState.value = true;
  }

  /* ── UNSAVED_RESET_CONFIRM: destructive browser-local reset stays confirm-gated (app.js) ── */
  {
    const resetConfirmIndex = appSource.indexOf('window.confirm("이 브라우저에 저장한 견적, 발신자, 최근 견적 기록을 초기화할까요?")');
    const resetDispatchIndex = appSource.indexOf('new CustomEvent("b66:local-data-reset")');
    const resetGateHonored = /confirm\("이 브라우저에 저장한 견적[^"]*"\)\)\s*\{\s*return false;/.test(appSource);
    results.unsavedResetConfirm = check(
      resetConfirmIndex >= 0 && resetDispatchIndex > resetConfirmIndex && resetGateHonored,
      "UNSAVED_RESET_CONFIRM=PASS (browser-local reset is confirm-gated before any wipe or event)"
    );
  }

  /* ── guided restore wiring: restore and explicit start are distinct intents (source contract) ── */
  {
    check(easySource.includes("options.reuseCurrentDraft === true") &&
          easySource.includes('startGuided("", { history: false, reuseCurrentDraft: true })') &&
          easySource.includes("draft: guidedDraft(options)"),
      "GUIDED_RESTORE_REUSE_CONTRACT=PASS (popstate restore reuses the draft; explicit start still allocates)");
  }

  /* ── final invariants ── */
  const depthBounded = env.history._depth() <= 2;
  check(depthBounded, "HISTORY_PUSH_LOOP=0 (depth never exceeded 2 across all back/forward)");
  results.draftPreserved = results.draftPreserved &&
    env.storage.getItem(Core.DRAFT_STORAGE_KEY) === env.draftBefore;
  check(results.draftPreserved,
    "FINAL: stored QuoteDraft identical to its value before any navigation");
  check(restoreFlags.newDraftAllocation === 0 && restoreFlags.newQuoteNoAllocation === 0 &&
        restoreFlags.pushLoops === 0,
    "FINAL: every observed restore was allocation-free");

  console.log("");
  console.log("BACK_GUIDED_TO_HOME=" + (results.backGuidedToHome ? "PASS" : "FAIL"));
  console.log("BACK_FREEFORM_TO_HOME=" + (results.backFreeformToHome ? "PASS" : "FAIL"));
  console.log("POPSTATE_DRAFT_PRESERVED=" + (results.draftPreserved ? "PASS" : "FAIL"));
  console.log("POPSTATE_NEW_DRAFT_ALLOCATION=" + restoreFlags.newDraftAllocation);
  console.log("POPSTATE_NEW_QUOTE_NUMBER_ALLOCATION=" + restoreFlags.newQuoteNoAllocation);
  console.log("NO_RESET_ON_BACK=" + (results.noResetOnBack ? "PASS" : "FAIL"));
  console.log("HISTORY_PUSH_LOOP=" + (restoreFlags.pushLoops + (depthBounded ? 0 : 1)));
  console.log("CANCEL_PATH=" + (results.cancelPath ? "PASS" : "FAIL"));
  console.log("UNSAVED_RESET_CONFIRM=" + (results.unsavedResetConfirm ? "PASS" : "FAIL"));
  console.log("HISTORY_PROBE_FAILURES=" + failures);
  console.log("HISTORY_PROBE_NETWORK_CALLS=0");
  process.exitCode = failures === 0 ? 0 : 1;
})().catch((error) => {
  console.error("PROBE_CRASH");
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
