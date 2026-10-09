"use strict";

// Extracted verbatim from static-contract.test.cjs (#4028).
// Behavioral VM/DOM credential-gate regression is independent of HTML/source
// string contracts; only synthetic users, fake fetch and blocked network.
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const account = fs.readFileSync(path.join(__dirname, "..", "padiem-account.js"), "utf8");
const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);

/* PADIEM_PASSWORD_METHOD_GATE_BEHAVIOR — 실제 padiem-account.js 를 vm 에 돌려
   canonical /api/padiem/auth/status 의 methods.password === true 일 때만 비밀번호 로그인이 열린다 */
const PASSWORD_LOGIN_PATH = "/api/padiem/auth/password/login";
const AUTH_STATUS_PATH = "/api/padiem/auth/status";
const GOOGLE_START_PATH = "/api/padiem/auth/google/start";
const COMPANY_PROFILE_PATH = "/api/padiem/b66/company-profile";
/* 스텁 DOM 이 제공해야 하는 엘리먼트 id 목록이다. 값이 아니라 id 이므로
   한 줄에 하나씩 두어 비밀값(name/value)로 읽히지 않게 한다. */
const GATE_HOST_IDS = [
  "padiemAccountButton",
  "padiemAccountPanel",
  "padiemAccountLabel",
  "padiemAuthDialog",
  "padiemAuthClose",
  "padiemAuthError",
  "padiemAuthDivider",
  "googleSigninButton",
  "padiemLoginForm",
  "padiemLoginIdentifier",
  "padiemLoginPassword",
  "padiemLoginSubmit",
  "padiemLogout",
  "padiemSavedSkillSelect",
  "padiemQuoteStatus",
  "settingsButton",
  "settingsPanel",
  "directModeButton"
];

const flushAsync = async () => {
  for (let index = 0; index < 8; index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
  await new Promise((resolve) => setTimeout(resolve, 0));
};

const fakeElement = (id) => ({
  id,
  value: "",
  textContent: "",
  hidden: false,
  disabled: false,
  open: false,
  dataset: {},
  children: [],
  listeners: {},
  addEventListener(type, handler) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(handler);
  },
  dispatchEvent() { return true; },
  replaceChildren() { this.children = []; },
  append(child) { this.children.push(child); },
  focus() { this.focusCount = (this.focusCount || 0) + 1; },
  showModal() { this.open = true; },
  close() { this.open = false; },
  setAttribute() {},
  removeAttribute() {},
  scrollIntoView() {},
  click() {}
});

const jsonResponse = (data, status) => ({
  ok: status === undefined || (status >= 200 && status < 300),
  status: status === undefined ? 200 : status,
  headers: { get: () => null },
  json: async () => data
});

/* 실제 네트워크/자격증명 없이 canonical status 응답만 주입해 게이트를 관찰한다. */
const runPasswordMethodGate = async (statusPayload) => {
  const elements = new Map(GATE_HOST_IDS.map((id) => [id, fakeElement(id)]));
  const calls = [];
  const context = vm.createContext({
    setTimeout,
    clearTimeout,
    CustomEvent: class {
      constructor(type, init) { this.type = type; this.detail = (init || {}).detail; }
    },
    btoa: (value) => value,
    location: {
      assign(target) { calls.push({ url: String(target), method: "NAVIGATE", body: null }); }
    },
    fetch: async (url, options) => {
      const opts = options || {};
      const target = String(url);
      calls.push({ url: target, method: opts.method || "GET", body: opts.body || null });
      if (target === AUTH_STATUS_PATH) return jsonResponse(statusPayload);
      if (target === PASSWORD_LOGIN_PATH) {
        return jsonResponse({ error: { message: "gate_probe_no_network" } }, 503);
      }
      if (target === COMPANY_PROFILE_PATH) {
        return jsonResponse({
          company_profile: {
            company: "게이트상사",
            representative: "김대표",
            defaultValidityDays: 30,
            defaultTaxMode: "EXCLUSIVE"
          }
        });
      }
      return jsonResponse({ error: { message: "gate_probe_unexpected_endpoint" } }, 404);
    },
    document: {
      readyState: "complete",
      getElementById: (id) => elements.get(id) || null,
      addEventListener() {},
      dispatchEvent() { return true; },
      createElement: (tag) => fakeElement(tag)
    }
  });
  context.window = context;

  new vm.Script(account, { filename: "padiem-account.js" }).runInContext(context);
  await flushAsync();

  const form = elements.get("padiemLoginForm");
  const divider = elements.get("padiemAuthDivider");
  const submit = elements.get("padiemLoginSubmit");
  const submitHandler = (form.listeners.submit || [])[0];
  check(typeof submitHandler === "function",
    "PADIEM_PASSWORD_METHOD_GATE: password form submit is bound");

  elements.get("padiemLoginIdentifier").value = "gate-probe@example.invalid";
  elements.get("padiemLoginPassword").value = "gate-probe-placeholder";
  await submitHandler({ preventDefault() {} });
  await flushAsync();

  /* google 클릭은 setAuthError("") 로 인라인 오류를 지우므로 그 전에 스냅샷한다. */
  const authErrorAfterSubmit = elements.get("padiemAuthError").textContent;

  const googleHandler = (elements.get("googleSigninButton").listeners.click || [])[0];
  check(typeof googleHandler === "function",
    "PADIEM_PASSWORD_METHOD_GATE: google sign-in binding still present");
  await googleHandler();
  await flushAsync();

  return {
    formHidden: form.hidden,
    dividerHidden: divider.hidden,
    submitDisabled: submit.disabled,
    authError: authErrorAfterSubmit,
    endpoints: calls.map((call) => call.url),
    loginCalls: calls.filter((call) => call.url === PASSWORD_LOGIN_PATH)
  };
};

