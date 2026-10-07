/* #3480 B66 browser-local account isolation.
   Synthetic accounts only: usr_A / usr_B. No real identity, no production call. */

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.join(__dirname, "..");
const Scope = require(path.join(ROOT, "quote-account-scope.js"));
const Core = require(path.join(ROOT, "quote-core.js"));
const History = require(path.join(ROOT, "quote-history.js"));
const TemplateStore = require(path.join(ROOT, "quote-template-store.js"));
const TemplateSelection = require(path.join(ROOT, "quote-template-selection.js"));
const SkillStore = require(path.join(ROOT, "quote-skill-store.js"));

const OWNER_A = "usr_A";
const OWNER_B = "usr_B";
const TAX_REVIEW_KEY = "quoteBeta.taxReview.v1";
const PRIVATE_KEYS = Scope.privateKeys({
  Core,
  History,
  taxReviewKey: TAX_REVIEW_KEY,
  TemplateStore,
  TemplateSelection,
  SkillStore
});

const read = (name) => fs.readFileSync(path.join(ROOT, name), "utf8");

function makeStorage(seed) {
  const map = new Map(Object.entries(seed || {}));
  return {
    map,
    getItem(key) { return map.has(key) ? map.get(key) : null; },
    setItem(key, value) { map.set(key, String(value)); },
    removeItem(key) { map.delete(key); }
  };
}

const A_DRAFT = JSON.stringify(Core.normalizeDraft({
  schemaVersion: 1,
  meta: { quoteNo: "PQ-20260101-004" },
  sender: { company: "A회사", rep: "A대표" },
  recipient: { company: "A거래처", person: "A담당자" },
  items: [{ id: "item-1", name: "A 품목", qty: 7, unitPrice: 4242000 }],
  memo: "A 비밀 메모"
}));
const A_HISTORY = JSON.stringify(History.normalizeEnvelope({
  schemaVersion: 1,
  entries: [{ id: "quote-a", savedAt: "2026-01-01T00:00:00.000Z", draft: JSON.parse(A_DRAFT) }]
}));
const A_SEQUENCE = JSON.stringify({ schemaVersion: 1, date: "2026-01-01", lastSequence: 4 });
const A_TAX_REVIEW = JSON.stringify({ schemaVersion: 1, quoteNo: "PQ-20260101-004", required: true });

function accountAFixture() {
  return {
    [Core.DRAFT_STORAGE_KEY]: A_DRAFT,
    [Core.SENDER_STORAGE_KEY]: JSON.stringify({ company: "A회사", rep: "A대표" }),
    [History.HISTORY_STORAGE_KEY]: A_HISTORY,
    [History.SEQUENCE_STORAGE_KEY]: A_SEQUENCE,
    [TAX_REVIEW_KEY]: A_TAX_REVIEW,
    [TemplateStore.TEMPLATE_STORAGE_KEY]: JSON.stringify({ company: "A회사" }),
    [TemplateSelection.SELECTION_STORAGE_KEY]: JSON.stringify({
      schemaVersion: 1,
      selections: [{ quoteNo: "PQ-20260101-004", templateId: "tpl_A" }]
    }),
    [SkillStore.STORAGE_KEY]: JSON.stringify({
      schemaVersion: 1,
      defaultSkillId: null,
      skills: [{ id: "b66skill_A", name: "A 내 견적서" }]
    })
  };
}

const storedBlob = (storage) => JSON.stringify(Array.from(storage.map.entries()));

/* ── localStorage inventory ──────────────────────────────────────────────── */

assert.deepEqual(PRIVATE_KEYS, [
  "quoteBeta.draft.v1",
  "quoteBeta.sender",
  "quoteBeta.history.v1",
  "quoteBeta.quoteNoSequence.v1",
  "quoteBeta.taxReview.v1",
  "quoteBetaTemplate.v1",
  "quoteBetaTemplateSelection.v1",
  "quoteBetaSavedSkill.v1"
], "every B66 browser-local key is enumerated from the owning module constants");
assert.equal(new Set(PRIVATE_KEYS).size, PRIVATE_KEYS.length, "private key list has no duplicates");
assert.ok(!PRIVATE_KEYS.includes(Scope.OWNER_STORAGE_KEY), "owner marker is not one of the private quote keys");

/* ── owner marker derivation ─────────────────────────────────────────────── */

