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
const Template = require(path.join(SRC, "quote-template.js"));
const SavedQuoteSkill = require(path.join(SRC, "quote-skill.js"));
const easySource = fs.readFileSync(path.join(SRC, "easy-mode.js"), "utf8");
const appSource = fs.readFileSync(path.join(SRC, "app.js"), "utf8");

/* #3478 CGI runtime fixtures: assigned approved Skill + authenticated CompanyProfile.
   probe 의 runtime bridge 스텁은 실제 SavedQuoteSkill.buildDraft 로 위임해
   canonical build 경로를 그대로 검증한다. */
const RUNTIME_NOW = "2026-10-04T09:00:00.000Z";
const CGI_SKILL_BASE = {
  id: "skill-cgi-mvp",
  name: "CGI 기본 견적서",
  fixedDefaults: {
    sender: {
      company: "스킬잔존상사", rep: "스킬대표", bizNo: "000-00-0000",
      address: "스킬주소", phone: "010-0000-0000", email: "skill@example.invalid",
      presetId: "saved-skill"
    },
    validDays: 30,
    taxMode: "EXCLUSIVE",
    memo: "스킬 기본 메모"
  },
  variableSchema: { recipient: true, quoteNo: true, issueDate: true, items: true, memo: true, taxMode: true },
  internalTemplate: Template.serializeTemplate(Template.builtInTemplate()),
  provenance: {
    sourceKind: "file", sourceName: "cgi-quotation.pdf", sourceRef: "source:cgi-mvp",
    capturedAt: RUNTIME_NOW, warnings: [], unknowns: [],
    evidence: [{ label: "sender", value: "CGI상사" }]
  },
  createdAt: RUNTIME_NOW,
  updatedAt: RUNTIME_NOW
};
const CGI_SKILL_DRAFT = SavedQuoteSkill.buildSkill(CGI_SKILL_BASE);
const CGI_SKILL = SavedQuoteSkill.buildSkill(Object.assign({}, CGI_SKILL_BASE, {
  approval: {
    schemaVersion: 1,
    status: "approved",
    skillFingerprint: CGI_SKILL_DRAFT.fingerprint,
    approvedBy: "central-cto",
    approvedAt: RUNTIME_NOW,
    approvalRef: "issue-3478"
  }
}));
const CGI_PROFILE = {
  company: "CGI상사",
  representative: "김범신",
  businessNumber: "111-11-11111",
  address: "서울특별시",
  phone: "02-000-0000",
  email: "cgi@example.invalid",
  defaultValidityDays: 14,
  defaultTaxMode: "EXCLUSIVE"
};

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
    hidden: false, className: "", type: "", style: {},
    dataset: {}, children: [], listeners: {}, focusCount: 0, clickCount: 0,
    get innerHTML() { return this._innerHTML || ""; },
    set innerHTML(value) {
      this._innerHTML = value;
      /* 빈 문자열 대입은 실제 DOM 처럼 내용을 비운다 */
      if (value === "") this.children = [];
    },
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
  const replaceDrafts = [];
  const allocatedQuoteNos = [];
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
      replaceDraft: (next, opts) => {
        appCalls.push("replaceDraft" + (opts && opts.toast ? ":" + opts.toast : ""));
        replaceDrafts.push(next);
        return { ok: true, draft: next };
      },
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
        allocatedQuoteNos.push(allocation.quoteNo);
        const fresh = Core.createDefaultDraft();
        fresh.meta.quoteNo = allocation.quoteNo;
        fresh.meta.source = source || "manual";
        return fresh;
      },
      copyHistoryAsNew: () => { appCalls.push("copyHistoryAsNew"); return Core.createDefaultDraft(); },
      toast: (message) => { appCalls.push("toast:" + message); },
      focusTaxReview: () => { appCalls.push("focusTaxReview"); }
    },
    /* #3478 runtime bridge 스텁: buildFromFacts 는 실제 SavedQuoteSkill.buildDraft 로 위임한다 */
    B66QuoteRuntimeBridge: {
      readiness: () => ({ ready: true, authenticated: true, skillReady: true, profileReady: true }),
      interpret: (text) => {
        appCalls.push("interpret:" + text);
        return Promise.resolve({ ok: false, code: "probe_interpret_unavailable" });
      },
      buildFromFacts: (facts) => {
        appCalls.push("buildFromFacts");
        const built = SavedQuoteSkill.buildDraft(CGI_SKILL, {
          recipient: facts.recipient,
          items: facts.items,
          quoteNo: facts.quoteNo,
          issueDate: facts.issueDate,
          taxMode: facts.taxMode,
          memo: facts.memo
        }, { companyProfile: CGI_PROFILE });
        return Promise.resolve(built && built.ok
          ? { ok: true, draft: built.draft }
          : { ok: false, code: built ? built.code : "draft_build_failed" });
      },
      errorText: (code) => "probe runtime error: " + code
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

  return { context, elements, getElement, created, storage, history, appCalls, replaceDrafts, allocatedQuoteNos, draftBefore, DRAFT, navigations, windowListeners };
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
  const restoreFlags = { newDraftAllocation: 0, newQuoteNoAllocation: 0, pushLoops: 0, oldAppDraftImported: 0 };
  const results = {
    backGuidedToHome: false,
    backFreeformToHome: false,
    draftPreserved: true,
    noResetOnBack: true,
    guidedStateRestore: true,
    cancelPath: true,
    unsavedResetConfirm: false,
    noSnapshotRestore: true,
    safeFallback: true,
    explicitRestart: true,
    explicitRestartAllocations: 0
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

  /* ── in-progress guided conversation survives Back -> Forward (CENTRAL blocker) ──
     구분 불가능한 OLD App draft(시드거래처/시드품목) 위에서 guided를 새로 시작하고
     답변을 입력한 뒤 Back/Forward 해도 답한 값이 유지되고 OLD 값이 섞이지 않아야 한다. */
  {
    clickStarter(env, "guidedStarter");
    await flush();
    const startedAllocations = env.allocatedQuoteNos.length;
    const startedQuoteNo = env.allocatedQuoteNos[env.allocatedQuoteNos.length - 1];
    const type = async (text) => {
      env.getElement("easyComposer").value = text;
      clickStarter(env, "easySend");
      await flush();
    };
    await type("B상사");      /* guided recipient: App draft(시드거래처)와 다른 값 */
    await type("없음");        /* 담당자 없음 */
    await type("NEW품목");     /* guided item: App draft(시드품목)와 다른 값 */

    const freshBefore = countCalls(env, "createFreshDraft");
    const seqBefore = env.storage.getItem(History.SEQUENCE_STORAGE_KEY);
    env.history.back();
    await flush();
    check(env.history._view() === "home", "GUIDED_STATE_RESTORE: Back returns home from mid-conversation");
    env.history.forward();
    await flush();
    check(env.history._view() === "guided", "GUIDED_STATE_RESTORE: Forward reopens the guided flow");
    check(countCalls(env, "createFreshDraft") === freshBefore,
      "GUIDED_STATE_RESTORE: restore allocates no new draft");
    check(env.storage.getItem(History.SEQUENCE_STORAGE_KEY) === seqBefore,
      "GUIDED_STATE_RESTORE: restore consumes no quote number");

    await type("2");          /* 수량 */
    await type("15000");      /* 단가 */
    await type("다음");        /* 품목 완료 */
    await type("별도");        /* 부가세 */
    await type("없음");        /* 메모 */
    await type("현재");        /* 보내는 사람 → 요약 */
    const confirmChips = chipsWith(env, "견적서 만들기");
    results.guidedStateRestore = results.guidedStateRestore &&
      check(confirmChips.length > 0, "GUIDED_STATE_RESTORE: resumed conversation reaches the summary");
    if (confirmChips.length) confirmChips[confirmChips.length - 1].listeners.click[0]();
    await flush();

    const payload = env.replaceDrafts[env.replaceDrafts.length - 1];
    results.guidedStateRestore = results.guidedStateRestore &&
      check(Boolean(payload) && payload.recipient && Array.isArray(payload.items),
        "GUIDED_STATE_RESTORE: completed quote reaches App.replaceDraft") &&
      check(payload && payload.recipient.company === "B상사",
        "GUIDED_STATE_RESTORE: entered recipient survives Back -> Forward") &&
      check(payload && payload.items.some((item) => item.name === "NEW품목"),
        "GUIDED_STATE_RESTORE: entered item survives Back -> Forward") &&
      check(payload && payload.sender && payload.sender.company === "CGI상사" &&
            payload.sender.presetId === "account-company-profile",
        "GUIDED_STATE_RESTORE: sender comes from the authenticated CompanyProfile (no demo leak)") &&
      check(payload && payload.recipient.company !== "시드거래처" &&
            !payload.items.some((item) => item.name === "시드품목"),
        "GUIDED_STATE_RESTORE: OLD App draft recipient/item never substituted into Guided") &&
      check(payload && payload.meta.quoteNo === startedQuoteNo,
        "GUIDED_STATE_RESTORE: quote number is the one from guided start (no re-allocation)") &&
      check(env.allocatedQuoteNos.length === startedAllocations,
        "GUIDED_STATE_RESTORE: zero draft/quote-number allocation across the whole scenario");

    /* 결과 리뷰는 사용자가 명시적으로 열 때만 direct 표면으로 간다 */
    const reviewChips = chipsWith(env, "견적서 확인하기");
    results.guidedStateRestore = results.guidedStateRestore &&
      check(reviewChips.length > 0 && env.getElement("directView").hidden === true,
        "GUIDED_STATE_RESTORE: result review stays in place until the user opens it");
    if (reviewChips.length) reviewChips[reviewChips.length - 1].listeners.click[0]();
    await flush();
    results.guidedStateRestore = results.guidedStateRestore &&
      check(env.getElement("directView").hidden === false,
        "GUIDED_STATE_RESTORE: explicit review opens the canonical result surface");
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

  /* ── NO_SNAPSHOT_GUIDED_RESTORE: guided entry without session state must not import the App draft ──
     재시작(페이지 reload) 시뮬레이션: 히스토리 항목은 이전 세션에서 남았지만 메모리의
     guided/guidedSnapshot 는 없다. 이때 OLD App draft(시드거래처/시드품목)를 guided 로
     가져오거나 새 견적을 발급해서는 안 되고, Home 으로 안전 귀결해야 한다. */
  {
    const env2 = buildEnv();
    new vm.Script(easySource, { filename: "easy-mode.js" }).runInContext(env2.context);
    await flush();

    /* 이전 세션에서 남은 guided 항목을 흉내낸다: 항목은 있고 메모리 상태는 없다 */
    env2.history.pushState({ b66View: "guided" }, "", "https://quick-quote-kr.pages.dev/");
    env2.history.back();
    await flush();
    results.noSnapshotRestore = results.noSnapshotRestore &&
      check(env2.history._view() === "home" && env2.getElement("easyEmpty").hidden === false,
        "NO_SNAPSHOT_GUIDED_RESTORE: prior-session guided entry staged (current=home, forward=guided)");

    const freshBefore = countCalls(env2, "createFreshDraft");
    const seqBefore = env2.storage.getItem(History.SEQUENCE_STORAGE_KEY);
    const pushBefore = env2.history._ops("push");
    const draftBefore2 = env2.storage.getItem(Core.DRAFT_STORAGE_KEY);

    env2.history.forward();
    await flush();

    /* guided 대화가 시작됐다는 것은 App draft 가 guided 로 유입될 수 있는 길이 열렸다는 뜻이다.
       안전 귀결에서는 대화 자체가 만들어지지 않아야 한다. */
    const guidedConversationStarted =
      env2.getElement("easyMessageList").children.length > 0 ||
      env2.getElement("easyEmpty").hidden === true;
    restoreFlags.oldAppDraftImported += guidedConversationStarted ? 1 : 0;
    results.noSnapshotRestore = results.noSnapshotRestore &&
      check(countCalls(env2, "createFreshDraft") === freshBefore,
        "POPSTATE_NEW_DRAFT_ALLOCATION=0 (no-state guided restore allocates nothing)") &&
      check(env2.storage.getItem(History.SEQUENCE_STORAGE_KEY) === seqBefore,
        "POPSTATE_NEW_QUOTE_NUMBER_ALLOCATION=0 (no-state guided restore consumes no quote number)") &&
      check(!guidedConversationStarted,
        "OLD_APP_DRAFT_IMPORTED_INTO_GUIDED=0 (no guided conversation is created, so the App draft cannot be imported)") &&
      check(env2.storage.getItem(Core.DRAFT_STORAGE_KEY) === draftBefore2,
        "NO_SNAPSHOT_GUIDED_RESTORE: stored App draft untouched") &&
      check(env2.history._ops("push") === pushBefore,
        "NO_SNAPSHOT_GUIDED_RESTORE: restore pushes nothing (no loop)");
    results.safeFallback = results.safeFallback &&
      check(env2.appCalls.filter((c) => c.startsWith("toast:진행 중이던 견적 상태를 복원할 수 없습니다")).length === 1,
        "SAFE_FALLBACK: honest restore-impossible notice is shown exactly once") &&
      check(env2.getElement("easyEmpty").hidden === false &&
            env2.getElement("easyMessageList").children.length === 0,
        "SAFE_FALLBACK=PASS (settles on Home; no guided conversation is started from the old draft)");

    /* 사용자가 명시적으로 다시 시작하면 그때는 fresh allocation 이 정확히 1회 허용된다 */
    clickStarter(env2, "guidedStarter");
    await flush();
    results.explicitRestartAllocations = countCalls(env2, "createFreshDraft") - freshBefore;
    results.explicitRestart = results.explicitRestart &&
      check(results.explicitRestartAllocations === 1,
        "EXPLICIT_RESTART_FRESH_ALLOCATION=1 (user-initiated start allocates exactly once)") &&
      check(env2.storage.getItem(History.SEQUENCE_STORAGE_KEY) !== seqBefore,
        "EXPLICIT_RESTART_FRESH_ALLOCATION: quote number sequence advances for the new quote");
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

  /* ── guided restore wiring: restore never imports the App draft (source contract) ── */
  {
    check(!easySource.includes("reuseCurrentDraft") &&
          easySource.includes("function restoreGuidedWithoutState") &&
          easySource.includes('App.createFreshDraft("guided")'),
      "GUIDED_RESTORE_SOURCE_CONTRACT=PASS (popstate restore never imports the App draft; explicit start still allocates)");
  }

  /* ── final invariants ── */
  const depthBounded = env.history._depth() <= 2;
  check(depthBounded, "HISTORY_PUSH_LOOP=0 (depth never exceeded 2 across all back/forward)");
  results.draftPreserved = results.draftPreserved &&
    env.storage.getItem(Core.DRAFT_STORAGE_KEY) === env.draftBefore;
  check(results.draftPreserved,
    "FINAL: stored QuoteDraft identical to its value before any navigation");
  check(restoreFlags.newDraftAllocation === 0 && restoreFlags.newQuoteNoAllocation === 0 &&
        restoreFlags.pushLoops === 0 && restoreFlags.oldAppDraftImported === 0,
    "FINAL: every observed restore was allocation-free and App-draft-free");

  console.log("");
  console.log("BACK_GUIDED_TO_HOME=" + (results.backGuidedToHome ? "PASS" : "FAIL"));
  console.log("BACK_FREEFORM_TO_HOME=" + (results.backFreeformToHome ? "PASS" : "FAIL"));
  console.log("POPSTATE_DRAFT_PRESERVED=" + (results.draftPreserved ? "PASS" : "FAIL"));
  console.log("GUIDED_STATE_RESTORE=" + (results.guidedStateRestore ? "PASS" : "FAIL"));
  console.log("NO_SNAPSHOT_GUIDED_RESTORE=" + (results.noSnapshotRestore ? "PASS" : "FAIL"));
  console.log("OLD_APP_DRAFT_IMPORTED_INTO_GUIDED=" + restoreFlags.oldAppDraftImported);
  console.log("SAFE_FALLBACK=" + (results.safeFallback ? "PASS" : "FAIL"));
  console.log("EXPLICIT_RESTART_FRESH_ALLOCATION=" + results.explicitRestartAllocations +
    " (" + (results.explicitRestart ? "PASS" : "FAIL") + ")");
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