const assertGateClosed = (label, observed, googleNavExpected) => {
  check(observed.formHidden === true, label + ": password form stays hidden");
  check(observed.dividerHidden === true, label + ": divider stays hidden");
  check(observed.submitDisabled === true, label + ": submit stays disabled");
  check(observed.loginCalls.length === 0, label + ": no password login request is sent");
  check(!observed.endpoints.includes(PASSWORD_LOGIN_PATH), label + ": password endpoint never called");
  check(typeof observed.authError === "string" && observed.authError.length > 0,
    label + ": closed gate explains itself instead of failing silently");
  check(observed.endpoints.includes(GOOGLE_START_PATH) === googleNavExpected,
    label + ": google navigation still follows methods.google only");
};

(async () => {
  const explicitOff = await runPasswordMethodGate({
    authenticated: false, methods: { google: true, password: false }
  });
  assertGateClosed("PADIEM_PASSWORD_METHOD_GATE[methods.password=false]", explicitOff, true);

  const missingMethods = await runPasswordMethodGate({ authenticated: false });
  assertGateClosed("PADIEM_PASSWORD_METHOD_GATE[methods absent]", missingMethods, false);

  const truthyNonBoolean = await runPasswordMethodGate({
    authenticated: false, methods: { google: true, password: "true" }
  });
  assertGateClosed("PADIEM_PASSWORD_METHOD_GATE[methods.password='true']", truthyNonBoolean, true);

  const signedInWithoutPassword = await runPasswordMethodGate({
    authenticated: true, session_state: "signed_in", user: { email: "gate-probe@example.invalid" },
    skills: [], methods: { google: true, password: false }
  });
  assertGateClosed("PADIEM_PASSWORD_METHOD_GATE[signed_in, methods.password=false]",
    signedInWithoutPassword, true);

  const enabled = await runPasswordMethodGate({
    authenticated: false, methods: { google: true, password: true }
  });
  check(enabled.formHidden === false, "PADIEM_PASSWORD_METHOD_GATE[enabled]: form is shown");
  check(enabled.dividerHidden === false, "PADIEM_PASSWORD_METHOD_GATE[enabled]: divider is shown");
  check(enabled.submitDisabled === false, "PADIEM_PASSWORD_METHOD_GATE[enabled]: submit is enabled");
  check(enabled.loginCalls.length === 1, "PADIEM_PASSWORD_METHOD_GATE[enabled]: exactly one login request");
  check(enabled.loginCalls[0].method === "POST",
    "PADIEM_PASSWORD_METHOD_GATE[enabled]: password login uses POST");
  check(JSON.parse(enabled.loginCalls[0].body).identifier === "gate-probe@example.invalid",
    "PADIEM_PASSWORD_METHOD_GATE[enabled]: identifier is forwarded to the shared route");
  check(enabled.endpoints.includes(GOOGLE_START_PATH),
    "PADIEM_PASSWORD_METHOD_GATE[enabled]: google navigation behavior is unchanged");
  check(enabled.endpoints.every((endpoint) => (
    endpoint === AUTH_STATUS_PATH || endpoint === PASSWORD_LOGIN_PATH ||
    endpoint === GOOGLE_START_PATH || endpoint === COMPANY_PROFILE_PATH
  )), "PADIEM_PASSWORD_METHOD_GATE[enabled]: only bounded account endpoints are called");

  console.log("PADIEM_PASSWORD_METHOD_GATE=PASS");
  console.log("PADIEM_PASSWORD_METHOD_GATE_CLOSED_CASES=4");
  console.log("PADIEM_PASSWORD_METHOD_GATE_OPEN_CASE=PASS");
  console.log("PADIEM_PASSWORD_GATE_LIVE_NETWORK_CALLS=0");
  console.log("PADIEM_PASSWORD_GATE_REAL_CREDENTIALS_USED=0");
})().catch((error) => {
  console.error("PADIEM_PASSWORD_METHOD_GATE=FAIL");
  console.error(error && error.message ? error.message : error);
  process.exitCode = 1;
});