const markerA = Scope.deriveOwnerMarker(OWNER_A);
const markerB = Scope.deriveOwnerMarker(OWNER_B);
assert.match(markerA, Scope.OWNER_MARKER_PATTERN, "marker is the bounded qb1 digest shape");
assert.equal(markerA.length, 36, "marker length is bounded");
assert.notEqual(markerA, markerB, "distinct canonical ids produce distinct markers");
assert.ok(!markerA.includes(OWNER_A), "marker never contains the raw user id");
assert.ok(!markerA.includes("@"), "marker never looks like an email");
assert.equal(Scope.deriveOwnerMarker(OWNER_A), markerA, "marker derivation is deterministic");
assert.equal(Scope.deriveOwnerMarker(""), null, "empty owner id is rejected");
assert.equal(Scope.deriveOwnerMarker("   "), null, "whitespace-only owner id is rejected");
assert.equal(Scope.deriveOwnerMarker("a b"), null, "owner id with inner whitespace is rejected");
assert.equal(Scope.deriveOwnerMarker("x".repeat(201)), null, "over-long owner id is rejected");
assert.ok(Scope.deriveOwnerMarker("550e8400-e29b-41d4-a716-446655440000"), "opaque uuid id is accepted");
assert.equal(Scope.normalizeOwnerId("display name"), null, "display name with spaces is not an opaque id");

/* ── signed-out denies every private read ────────────────────────────────── */

{
  const storage = makeStorage({ ...accountAFixture(), [Scope.OWNER_STORAGE_KEY]: markerA });
  const result = Scope.applyAccountScope(storage, { authenticated: false, userId: null }, PRIVATE_KEYS);
  assert.equal(result.privateStateReadable, false, "signed-out state is never readable");
  assert.equal(Scope.privateStateReadable(), false, "module gate denies private reads while signed out");
  assert.equal(result.action, Scope.SCOPE_ACTIONS.SIGNED_OUT, "signed-out action is explicit");
  assert.equal(result.marker, markerA, "owner marker survives logout for a possible same-account resume");
  assert.equal(storage.getItem(Core.DRAFT_STORAGE_KEY), A_DRAFT, "same-account bytes are retained, not rendered");
  assert.equal(storage.getItem(History.HISTORY_STORAGE_KEY), A_HISTORY, "same-account history is retained");
  assert.equal(Scope.privateStateReadable(), false, "retained bytes are unreachable through the gate");
}

/* ── owner bound on first canonical sign-in (same-account UX preserved) ─── */

{
  const storage = makeStorage(accountAFixture());
  const result = Scope.applyAccountScope(storage, { authenticated: true, userId: OWNER_A }, PRIVATE_KEYS);
  assert.equal(result.action, Scope.SCOPE_ACTIONS.OWNER_BOUND, "first sign-in binds existing local state");
  assert.equal(result.privateStateReadable, true, "owner-bound state is readable for its owner");
  assert.equal(storage.getItem(Scope.OWNER_STORAGE_KEY), markerA, "marker written from canonical id only");
  assert.equal(storage.getItem(Core.DRAFT_STORAGE_KEY), A_DRAFT, "A keeps its own draft on first sign-in");
}

/* ── same-account resume ─────────────────────────────────────────────────── */

{
  const storage = makeStorage({ ...accountAFixture(), [Scope.OWNER_STORAGE_KEY]: markerA });
  const result = Scope.applyAccountScope(storage, { authenticated: true, userId: OWNER_A }, PRIVATE_KEYS);
  assert.equal(result.action, Scope.SCOPE_ACTIONS.SAME_ACCOUNT_RESUME, "SAME_ACCOUNT_SAFE_RESUME=PASS");
  assert.equal(storage.getItem(Core.DRAFT_STORAGE_KEY), A_DRAFT, "A resumes its own draft");
  assert.equal(storage.getItem(History.HISTORY_STORAGE_KEY), A_HISTORY, "A resumes its own history");
  assert.equal(storage.getItem(History.SEQUENCE_STORAGE_KEY), A_SEQUENCE, "A resumes its own sequence");
}

/* ── foreign account quarantines every private key ───────────────────────── */

