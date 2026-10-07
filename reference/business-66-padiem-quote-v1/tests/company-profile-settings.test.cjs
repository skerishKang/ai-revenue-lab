/* CompanyProfile self-service settings tests (#3406).

   Runs on a stub DOM (same discipline as quote-skill-ui.test.cjs):
   - DOM API-only rendering (no innerHTML anywhere in the module)
   - server is the canonical account authority: the module never sends
     owner/workspace fields and never reads them from the client
   - assisted/pre-provisioned accounts (state: ready) never see onboarding copy */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const Settings = require("../company-profile-settings.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const MODULE_SOURCE = fs.readFileSync(path.join(__dirname, "..", "company-profile-settings.js"), "utf8");
const INDEX_HTML = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");

/* ── stub DOM ── */
function matches(node, selector) {
  if (!selector) return false;
  if (selector[0] === "#") return node.id === selector.slice(1);
  if (selector[0] === ".") return String(node.className || "").split(/\s+/).includes(selector.slice(1));
  const attr = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
  if (attr) {
    const value = node.attributes ? node.attributes[attr[1]] : undefined;
    if (value === undefined) return false;
    return attr[2] === undefined || value === attr[2];
  }
  if (selector.includes(".")) {
    const parts = selector.split(".");
    return node.tagName === parts[0].toUpperCase() &&
      String(node.className || "").split(/\s+/).includes(parts[1]);
  }
  return node.tagName === String(selector).toUpperCase();
}

function queryAll(root, selector) {
  const found = [];
  const visit = (node) => {
    (node.children || []).forEach((child) => {
      if (matches(child, selector)) found.push(child);
      visit(child);
    });
  };
  visit(root);
  return found;
}

function stubDocument(staticIds) {
  const byId = new Map();
  const doc = {
    readyState: "complete",
    listeners: {},
    activeElement: null,
    createElement(tag) { return makeNode(String(tag)); },
    createTextNode(text) { return { nodeType: 3, textContent: String(text), children: [] }; },
    getElementById(id) { return byId.get(String(id)) || null; },
    addEventListener(type, fn) { (doc.listeners[type] = doc.listeners[type] || []).push(fn); },
    dispatchEvent(event) {
      (doc.listeners[event.type] || []).forEach((fn) => fn(event));
    }
  };
  function makeNode(tag) {
    const node = {
      tagName: tag.toUpperCase(),
      id: "",
      className: "",
      attributes: {},
      hidden: false,
      disabled: false,
      children: [],
      parent: null,
      listeners: {},
      textContentValue: "",
      setAttribute(name, value) {
        this.attributes[name] = String(value);
        if (name === "id") { this.id = String(value); byId.set(this.id, this); }
      },
      getAttribute(name) { return this.attributes[name] === undefined ? null : this.attributes[name]; },
      appendChild(child) {
        child.parent = this;
        this.children.push(child);
        if (child.id) byId.set(child.id, child);
        return child;
      },
      removeChild(child) {
        this.children = this.children.filter((c) => c !== child);
        return child;
      },
      addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
      dispatch(type, event) {
        (this.listeners[type] || []).forEach((fn) => fn(Object.assign({ target: this }, event || {})));
      },
      click() { this.dispatch("click", {}); },
      querySelector(sel) { return queryAll(this, sel)[0] || null; },
      querySelectorAll(sel) { return queryAll(this, sel); }
    };
    Object.defineProperty(node, "textContent", {
      get() {
        const own = this.textContentValue || "";
        const childText = (this.children || [])
          .map((c) => String(c.textContent))
          .join("");
        return own + childText;
      },
      set(value) {
        this.textContentValue = String(value);
        this.children = [];
      },
      configurable: true
    });
    if (node.tagName === "SELECT") {
      node.options = [];
      const originalAppend = node.appendChild.bind(node);
      node.appendChild = function (child) {
        const result = originalAppend(child);
        node.options = node.children.filter((c) => c.tagName === "OPTION");
        return result;
      };
      Object.defineProperty(node, "value", {
        get() {
          const selected = node.options.find((o) => o.selected);
          if (selected) return selected.attributes.value;
          return node.options[0] ? node.options[0].attributes.value : "";
        },
        set(v) {
          node.options.forEach((o) => { o.selected = o.attributes.value === String(v); });
        },
        configurable: true
      });
    } else {
      node.value = "";
    }
    return node;
  }
  (staticIds || []).forEach((id) => {
    const node = makeNode("div");
    node.setAttribute("id", id);
  });
  return doc;
}

function stubSession() {
  const map = new Map();
  const writes = [];
  return {
    writes,
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => { writes.push([key, String(value)]); map.set(key, String(value)); },
    removeItem: (key) => { writes.push(["remove:" + key, ""]); map.delete(key); }
  };
}

function jsonResponse(status, body) {
  return { response: { ok: status >= 200 && status < 300, status }, data: body };
}

function bind(doc, session, fetchLog) {
  const reloads = [];
  const host = doc.getElementById("companyProfileHost");
  const panel = doc.getElementById("settingsPanel");
  const controller = Settings.bindCompanyProfileSection({
    doc,
    host,
    settingsPanel: panel,
    session,
    reloadDelay: 0,
    reload: () => { reloads.push(1); },
    fetchJson: (endpoint, options) => {
      const entry = { endpoint, options: options || null };
      fetchLog.push(entry);
      const handler = fetchLog.handler;
      return Promise.resolve(handler ? handler(entry) : jsonResponse(500, null)).then((r) => r);
    }
  });
  return { controller, host, panel, reloads };
}

const STATIC_IDS = ["companyProfileHost", "settingsPanel", "settingsButton", "settingsClose"];

function flush() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/* ── K/L: signed-out → private read/write denied ── */
async function test_signed_out_denied() {
  const doc = stubDocument(STATIC_IDS);
  const fetchLog = [];
  fetchLog.handler = () => jsonResponse(401, { ok: false, error: { code: "unauthorized" } });
  const session = stubSession();
  const { controller, host } = bind(doc, session, fetchLog);
  await controller.refresh();
  await flush();
  check(host.textContent.includes("로그인"), "signed-out note rendered");
  check(!host.querySelector("form.company-profile-form"), "no form for signed-out visitor");
  check(fetchLog[0].endpoint === Settings.PROFILE_ENDPOINT, "GET endpoint");
  console.log("PASS signed-out denied");
}

/* ── A: Account A, no profile → bounded onboarding → save ── */
async function test_missing_profile_onboarding_and_save() {
  const doc = stubDocument(STATIC_IDS);
  const fetchLog = [];
  fetchLog.handler = (entry) => {
    if (!entry.options) return jsonResponse(200, { ok: true, state: "missing", company_profile: null });
    return jsonResponse(200, {
      ok: true, state: "ready",
      company_profile: { company: "테스트상사", defaultValidityDays: 7 }
    });
  };
  const session = stubSession();
  const { controller, host, panel, reloads } = bind(doc, session, fetchLog);
  await controller.refresh();
  await flush();
  check(host.textContent.includes("내 회사 정보를 먼저 설정할까요?"), "onboarding offer copy");
  const form = host.querySelector("form.company-profile-form");
  check(form, "onboarding form rendered");
  check(panel.hidden === false, "bounded onboarding opened the settings panel");

  /* company required */
  controller.submit();
  await flush();
  const companyError = form.querySelector('[data-error-for="company"]');
  check(companyError && companyError.textContent.includes("회사명"), "company required error");
  check(fetchLog.length === 1, "no PUT on invalid save");

  /* invalid validity */
  doc.getElementById("cpField-company").value = "테스트상사";
  doc.getElementById("cpField-defaultValidityDays").value = "99999";
  controller.submit();
  await flush();
  check(fetchLog.length === 1, "no PUT on invalid validity");
  check(form.querySelector('[data-error-for="defaultValidityDays"]').textContent.includes("3650"),
    "validity range error");

  /* valid save → PUT with only profile keys, no owner authority */
  doc.getElementById("cpField-defaultValidityDays").value = "";
  doc.getElementById("cpField-representative").value = "홍길동";
  const savePromise = controller.submit();
  await flush();
  await savePromise;
  const put = fetchLog[1];
  check(put.endpoint === Settings.PROFILE_ENDPOINT && put.options.method === "PUT", "PUT endpoint/method");
  const payload = JSON.parse(put.options.body);
  const allowed = Settings.FIELD_DEFS.map((f) => f.key);
  Object.keys(payload).forEach((key) => check(allowed.includes(key), `payload key allowed: ${key}`));
  ["user_id", "userId", "tenant_id", "workspace_id", "owner"].forEach((key) => {
    check(!(key in payload), `no client-supplied owner field: ${key}`);
  });
  check(payload.company === "테스트상사" && payload.representative === "홍길동", "payload values");
  await flush();
  check(reloads.length === 1, "page reload after successful save");
  check(session.writes.some(([key]) => key === Settings.ONBOARDING_DISMISS_KEY), "onboarding dismissal recorded");
  console.log("PASS missing-profile onboarding and save");
}

/* ── B/H: existing (pre-provisioned) profile → edit form, no onboarding ── */
async function test_ready_profile_edit_no_onboarding() {
  const doc = stubDocument(STATIC_IDS);
  const fetchLog = [];
  fetchLog.handler = (entry) => {
    if (!entry.options) {
      return jsonResponse(200, {
        ok: true, state: "ready",
        company_profile: {
          company: "테스트상사", representative: "테스트대표", businessNumber: "000-00-00000",
          address: "테스트시 테스트구", phone: "02-0000-0000",
          defaultValidityDays: 7, defaultTaxMode: "EXCLUSIVE"
        }
      });
    }
    return jsonResponse(200, { ok: true, state: "ready", company_profile: { company: "테스트상사" } });
  };
  const session = stubSession();
  const { controller, host } = bind(doc, session, fetchLog);
  await controller.refresh();
  await flush();
  check(!host.textContent.includes("먼저 설정할까요"), "NO onboarding offer for pre-provisioned account");
  const form = host.querySelector("form.company-profile-form");
  check(form, "edit form rendered");
  check(doc.getElementById("cpField-company").value === "테스트상사", "prefilled company");
  check(doc.getElementById("cpField-defaultTaxMode").value === "EXCLUSIVE", "prefilled tax mode");
  check(!host.querySelector("#cpSkip"), "no skip button in edit mode");

  doc.getElementById("cpField-phone").value = "02-0000-1111";
  await controller.submit();
  await flush();
  const put = fetchLog[1];
  check(put && put.options.method === "PUT", "PUT sent");
  const payload = JSON.parse(put.options.body);
  check(payload.company === "테스트상사" && payload.phone === "02-0000-1111", "edit payload carries full form");
  console.log("PASS ready profile edit without onboarding");
}

/* ── read failure → bounded error + retry (truthful missing/error state) ── */
async function test_read_error_state() {
  const doc = stubDocument(STATIC_IDS);
  const fetchLog = [];
  fetchLog.handler = () => jsonResponse(503, { ok: false, error: { code: "company_profile_unavailable" } });
  const { controller, host } = bind(doc, stubSession(), fetchLog);
  await controller.refresh();
  await flush();
  check(host.textContent.includes("불러오지 못했습니다"), "read failure surfaced truthfully");
  check(host.querySelector("#cpRetry"), "retry affordance");
  console.log("PASS read error state");
}

/* ── invalid PUT → field-level error, save re-enabled ── */
async function test_put_invalid_feedback() {
  const doc = stubDocument(STATIC_IDS);
  const fetchLog = [];
  fetchLog.handler = (entry) => {
    if (!entry.options) return jsonResponse(200, { ok: true, state: "ready", company_profile: { company: "A" } });
    return jsonResponse(400, { ok: false, error: { code: "invalid_company_profile" } });
  };
  const { controller, host } = bind(doc, stubSession(), fetchLog);
  await controller.refresh();
  await flush();
  const save = host.querySelector("#cpSave");
  await controller.submit();
  await flush();
  const status = host.querySelector("#cpStatus");
  check(status.textContent.includes("확인해 주세요"), "invalid payload feedback");
  check(save.disabled === false, "save re-enabled after failure");
  console.log("PASS invalid PUT feedback");
}

/* ── skip records dismissal; auth-changed(false) renders signed-out ── */
async function test_skip_and_auth_changed() {
  const doc = stubDocument(STATIC_IDS);
  const fetchLog = [];
  fetchLog.handler = () => jsonResponse(200, { ok: true, state: "missing", company_profile: null });
  const session = stubSession();
  const { controller, host } = bind(doc, session, fetchLog);
  await controller.refresh();
  await flush();
  const skip = host.querySelector("#cpSkip");
  skip.click();
  check(session.writes.some(([key]) => key === Settings.ONBOARDING_DISMISS_KEY), "skip recorded");
  check(host.textContent.includes("나중에"), "skip note rendered");

  doc.dispatchEvent({ type: "b66:auth-changed", detail: { authenticated: false } });
  await flush();
  check(host.textContent.includes("로그인"), "signed-out after auth change");
  console.log("PASS skip and auth-changed handling");
}

/* ── Fix 3: cross-account onboarding dismissal 재사용 금지 ── */
async function test_cross_account_dismissal_not_reused() {
  const doc = stubDocument(STATIC_IDS);
  const fetchLog = [];
  fetchLog.handler = () => jsonResponse(200, { ok: true, state: "missing", company_profile: null });
  const session = stubSession();
  const { controller, host, panel } = bind(doc, session, fetchLog);

  /* Account A: missing → auto-open → skip (dismiss 기록) */
  await controller.refresh();
  await flush();
  check(panel.hidden === false, "A onboarding auto-opened");
  host.querySelector("#cpSkip").click();
  check(session.getItem(Settings.ONBOARDING_DISMISS_KEY) === "dismissed", "A dismissal recorded");

  /* 같은 signed-in 세션: skip 후에는 반복 auto-open 되지 않는다 */
  panel.hidden = true;
  await controller.refresh();
  await flush();
  check(panel.hidden === true, "no repeated auto-open within the same signed-in session");

  /* logout: auth false → 이전 계정의 dismiss 플래그 clear */
  doc.dispatchEvent({ type: "b66:auth-changed", detail: { authenticated: false } });
  await flush();
  check(session.getItem(Settings.ONBOARDING_DISMISS_KEY) === null, "dismissal cleared on signed-out");

  /* Account B: authenticated + missing → onboarding offer가 다시 보인다 */
  panel.hidden = true;
  doc.dispatchEvent({ type: "b66:auth-changed", detail: { authenticated: true } });
  await flush();
  check(host.textContent.includes("내 회사 정보를 먼저 설정할까요?"), "B onboarding offer visible");
  check(panel.hidden === false, "B onboarding auto-opened again");
  console.log("PASS cross-account dismissal reuse prevented");
}

/* ── Fix 2: copy truthfulness ── */
async function test_copy_truthfulness() {
  const doc = stubDocument(STATIC_IDS);
  const fetchLog = [];
  fetchLog.handler = () => jsonResponse(200, { ok: true, state: "ready", company_profile: { company: "테스트상사" } });
  const { controller, host } = bind(doc, stubSession(), fetchLog);
  await controller.refresh();
  await flush();
  check(host.textContent.includes("로그인 계정에 저장되어 다른 기기에서도 사용됩니다"),
    "edit form describes the profile as account-bound and cross-device");
  check(INDEX_HTML.includes("'내 회사' 정보는 로그인 계정에 저장되어 다른 기기에서도 사용됩니다"),
    "settings note separates browser-local drafts from the account-bound profile");
  check(INDEX_HTML.includes("작성 중 견적은 이 브라우저에 저장"),
    "browser-local note kept truthful for drafts only");
  console.log("PASS copy truthfulness");
}

/* ── static + module contracts ── */
function test_static_contracts() {
  check(INDEX_HTML.includes('id="companyProfileHost"'), "index.html has company profile host");
  check(INDEX_HTML.includes('id="companyProfileSection"'), "index.html has 내 회사 section");
  check(INDEX_HTML.includes('src="company-profile-settings.js"'), "module script wired");
  check(INDEX_HTML.indexOf("company-profile-settings.js") < INDEX_HTML.indexOf("padiem-account.js"),
    "module loads before padiem-account to receive initial auth events");
  const moduleCode = MODULE_SOURCE.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
  check(!/innerHTML/.test(moduleCode), "module renders without innerHTML");
  /* sessionStorage is convenience-only (onboarding dismissal); localStorage must not appear */
  check(!/\blocalStorage\b/.test(moduleCode), "module never treats browser local storage as authority");
  ["견적서" + "샘플", "시지아" + "이", "CGI-2-", "목포대학교", "J4:R9", "FmlaPict"].forEach((token) => {
    check(!MODULE_SOURCE.includes(token), `no document-specific constant: ${token}`);
  });
  /* REAL_CUSTOMER_DATA_IN_GITHUB=0 — 실제 고객 식별 literal 금지 (파트 결합으로 self-match 회피) */
  const snapshotSource = fs.readFileSync(path.join(__dirname, "company-profile-snapshot.test.cjs"), "utf8");
  const realCustomerTokens = ["시지아" + "이", "김범" + "식", "410-86-" + "46283", "장성" + "군 남면", "576-" + "8100"];
  [MODULE_SOURCE, snapshotSource].forEach((source, i) => {
    realCustomerTokens.forEach((token) => {
      check(!source.includes(token), `real customer literal absent (source ${i}): ${token}`);
    });
  });
  /* identity/contact fields only — no quote-family policy ownership */
  const keys = Settings.FIELD_DEFS.map((f) => f.key);
  ["defaultValidityDays", "defaultTaxMode"].forEach((key) => check(keys.includes(key), `fallback field: ${key}`));
  ["validDays", "taxMode", "paymentTerms", "quoteNumberPolicy"].forEach((key) => {
    check(!keys.includes(key), `no quote-family policy field: ${key}`);
  });
  console.log("PASS static and module contracts");
}

(async () => {
  await test_signed_out_denied();
  await test_missing_profile_onboarding_and_save();
  await test_ready_profile_edit_no_onboarding();
  await test_read_error_state();
  await test_put_invalid_feedback();
  await test_skip_and_auth_changed();
  await test_cross_account_dismissal_not_reused();
  await test_copy_truthfulness();
  test_static_contracts();
  console.log("ALL COMPANY-PROFILE-SETTINGS TESTS PASSED");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
