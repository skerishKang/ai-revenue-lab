const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const Skill = require("../quote-skill.js");
const SkillStore = require("../quote-skill-store.js");
const Session = require("../quote-registration-session.js");
const SkillUi = require("../quote-skill-ui.js");
const Template = require("../quote-template.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) => assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);
const clone = (value) => JSON.parse(JSON.stringify(value));
const NOW = "2026-09-30T05:00:00.000Z";

/* ── 스텁 DOM: UI 모듈은 innerHTML 없이 DOM API 로만 렌더한다 ── */

function matches(node, selector) {
  if (!selector) return false;
  if (selector[0] === "#") return node.id === selector.slice(1);
  const dataAction = selector.match(/^\[data-action(?:="([^"]*)")?\]$/);
  if (dataAction) {
    const value = node.attributes ? node.attributes["data-action"] : undefined;
    if (value === undefined) return false;
    return dataAction[1] === undefined || value === dataAction[1];
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
    activeElement: null,
    createElement(tag) { return makeNode(String(tag)); },
    createTextNode(text) { return { nodeType: 3, textContent: String(text), parent: null }; },
    getElementById(id) { return byId.get(String(id)) || null; }
  };
  function makeNode(tag) {
    const node = {
      tagName: tag.toUpperCase(),
      id: "",
      attributes: {},
      dataset: {},
      checked: false,
      files: [],
      hidden: false,
      selected: false,
      disabled: false,
      textContent: "",
      children: [],
      parent: null,
      listeners: {},
      focused: false,
      style: {},
      classList: { add() {}, remove() {}, toggle() {} },
      setAttribute(name, value) {
        this.attributes[name] = String(value);
        if (name === "id") { this.id = String(value); byId.set(this.id, this); }
        if (name.slice(0, 5) === "data-") {
          this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value);
        }
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
        child.parent = null;
        return child;
      },
      get firstChild() { return this.children[0] || null; },
      addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
      dispatch(type, event) {
        (this.listeners[type] || []).forEach((fn) => fn(Object.assign({ target: this }, event || {})));
      },
      click() {
        /* Real clicks bubble to the delegated container listener. */
        let node = this;
        const event = { target: this };
        while (node) {
          (node.listeners["click"] || []).slice().forEach((fn) => fn(event));
          node = node.parent;
        }
      },
      focus() { this.focused = true; doc.activeElement = this; },
      closest(selector) {
        let node = this;
        while (node) {
          if (matches(node, selector)) return node;
          node = node.parent;
        }
        return null;
      },
      querySelector(sel) { return queryAll(this, sel)[0] || null; },
      querySelectorAll(sel) { return queryAll(this, sel); }
    };
    /* Real SELECT elements report the selected option's value. */
    if (node.tagName === "SELECT") {
      let explicit = null;
      Object.defineProperty(node, "value", {
        get() {
          if (explicit !== null) return explicit;
          const selected = this.children.find((c) => c.selected);
          return selected ? String(selected.value) : "";
        },
        set(v) {
          explicit = String(v);
          this.children.forEach((c) => { c.selected = String(c.value) === explicit; });
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

function countingStorage() {
  const map = new Map();
  const writes = [];
  return {
    writes: writes,
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => { writes.push(key); map.set(key, String(value)); },
    removeItem: (key) => { writes.push("remove:" + key); map.delete(key); }
  };
}

function sampleDraft() {
  return {
    schemaVersion: 1,
    meta: { quoteNo: "Q-DRAFT-1", issueDate: "2026-09-30", validDays: 30, source: "manual" },
    sender: { company: "기존 입력 상호", rep: "", bizNo: "", address: "", phone: "", email: "", presetId: "custom" },
    recipient: { company: "", person: "", address: "", email: "" },
    items: [],
    tax: { mode: "EXCLUSIVE", rate: 0.1 },
    memo: ""
  };
}

const STATIC_IDS = Object.keys(SkillUi.IDS).map((key) => SkillUi.IDS[key]);

const INDEX_HTML = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");

function tagFor(id) {
  const match = INDEX_HTML.match(new RegExp("<[^>]*\\bid=\"" + id + "\"[^>]*>", ""));
  check(match !== null, `static node present in index.html: #${id}`);
  return match[0];
}

function mount(envOverrides) {
  const doc = stubDocument(STATIC_IDS);
  /* Seed stub nodes with the exact static attributes index.html declares. */
  STATIC_IDS.forEach((id) => {
    const tag = tagFor(id);
    const node = doc.getElementById(id);
    const attrs = tag.match(/([a-zA-Z-]+)="([^"]*)"/g) || [];
    attrs.forEach((pair) => {
      const key = pair.slice(0, pair.indexOf("="));
      const value = pair.slice(pair.indexOf("=") + 2, -1);
      if (key !== "id" && key !== "class" && key !== "hidden") node.setAttribute(key, value);
    });
    if (/ hidden[\s>]/.test(tag)) node.hidden = true;
  });
  const applied = [];
  const previews = [];
  const toasts = [];
  let renders = 0;
  const storage = countingStorage();
  const env = Object.assign({
    storage: storage,
    getDraftSnapshot: () => clone(sampleDraft()),
    applySkillToForm: (skill) => { applied.push(skill ? skill.id : null); return true; },
    renderMain: () => { renders += 1; },
    renderPreviewModel: (model) => { previews.push(model); return true; },
    toast: (message) => { toasts.push(message); },
    confirm: () => true,
    focusMain: () => {}
  }, envOverrides || {});
  const api = SkillUi.bindSkillSection(doc, env);
  check(api !== null, "skill section binds");
  return { doc: doc, api: api, env: env, applied: applied, previews: previews, toasts: toasts, renders: () => renders, storage: storage };
}

function setValue(doc, id, value) {
  const node = doc.getElementById(id);
  check(node !== null, `wizard input present: ${id}`);
  node.value = value;
}

function clickAction(doc, action) {
  const node = doc.getElementById(SkillUi.IDS.wizardBody).querySelector(`[data-action="${action}"]`) ||
    doc.getElementById(SkillUi.IDS.list).querySelector(`[data-action="${action}"]`);
  check(node !== null, `wizard action present: ${action}`);
  node.click();
}

/* ── 순수 빌더 ── */

const options = SkillUi.buildSkillOptions(
  [{ id: "skill-a", name: "우리회사 일반 견적서" }],
  "skill-a", "skill-a"
);
eq(options[0].value, "", "builtin option comes first");
eq(options[0].selected, false, "saved skill is active");
eq(options[1].label, "우리회사 일반 견적서 (기본)", "default skill is labelled");
eq(SkillUi.buildSkillOptions([], null, null)[0].label, "기본 견적서", "empty store falls back to builtin");

const rows = SkillUi.buildSkillRows([{ id: "skill-a", name: "A" }], { activeSkillId: "skill-a", defaultSkillId: null, renamingSkillId: null });
eq(rows[0].isActive, true, "active skill row is flagged");
eq(rows[0].canSetDefault, true, "non-default skill can become default");

eq(SkillUi.wizardStepForSession(null), 1, "no session is step 1");
eq(SkillUi.wizardStepForSession({ status: Session.STATUS_TEMPLATE_REVIEW }), 3, "template review is step 3");
eq(SkillUi.wizardStepForSession({ status: Session.STATUS_SKILL_REVIEW }), 5, "skill review is step 5");
eq(SkillUi.wizardStepForSession({ status: Session.STATUS_COMMITTED }), 6, "commit is step 6");
eq(SkillUi.extractionKindForCategory("image"), "image", "images map to image extraction");
eq(SkillUi.extractionKindForCategory("document"), "native_document", "documents map to native extraction");

/* ── index.html: 내 견적서가 primary, template는 고급으로 ── */

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
check(html.includes(">5. 내 견적서<"), "MY_QUOTATION_PRIMARY_UI=PASS");
check(!html.includes("<h2>견적서 양식</h2>"), "PRIMARY_TEMPLATE_PICKER_MENTAL_MODEL=NO");
["skillSelect", "skillRegister", "skillWrite", "skillManageToggle", "skillManagePanel",
 "skillList", "skillWizardPanel", "skillWizardTitle", "skillWizardStatus", "skillWizardBody",
 "skillWizardCancel", "skillRegisterFile", "skillStatus", "skillEmptyState",
 "skillPreviewBanner"].forEach((id) => {
  check(html.includes(`id="${id}"`), `EXISTING_QUOTATION_REGISTRATION_ENTRY: #${id} present`);
});
check(html.includes("고급: 기존 양식 직접 관리"), "template management survives under an advanced disclosure");
check(html.includes('id="templateSelect"') && html.includes('id="templateCloneFile"'),
  "existing template engine ids are preserved");
check(html.includes("아직 등록한 내 견적서가 없습니다"), "empty-state copy guides first use");
check(!/AI가 견적서 디자인을 학습했습니다|모양을 자동으로 분석했습니다|완벽하게 복제/.test(html),
  "no overclaimed copy in primary UI");

/* ── 전체 wizard DOM E2E: 등록 → 수정 → preview → 승인 → 저장 → 작성 ── */

const mounted = mount();
const { doc, api, env, storage } = mounted;
eq(api.getState().step, 1, "wizard starts closed at step 1");

// open + step 1 file
doc.getElementById(SkillUi.IDS.register).click();
check(doc.getElementById(SkillUi.IDS.wizard).hidden === false, "registration opens the wizard");
doc.getElementById(SkillUi.IDS.file).files = [{ name: "synthetic-company.pdf", type: "application/pdf", size: 5822 }];
doc.getElementById(SkillUi.IDS.file).dispatch("change");
check(api.getState().fileMeta && api.getState().fileMeta.name === "synthetic-company.pdf", "STEP_1_SOURCE_SELECTION=YES");
clickAction(doc, "wiz-step2");
check(api.getState().step === 2, "STEP_2_BUSINESS_FACT_REVIEW=YES shows the facts form");

// step 2 facts -> step 3 layout (fill the step-2 form BEFORE leaving step 2)
setValue(doc, "wiz-sender-company", "테스트상사");
setValue(doc, "wiz-sender-rep", "최대표");
setValue(doc, "wiz-sender-bizno", "111-22-33333");
setValue(doc, "wiz-sender-address", "광주");
setValue(doc, "wiz-sender-phone", "062-111-2222");
setValue(doc, "wiz-sender-email", "t@test.example");
setValue(doc, "wiz-valid-days", "30");
doc.getElementById("wiz-tax-mode").value = "EXCLUSIVE";
setValue(doc, "wiz-memo", "납기 협의");
setValue(doc, "wiz-skill-name", "테스트상사 일반 견적서");
clickAction(doc, "wiz-facts-next");
check(api.getState().step === 3, "business facts lead to layout review");
// step 3 layout form is fresh here; correct it before preview
setValue(doc, "wiz-tpl-title", "테스트상사 견적서");
clickAction(doc, "wiz-preview-update");
check(mounted.previews.length === 1, "TEMPLATE_PREVIEW_BEFORE_APPROVAL=YES via live preview");
check(mounted.previews[0].template.fallbackReason === "preview_unapproved_candidate", "preview is marked unapproved");
eq(storage.writes.length, 0, "preview performs zero storage mutation");
clickAction(doc, "wiz-use-layout");
check(api.getState().step === 5, "STEP_4_MANUAL_CORRECTION=YES then explicit template approval");
check(api.getState().session.status === Session.STATUS_SKILL_REVIEW, "approved template links into skill review");
check(api.getState().session.approvedTemplate !== null &&
      api.getState().session.templateEvidence !== null, "EXPLICIT_TEMPLATE_APPROVAL=YES");

// step 5 final review -> save
check(doc.getElementById("wiz-final-skill-name").value === "테스트상사 일반 견적서", "STEP_5_FINAL_REVIEW=YES shows the skill name");
clickAction(doc, "wiz-skill-save");
check(api.getState().step === 6, "STEP_6_MY_QUOTATION_SAVE=YES");
check(api.getState().session.status === Session.STATUS_COMMITTED, "ATOMIC_COMMIT_UI_SUCCESS_ONLY=PASS");
check(doc.getElementById(SkillUi.IDS.wizardStatus).textContent === "내 견적서로 저장되었습니다.",
  "success copy appears only after commit");
eq(storage.writes.filter((k) => k === "quoteBetaSavedSkill.v1").length, 1, "skill store written once on commit");
const savedId = api.getState().session.approvedSkill.id;

// use the saved skill from the main select
const select = doc.getElementById(SkillUi.IDS.select);
select.value = savedId;
select.dispatch("change");
eq(mounted.applied[mounted.applied.length - 1], savedId, "MY_QUOTATION_USE=YES applies the skill to the form");
clickAction(doc, "wiz-write");
check(mounted.applied.length >= 2, "write button re-applies the active skill");

// builtin fallback: choosing the builtin option clears the skill and writes nothing new
select.value = "";
select.dispatch("change");
eq(mounted.applied[mounted.applied.length - 1], null, "BUILTIN_FALLBACK=PASS without a skill");
eq(api.getState().activeSkillId, null, "no active skill after builtin choice");

// management: rename / default / delete with confirmation
const listysicsBefore = mounted.toasts.length;
doc.getElementById(SkillUi.IDS.manageToggle).click();
check(doc.getElementById(SkillUi.IDS.managePanel).hidden === false, "MY_QUOTATION_LIST=PASS management opens");
clickAction(doc, "skill-rename:" + savedId);
setValue(doc, "skill-rename-" + savedId, "테스트상사 일반 견적서 v2");
clickAction(doc, "skill-rename-save:" + savedId);
check(SkillStore.getSkill(SkillStore.readStore(storage), savedId).name === "테스트상사 일반 견적서 v2", "MY_QUOTATION_RENAME=PASS");
clickAction(doc, "skill-default:" + savedId);
check(SkillStore.defaultSkill(SkillStore.readStore(storage)).id === savedId, "MY_QUOTATION_DEFAULT=PASS set");
clickAction(doc, "skill-default-clear");
check(SkillStore.defaultSkill(SkillStore.readStore(storage)) === null, "MY_QUOTATION_DEFAULT=PASS cleared");
clickAction(doc, "skill-delete:" + savedId);
check(SkillStore.getSkill(SkillStore.readStore(storage), savedId) === null, "MY_QUOTATION_DELETE=PASS");
check(SkillStore.defaultSkill(SkillStore.readStore(storage)) === null, "default deletion falls back safely");
check(mounted.toasts.length > listysicsBefore, "management actions announce");

// cancel path leaves nothing stored
const mounted2 = mount();
mounted2.doc.getElementById(SkillUi.IDS.register).click();
mounted2.doc.getElementById(SkillUi.IDS.file).files = [{ name: "x.pdf", type: "application/pdf", size: 100 }];
mounted2.doc.getElementById(SkillUi.IDS.file).dispatch("change");
mounted2.doc.getElementById(SkillUi.IDS.wizardCancel).click();
check(mounted2.doc.getElementById(SkillUi.IDS.wizard).hidden === true, "cancel closes the wizard");
check(mounted2.doc.activeElement === mounted2.doc.getElementById(SkillUi.IDS.register), "cancel returns focus to the trigger");
eq(mounted2.storage.writes.length, 0, "cancel leaves no stored artifacts");

/* ── formValuesFromSkill: 회사 기본값만, 건별값 없음 ── */

const stored = SkillStore.getSkill(SkillStore.readStore(storage), savedId);
check(stored === null, "deleted skill is gone");
const builtin = Template.serializeTemplate(Template.builtInTemplate());
const pendingForm = Skill.buildSkill({
  id: "skill-form", name: "S",
  fixedDefaults: {
    sender: { company: "C", rep: "R", bizNo: "B", address: "A", phone: "P", email: "E", presetId: "saved-skill" },
    validDays: 45, taxMode: "INCLUSIVE", memo: "MM"
  },
  variableSchema: { recipient: true, quoteNo: true, issueDate: true, items: true, memo: true, taxMode: true },
  internalTemplate: builtin,
  provenance: { sourceKind: "file", sourceName: "f", sourceRef: "", capturedAt: NOW, warnings: [], unknowns: [], evidence: [] },
  approval: null, createdAt: NOW, updatedAt: NOW
});
const approvedForm = Skill.buildSkill(Object.assign({}, pendingForm, {
  approval: {
    schemaVersion: 1, status: "approved", skillFingerprint: pendingForm.fingerprint,
    approvedBy: "local-owner", approvedAt: NOW, approvalRef: ""
  }
}));
const formValues = SkillUi.formValuesFromSkill(approvedForm);
eq(formValues.sender.company, "C", "form values carry the company default");
eq(formValues.validDays, 45, "form values carry validDays");
eq(formValues.taxMode, "INCLUSIVE", "form values carry taxMode");
eq(formValues.memo, "MM", "form values carry memo");
check(!("recipient" in formValues) && !("items" in formValues), "form values never carry per-quote facts");
check(SkillUi.formValuesFromSkill(null) === null, "formValuesFromSkill rejects empty input");

/* ── 접근성/모바일 계약 (열린 wizard 기준) ── */

const a11yMount = mount();
a11yMount.doc.getElementById(SkillUi.IDS.register).click();
a11yMount.doc.getElementById(SkillUi.IDS.file).files = [{ name: "a.pdf", type: "application/pdf", size: 100 }];
a11yMount.doc.getElementById(SkillUi.IDS.file).dispatch("change");
const wizardButtons = a11yMount.doc.getElementById(SkillUi.IDS.wizardBody).querySelectorAll("button");
check(wizardButtons.length > 0, "wizard exposes real buttons");
wizardButtons.forEach((button) => {
  check(button.getAttribute("type") === "button", "wizard buttons are explicit buttons");
  check((button.attributes.class || "").includes("btn"), "wizard buttons reuse the 44px btn class");
});
check(doc.getElementById(SkillUi.IDS.wizardStatus).getAttribute("role") === "status", "wizard status is announced");
check(doc.getElementById(SkillUi.IDS.wizardTitle).getAttribute("tabindex") === "-1", "step title receives focus");
check(doc.getElementById(SkillUi.IDS.select).getAttribute("aria-describedby") === SkillUi.IDS.status,
  "skill select is described");

/* ── 모듈 위생 ── */

const uiSource = fs.readFileSync(path.join(__dirname, "..", "quote-skill-ui.js"), "utf8");
check(!/\.innerHTML\s*=/.test(uiSource), "wizard renders via DOM API only, never innerHTML");
check(!/fetch\(|XMLHttpRequest|WebSocket|EventSource/.test(uiSource), "skill UI performs no network/model call");
check(!/(space-bunny|sensenova|openai|anthropic|kilo\/)/i.test(uiSource), "skill UI owns no provider/model identity");
check(!/secret|apiKey|api_key|password/i.test(uiSource), "skill UI carries no credential material");
check(!/localStorage|sessionStorage|indexedDB/.test(uiSource), "skill UI touches storage only through env");
check(!/완전히 학습했습니다|완벽하게 학습|학습이 완료되었습니다|AI가 배웠습니다|자동으로 분석했습니다/.test(uiSource),
  "LAYOUT_COPY_OVERCLAIM=NO in skill UI");

console.log("quote-skill-ui contracts: PASS");