{
  const storage = makeStorage({ ...accountAFixture(), [Scope.OWNER_STORAGE_KEY]: markerA });
  const result = Scope.applyAccountScope(storage, { authenticated: true, userId: OWNER_B }, PRIVATE_KEYS);
  assert.equal(result.action, Scope.SCOPE_ACTIONS.QUARANTINED_FOREIGN_OWNER, "DIFFERENT_ACCOUNT_STATE_REUSE=DENIED_OR_CLEARED");
  assert.equal(result.privateStateReadable, true, "B reads only its own fresh state");
  assert.equal(storage.getItem(Scope.OWNER_STORAGE_KEY), markerB, "marker rebound to the canonical B id");
  PRIVATE_KEYS.forEach((key) => {
    assert.equal(storage.getItem(key), null, "B cannot read or reuse A state at " + key);
  });
  ["A거래처", "A 품목", "A 비밀", "A회사", "tpl_A", "b66skill_A"].forEach((secret) => {
    assert.ok(!storedBlob(storage).includes(secret), "A fact never survives the switch: " + secret);
  });
}

/* ── malformed marker fails closed ───────────────────────────────────────── */

[
  { name: "malformed marker", marker: "qb1:NOT-A-DIGEST" },
  { name: "truncated marker", marker: "qb1:ab" },
  { name: "oversized marker", marker: "qb1:" + "a".repeat(4096) },
  { name: "raw user id as marker", marker: OWNER_B },
  { name: "html marker", marker: "<script>usr_B</script>" },
  { name: "raw session token as marker", marker: "padiem_session=opaque-token" }
].forEach((entry) => {
  const storage = makeStorage({ ...accountAFixture(), [Scope.OWNER_STORAGE_KEY]: entry.marker });
  const result = Scope.applyAccountScope(storage, { authenticated: true, userId: OWNER_B }, PRIVATE_KEYS);
  assert.equal(result.action, Scope.SCOPE_ACTIONS.QUARANTINED_MALFORMED_OWNER, entry.name + " fails closed");
  PRIVATE_KEYS.forEach((key) => {
    assert.equal(storage.getItem(key), null, entry.name + " drops private state at " + key);
  });
  assert.equal(storage.getItem(Scope.OWNER_STORAGE_KEY), markerB, entry.name + " rebinds to canonical B");
});

/* ── authenticated but unusable owner id never exposes private state ────── */

["", "   ", null, undefined, 42, {}, "a b", "x".repeat(201)].forEach((badId) => {
  const storage = makeStorage({ ...accountAFixture(), [Scope.OWNER_STORAGE_KEY]: markerA });
  const result = Scope.applyAccountScope(storage, { authenticated: true, userId: badId }, PRIVATE_KEYS);
  assert.equal(result.privateStateReadable, false, "unusable owner id is never readable: " + JSON.stringify(badId));
  assert.equal(result.action, Scope.SCOPE_ACTIONS.OWNER_UNUSABLE, "unusable owner id action is explicit");
  assert.equal(storage.getItem(Scope.OWNER_STORAGE_KEY), markerA, "unusable owner id leaves the binding untouched");
});

/* ── storage absence / failure fails closed ─────────────────────────────── */

{
  const blocked = {
    getItem() { throw new Error("storage blocked"); },
    setItem() { throw new Error("storage blocked"); },
    removeItem() { throw new Error("storage blocked"); }
  };
  const result = Scope.applyAccountScope(blocked, { authenticated: true, userId: OWNER_A }, PRIVATE_KEYS);
  assert.equal(result.privateStateReadable, false, "blocked storage never yields readable private state");
  assert.equal(
    Scope.applyAccountScope(null, { authenticated: true, userId: OWNER_A }, PRIVATE_KEYS).ok,
    false,
    "missing storage object is rejected"
  );
  assert.equal(Scope.privateStateReadable(), false, "module gate closes again");
}

/* ── credential / token hygiene across the whole stored surface ──────────── */

{
  const storage = makeStorage(accountAFixture());
  Scope.applyAccountScope(storage, { authenticated: true, userId: OWNER_A }, PRIVATE_KEYS);
  const blob = storedBlob(storage);
  [OWNER_A, OWNER_B, "padiem_session", "session_token", "access_token", "refresh_token",
    "password", "passwd", "Authorization", "Bearer", "Set-Cookie", "cookie"].forEach((needle) => {
    assert.ok(!blob.includes(needle), "RAW_CREDENTIAL_IN_LOCAL_STORAGE=0 for " + needle);
  });
  const marker = storage.getItem(Scope.OWNER_STORAGE_KEY);
  assert.ok(marker && marker.length <= Scope.MAX_MARKER_CHARS, "stored owner marker stays bounded");
  assert.equal(storage.map.size, PRIVATE_KEYS.length + 1,
    "only the private payload and the single owner marker exist");
}

console.log("B66_ACCOUNT_SCOPE_3480_UNIT=PASS");
console.log("ACCOUNT_A_LOCAL_DRAFT_VISIBLE_TO_A=YES");
console.log("ACCOUNT_A_LOCAL_HISTORY_VISIBLE_TO_A=YES");
console.log("LOGOUT_PRIVATE_QUOTE_VISIBLE=0");
console.log("ACCOUNT_B_SEES_A_DRAFT=0");
console.log("ACCOUNT_B_SEES_A_HISTORY=0");
console.log("ACCOUNT_B_REUSES_A_SEQUENCE=0");
console.log("ACCOUNT_B_REUSES_A_TAX_REVIEW=0");
console.log("SAME_ACCOUNT_RESUME=PASS");
console.log("DIFFERENT_ACCOUNT_STATE_REUSE=DENIED_OR_CLEARED");
console.log("OWNER_MARKER_FAILS_CLOSED=YES");
console.log("RAW_USER_ID_RENDERED_OR_LOGGED=0");
console.log("RAW_CREDENTIAL_IN_LOCAL_STORAGE=0");
console.log("RAW_SESSION_TOKEN_IN_LOCAL_STORAGE=0");
console.log("B66_PRIVATE_STORAGE_KEYS=" + PRIVATE_KEYS.length);

/* ═══════════════════════════════════════════════════════════════════════════
   Runtime seam: canonical /auth/status -> app bridge -> owner scope, including
   the truthful logout path. padiem-account.js runs in an isolated vm context.
   ═══════════════════════════════════════════════════════════════════════════ */

const accountSource = read("padiem-account.js");
const appSource = read("app.js");
const easySource = read("easy-mode.js");
const indexHtml = read("index.html");

function buildRuntime(seed, options) {
  const opts = options || {};
  const storage = makeStorage(seed);
  const scopes = [];
  const authEvents = [];
  const quoteStatuses = [];
  const toasts = [];
  const skillCleared = [];
  const listeners = new Map();

  const element = (id) => Object.assign(created(), {
    id,
    options: [],
    addEventListener(type, fn) {
      const key = id + ":" + type;
      listeners.set(key, (listeners.get(key) || []).concat([fn]));
    },
    replaceChildren() {},
    querySelector() { return null; },
    scrollIntoView() {},
    focus() {},
    getAttribute() { return null; },
    removeAttribute() {},
    async click() {
      const handlers = listeners.get(id + ":click") || [];
      for (const fn of handlers) await fn({ preventDefault() {} });
    },
    async submit() {
      const handlers = listeners.get(id + ":submit") || [];
      for (const fn of handlers) await fn({ preventDefault() {} });
    }
  });

  const nodes = new Map();
  const getElement = (id) => {
    if (!nodes.has(id)) nodes.set(id, element(id));
    return nodes.get(id);
  };

  let canonicalUser = opts.canonicalUser || null;
  let logoutNetworkFails = Boolean(opts.logoutNetworkFails);
  let logoutKeepsSession = Boolean(opts.logoutKeepsSession);
  let statusUnavailable = Boolean(opts.statusUnavailable);
  const logoutPosts = [];

  const respond = (body, ok) => ({ ok, status: ok ? 200 : 500, json: async () => body });

  const fetchStub = async (url, init) => {
    const target = String(url);
    if (target.endsWith("/auth/status")) {
      if (statusUnavailable) return respond(null, false);
      if (canonicalUser) {
        return respond({
          authenticated: true,
          session_state: "signed_in",
          user: { id: canonicalUser, name: "Synthetic" },
          methods: { google: true, password: true }
        }, true);
      }
      return respond({ authenticated: false, session_state: "signed_out", methods: { google: true, password: true } }, true);
    }
    if (target.endsWith("/auth/password/login")) {
      /* the server decides the identity; the browser never names an owner */
      const body = JSON.parse(String((init && init.body) || "{}"));
      canonicalUser = String(body.identifier || "");
      return respond({ ok: true, user: { id: canonicalUser } }, true);
    }
    if (target.endsWith("/auth/logout")) {
      logoutPosts.push(true);
      if (logoutNetworkFails) throw new Error("network down");
      if (!logoutKeepsSession) canonicalUser = null;
      return respond({ ok: true }, true);
    }
    if (target.endsWith("/b66/saved-skills?limit=20")) return respond({ ok: true, skills: [] }, true);
    if (target.endsWith("/b66/company-profile")) {
      return respond({ company_profile: { company: "Synthetic Co" } }, true);
    }
    throw new Error("unexpected upstream: " + target);
  };

  class CustomEventStub {
    constructor(type, init) {
      this.type = type;
      this.detail = (init || {}).detail || null;
    }
  }

  const created = () => ({
    value: "",
    textContent: "",
    dataset: {},
    disabled: false,
    hidden: false,
    append() {},
    prepend() {},
    remove() {},
    addEventListener() {},
    setAttribute() {},
    getAttribute() { return null; }
  });

  const document = {
    readyState: "complete",
    getElementById: getElement,
    createElement: created,
    dispatchEvent(event) {
      if (event.type === "b66:account-scope-changed") scopes.push(event.detail);
      if (event.type === "b66:auth-changed") authEvents.push(event.detail);
    },
    addEventListener() {}
  };

  const context = vm.createContext({
    console,
    setTimeout,
    clearTimeout,
    Promise,
    URL,
    CustomEvent: CustomEventStub,
    document,
    fetch: fetchStub
  });
  context.window = context;
  context.self = context;
  context.globalThis = context;
  context.location = { assign() {} };
  context.QuoteCore = Core;
  context.QuoteHistory = History;
  context.QuoteAccountScope = Scope;
  context.localStorage = storage;

  /* server-assigned Saved Quote Skill projection lives in app.js memory. */
  context.B66QuoteSkillBridge = {
    setServerSkill() { return true; },
    clearServerSkill() { skillCleared.push(true); return true; }
  };

  /* app.js is the single browser-storage authority; the seam mirrors only that boundary. */
  context.B66QuoteAppBridge = {
    applyOwnerScope(projection) {
      const result = Scope.applyAccountScope(storage, projection, PRIVATE_KEYS);
      scopes.push({
        authenticated: result.authenticated === true,
        privateStateReadable: result.privateStateReadable === true,
        action: result.action || null
      });
      return result;
    },
    toast(message) { toasts.push(message); }
  };

  vm.runInContext(accountSource, context, { filename: "padiem-account.js" });

  const originalQuoteStatus = document.getElementById("padiemQuoteStatus").textContent;

  return {
    storage,
    scopes,
    authEvents,
    quoteStatuses,
    toasts,
    skillCleared,
    logoutPosts,
    element: getElement,
    async signIn(id) {
      getElement("padiemLoginIdentifier").value = id;
      getElement("padiemLoginPassword").value = "synthetic-secret-not-a-real-credential";
      await getElement("padiemLoginForm").submit();
    },
    keepSessionOnLogout(value) { logoutKeepsSession = value; },
    failLogoutNetwork(value) { logoutNetworkFails = value; },
    makeStatusUnavailable(value) { statusUnavailable = value; },
    lastScope: () => scopes[scopes.length - 1],
    quoteStatusText: () => getElement("padiemQuoteStatus").textContent,
    accountButtonText: () => getElement("padiemAccountButton").textContent,
    originalQuoteStatus
  };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

(async () => {
  /* A. Account A signs in on a browser that already holds local B66 state. */
  {
    const runtime = buildRuntime(accountAFixture(), { canonicalUser: OWNER_A });
    await settle();
    assert.equal(runtime.lastScope().action, Scope.SCOPE_ACTIONS.OWNER_BOUND, "A binds its legacy local state");
    assert.equal(runtime.lastScope().privateStateReadable, true, "A may read its own private state");
    assert.equal(runtime.authEvents[runtime.authEvents.length - 1].authenticated, true, "A is signed in");
  }

  /* B. Confirmed logout hides private state and clears the server Skill projection. */
  {
    const runtime = buildRuntime(accountAFixture(), { canonicalUser: OWNER_A });
    await settle();
    const clearsBeforeLogout = runtime.skillCleared.length;

    await runtime.element("padiemLogout").click();
    assert.equal(runtime.logoutPosts.length, 1, "canonical logout endpoint was called");
    assert.equal(runtime.lastScope().action, Scope.SCOPE_ACTIONS.SIGNED_OUT, "signed-out scope applied");
    assert.equal(runtime.lastScope().privateStateReadable, false, "LOGOUT_PRIVATE_QUOTE_VISIBLE=0");
    assert.equal(runtime.authEvents[runtime.authEvents.length - 1].authenticated, false, "signed-out auth event");
    assert.ok(runtime.skillCleared.length > clearsBeforeLogout,
      "server-assigned Skill projection is cleared again on logout");
    assert.equal(runtime.accountButtonText(), "로그인", "account button reflects canonical signed out");
    assert.equal(runtime.quoteStatusText(), "로그아웃되었습니다.", "confirmed logout is reported truthfully");
    PRIVATE_KEYS.forEach((key) => {
      const value = runtime.storage.getItem(key);
      if (value !== null) {
        assert.ok(!Scope.privateStateReadable(), "retained state stays unreadable while signed out");
      }
    });
  }

  /* C. B signs in on the same browser after A logged out: A's state is quarantined. */
  {
    const runtime = buildRuntime(accountAFixture(), { canonicalUser: OWNER_A });
    await settle();
    await runtime.element("padiemLogout").click();
    assert.equal(runtime.storage.getItem(Core.DRAFT_STORAGE_KEY), A_DRAFT, "A bytes retained for same-account resume");

    await runtime.signIn(OWNER_B);
    assert.equal(runtime.lastScope().action, Scope.SCOPE_ACTIONS.QUARANTINED_FOREIGN_OWNER, "B quarantines A state");
    PRIVATE_KEYS.forEach((key) => {
      assert.equal(runtime.storage.getItem(key), null, "B cannot read or reuse A state at " + key);
    });
    assert.equal(runtime.storage.getItem(Scope.OWNER_STORAGE_KEY), markerB, "marker rebound to canonical B");
    ["A거래처", "A 품목", "A 비밀", "A회사", "b66skill_A"].forEach((secret) => {
      assert.ok(!storedBlob(runtime.storage).includes(secret), "A fact is gone after the switch: " + secret);
    });
  }

  /* E. A signs back in after no other account used the browser: same-account resume. */
  {
    const runtime = buildRuntime(accountAFixture(), { canonicalUser: OWNER_A });
    await settle();
    await runtime.element("padiemLogout").click();
    await runtime.signIn(OWNER_A);
    assert.equal(runtime.lastScope().action, Scope.SCOPE_ACTIONS.SAME_ACCOUNT_RESUME, "SAME_ACCOUNT_RESUME=PASS");
    assert.equal(runtime.storage.getItem(Core.DRAFT_STORAGE_KEY), A_DRAFT, "A resumes its own draft");
    assert.equal(runtime.storage.getItem(History.HISTORY_STORAGE_KEY), A_HISTORY, "A resumes its own history");
  }

  /* H. failed canonical logout is never presented as confirmed success. */
  {
    const stillSignedIn = buildRuntime(accountAFixture(), {
      canonicalUser: OWNER_A,
      logoutKeepsSession: true
    });
    await settle();
    await stillSignedIn.element("padiemLogout").click();

    assert.equal(stillSignedIn.logoutPosts.length, 1, "logout attempt was made");
    assert.ok(
      stillSignedIn.toasts.some((message) => message.includes("로그아웃을 확인하지 못했습니다")),
      "FAILED_CANONICAL_LOGOUT_SHOWN_AS_SUCCESS=0: a truthful error is surfaced"
    );
    assert.ok(
      stillSignedIn.quoteStatusText().includes("로그아웃을 확인하지 못했습니다"),
      "the live status line reports the unconfirmed logout"
    );
    assert.notEqual(stillSignedIn.quoteStatusText(), "로그아웃되었습니다.", "no success wording");
    assert.equal(stillSignedIn.authEvents[stillSignedIn.authEvents.length - 1].authenticated, true,
      "canonical status still reports a live session");
    assert.equal(stillSignedIn.lastScope().privateStateReadable, true,
      "same-account private state is restored because the session is still A");
  }

  /* H2. logout request fails outright: still no confirmed-logout claim. */
  {
    const networkDown = buildRuntime(accountAFixture(), {
      canonicalUser: OWNER_A,
      logoutNetworkFails: true
    });
    await settle();
    await networkDown.element("padiemLogout").click();
    assert.ok(
      networkDown.toasts.some((message) => message.includes("로그아웃을 확인하지 못했습니다")),
      "network logout failure reports a truthful error"
    );
    assert.equal(networkDown.authEvents[networkDown.authEvents.length - 1].authenticated, true,
      "session survives a failed logout request");
  }

  /* H3. indeterminate canonical status is never called signed out. */
  {
    const indeterminate = buildRuntime(accountAFixture(), { canonicalUser: OWNER_A });
    await settle();
    indeterminate.makeStatusUnavailable(true);
    await indeterminate.element("padiemLogout").click();
    assert.ok(
      indeterminate.toasts.some((message) => message.includes("로그아웃을 확인하지 못했습니다")),
      "an unevaluable canonical status is reported as unconfirmed"
    );
    assert.equal(indeterminate.lastScope().privateStateReadable, false,
      "private state is hidden while canonical status is unknown");
  }

  /* I. the canonical projection is the only owner source. */
  {
    assert.ok(accountSource.includes("applyOwnerScope({ authenticated: true, userId: owner ? owner.id : null })"),
      "owner source is the canonical /auth/status user.id projection");
    assert.ok(!accountSource.includes("localStorage") && !accountSource.includes("sessionStorage"),
      "the canonical auth bridge still holds no browser storage authority");
    assert.ok(!/console\.(log|info|warn|error)/.test(accountSource), "the auth bridge logs nothing");
    assert.ok(indexHtml.includes('<script src="quote-account-scope.js" defer></script>'),
      "owner scope module ships in the page");
    assert.ok(indexHtml.indexOf("quote-account-scope.js") < indexHtml.indexOf("app.js"),
      "owner scope module is evaluated before app.js reads it");
  }

  /* No private key may bypass the owner gate. */
  {
    [
      "readPrivateItem(Core.DRAFT_STORAGE_KEY)",
      "readPrivateItem(Core.SENDER_STORAGE_KEY)",
      "readPrivateItem(History.HISTORY_STORAGE_KEY)",
      "readPrivateItem(History.SEQUENCE_STORAGE_KEY)",
      "readPrivateItem(TAX_REVIEW_STORAGE_KEY)",
      "readPrivateItem(TemplateStore.TEMPLATE_STORAGE_KEY)"
    ].forEach((call) => {
      assert.ok(appSource.includes(call), "app.js routes " + call + " through the owner gate");
    });
    assert.ok(!/localStorage\.(getItem|setItem)\((Core\.(DRAFT|SENDER)_STORAGE_KEY|History\.(HISTORY|SEQUENCE)_STORAGE_KEY|TAX_REVIEW_STORAGE_KEY|TemplateStore\.TEMPLATE_STORAGE_KEY)/.test(appSource),
      "no private key bypasses the owner gate in app.js");
    assert.ok(!/localStorage\.(getItem|setItem)\(History\.HISTORY_STORAGE_KEY/.test(easySource),
      "easy-mode history is gated too");
    assert.ok(easySource.includes("App.getHistoryEnvelope()") && easySource.includes("App.writeHistoryEnvelope(envelope)"),
      "easy mode routes history through the owner-aware app bridge");
    assert.ok(appSource.includes('document.addEventListener("b66:account-scope-changed"'),
      "app.js reacts to the canonical owner scope transition");
    assert.ok(easySource.includes('document.addEventListener("b66:account-scope-changed"'),
      "easy mode drops in-memory guided context on an owner change");
    assert.ok(appSource.includes("discardPrivateProjection"),
      "signed-out/foreign owner discards the live private projection");
    assert.ok(appSource.includes("privateStateReadable()"),
      "app.js centralises the private-read gate");
  }

  console.log("B66_ACCOUNT_SCOPE_3480_RUNTIME=PASS");
  console.log("CANONICAL_ACCOUNT_ID_SUBMITTED_BY_BROWSER=0");
  console.log("SERVER_ASSIGNED_SKILL_CLEARED_ON_LOGOUT=YES");
  console.log("FAILED_CANONICAL_LOGOUT_SHOWN_AS_SUCCESS=0");
  console.log("SIGNED_OUT_PRIVATE_QUOTE_VISIBLE=0");
  console.log("PRODUCTION_MUTATION=0");
})().catch((err) => {
  console.error("B66_ACCOUNT_SCOPE_3480=FAIL");
  console.error(err);
  process.exitCode = 1;
});