const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const Core = require("../quote-core.js");
const Template = require("../quote-template.js");
const TemplateStore = require("../quote-template-store.js");
const SkillStore = require("../quote-skill-store.js");
const Session = require("../quote-registration-session.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) => assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);
const clone = (value) => JSON.parse(JSON.stringify(value));
const NOW = "2026-09-30T04:00:00.000Z";

const SRC_POISON = {
  recipient: "원본거래처-세션검증",
  quoteNo: "Q-SRC-세션검증",
  item: "원본품목-세션검증"
};

/* §12 synthetic fixture: 회사명/제목/5열/특정 열순서/합계라벨/정렬/accent/margin. */
function sourceInfo() {
  return { filename: "synthetic-company-quotation.xlsx", mediaType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", byteSize: 5822 };
}

function customLayout() {
  const content = clone(Template.builtInTemplate().content);
  content.title.text = "테스트상사 견적서";
  content.items.columns = [
    { key: "name", label: "품목명", width: "40%", align: "left" },
    { key: "qty", label: "수량", width: "12%", align: "center" },
    { key: "unitPrice", label: "공급단가", width: "", align: "right" },
    { key: "amount", label: "공급금액", width: "", align: "right" }
  ];
  content.totals.supplyLabel = "공급가액 합계";
  content.totals.grandLabel = "청구 총액";
  content.style.accent = "#123456";
  content.style.numericAlignment = "right";
  content.page = { size: "A4", margin: "20mm", orientation: "portrait" };
  content.mark.text = "SYNTHETIC TEST DATA";
  return content;
}

function modelOutput() {
  return {
    source: { kind: "native_document", filename: "synthetic-company-quotation.xlsx" },
    sender: {
      company: "테스트상사", rep: "최대표", bizNo: "111-22-33333",
      address: "광주", phone: "062-111-2222", email: "t@test.example"
    },
    recipient: { company: SRC_POISON.recipient, person: "담당", address: "서울", email: "s@test.example" },
    quote: { quoteNo: SRC_POISON.quoteNo, issueDate: "2026-09-30", validDays: 30 },
    items: [{ name: SRC_POISON.item, qty: 2, unitPrice: 5000 }],
    tax: { mode: "EXCLUSIVE" },
    memo: "납기 협의",
    evidence: [{ field: "sender.company", snippet: "테스트상사" }],
    warnings: []
  };
}

function sampleDraft() {
  return Core.normalizeDraft({
    schemaVersion: 1,
    meta: { quoteNo: "Q-PREVIEW-9", issueDate: "2026-09-30", validDays: 30, source: "preview" },
    sender: { company: "테스트상사", presetId: "custom" },
    recipient: { company: "미리보기 거래처" },
    items: [{ id: "item-1", name: "미리보기 품목", qty: 1, unitPrice: 1000 }],
    tax: { mode: "EXCLUSIVE", rate: 0.1 },
    memo: ""
  });
}

function fakeStorage(failOnKeys) {
  const map = new Map();
  const writes = [];
  const failing = failOnKeys || {};
  return {
    writes: writes,
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => {
      if (failing[key]) throw new Error("storage quota exceeded: " + key);
      writes.push(key);
      map.set(key, String(value));
    },
    removeItem: (key) => { writes.push("remove:" + key); map.delete(key); }
  };
}

function runFullSession() {
  let started = Session.start(sourceInfo(), { now: NOW });
  check(started.ok === true, "registration starts from the source file");
  let session = started.session;
  eq(session.status, Session.STATUS_TEMPLATE_REVIEW, "wizard opens at layout review");

  const corrected = Session.correctTemplate(session, { name: "테스트상사 견적 양식", content: customLayout() }, { now: NOW });
  check(corrected.ok === true, "layout correction succeeds");
  session = corrected.session;

  const preview = Session.previewTemplate(session, sampleDraft(), { now: NOW });
  check(preview.ok === true, "layout preview renders before approval");
  check(preview.renderModel.template.fallbackReason === "preview_unapproved_candidate", "preview is marked unapproved");

  const tplApproved = Session.approveTemplate(session, {
    id: "tpl-synthetic-company", approvedBy: "local-owner", approvedAt: NOW, approvalRef: "issue-3218"
  }, { now: NOW });
  check(tplApproved.ok === true, "template approves explicitly");
  session = tplApproved.session;
  eq(session.status, Session.STATUS_TEMPLATE_APPROVED, "template approval is a separate explicit step");

  const skillBuilt = Session.buildSkillCandidate(session, {
    modelOutput: modelOutput(),
    sourceMeta: { sourceKind: "file", filename: "synthetic-company-quotation.xlsx", sourceRef: "evidence:synthetic", capturedAt: NOW },
    skillName: "테스트상사 일반 견적서"
  }, { now: NOW });
  check(skillBuilt.ok === true, "approved profile links into skill registration");
  session = skillBuilt.session;
  eq(session.status, Session.STATUS_SKILL_REVIEW, "skill review follows template approval");

  const skillPreview = Session.previewSkill(session, {
    quoteNo: "Q-2026-100", issueDate: "2026-09-30",
    recipient: { company: "미리보기 거래처" },
    items: [{ name: "미리보기 품목", qty: 1, unitPrice: 1000 }]
  }, { now: NOW });
  check(skillPreview.ok === true, "skill preview renders before skill approval");
  check(skillPreview.preview === true, "skill preview is flagged preview-only");

  const skillApproved = Session.approveSkill(session, {
    id: "skill-synthetic-company", approvedBy: "local-owner", now: NOW, approvalRef: "issue-3218"
  }, { now: NOW });
  check(skillApproved.ok === true, "skill approves explicitly and separately");
  return skillApproved.session;
}

/* Full E2E: source -> layout -> approvals -> commit -> repeat. */
const session = runFullSession();
const storage = fakeStorage();
const committed = Session.commit(session,
  { templateStore: TemplateStore.emptyStore(), skillStore: Store_emptySkillStore() },
  storage, { now: NOW });
function Store_emptySkillStore() { return SkillStore.emptyStore(); }
check(committed.ok === true, "atomic commit persists template + skill");
eq(committed.session.status, Session.STATUS_COMMITTED, "session reaches committed");
check(committed.template.approved === true && committed.skill.approved === true, "both approvals land together");
eq(storage.writes.filter((k) => k === TemplateStore.TEMPLATE_STORAGE_KEY).length, 1, "template store written once");
eq(storage.writes.filter((k) => k === SkillStore.STORAGE_KEY).length, 1, "skill store written once");

/* Repeat with the committed approved layout: new facts only. */
const Skill = require("../quote-skill.js");
function repeat(input) {
  return Skill.buildRenderModel(committed.skill, input);
}
const base = repeat({
  quoteNo: "Q-2026-200", issueDate: "2026-10-01",
  recipient: { company: "대한건설" },
  items: [{ name: "배관 40A", qty: 100, unitPrice: 18000 }]
});
check(base.ok === true, "repeat generation works from the committed skill");
eq(base.draft.recipient.company, "대한건설", "NEW_RECIPIENT_APPLIED=YES");
eq(base.draft.items[0].qty, 100, "NEW_ITEM_VALUES_APPLIED=YES");
eq(base.renderModel.template.fingerprint, committed.template.fingerprint, "APPROVED_LAYOUT_REUSED=YES");
eq(base.compiled.templateFingerprint, committed.template.fingerprint, "APPROVED_TEMPLATE_FINGERPRINT_STABLE=YES");
const baseJson = JSON.stringify(base.renderModel);
check(!baseJson.includes(SRC_POISON.recipient), "SOURCE_RECIPIENT_REAPPEARED=NO");
check(!baseJson.includes(SRC_POISON.item), "SOURCE_ITEM_VALUES_REAPPEARED=NO");
check(baseJson.includes("테스트상사 견적서") && baseJson.includes("공급단가") && baseJson.includes("청구 총액"),
  "approved custom title/columns/labels render on repeat");

const again = repeat({
  quoteNo: "Q-2026-200", issueDate: "2026-10-01",
  recipient: { company: "대한건설" },
  items: [{ name: "배관 40A", qty: 100, unitPrice: 18000 }]
});
assert.deepStrictEqual(again.renderModel, base.renderModel, "SAME_INPUT_SAME_RENDER=YES");
assert.deepStrictEqual(again.draft, base.draft, "same input yields the same draft");

const numericOnly = repeat({
  quoteNo: "Q-2026-201", issueDate: "2026-10-02",
  recipient: { company: "대한건설" },
  items: [{ name: "배관 40A", qty: 50, unitPrice: 12000 }]
});
eq(numericOnly.compiled.skillFingerprint, base.compiled.skillFingerprint, "numeric-only edit reuses the compiled skill");
check(numericOnly.renderModel.totals.grandText !== base.renderModel.totals.grandText, "QuoteCore recalculates");

const recipientOnly = repeat({
  quoteNo: "Q-2026-202", issueDate: "2026-10-03",
  recipient: { company: "미래산업" },
  items: [{ name: "배관 40A", qty: 100, unitPrice: 18000 }]
});
eq(recipientOnly.draft.recipient.company, "미래산업", "recipient-only edit applies");

const itemOnly = repeat({
  quoteNo: "Q-2026-203", issueDate: "2026-10-04",
  recipient: { company: "대한건설" },
  items: [{ name: "밸브 20A", qty: 4, unitPrice: 88000 }]
});
eq(itemOnly.draft.items[0].name, "밸브 20A", "item-only edit applies");

/* Structural zero-call proof: repeat signature carries no source/model input. */
eq(Skill.buildRenderModel.length, 2, "MODEL_CALLS_ON_REPEAT=0 / SOURCE_REANALYSIS_ON_REPEAT=0: repeat takes (skill, input) only");

/* Tamper rejections on both approvals. */
const tamperedTemplate = clone(session.approvedTemplate);
tamperedTemplate.content.title.text = "변조";
check(Template.normalizeTemplate(tamperedTemplate) === null ||
      Template.normalizeTemplate(tamperedTemplate).fingerprint !== session.approvedTemplate.fingerprint,
  "tampered template approval rejected");
const staleSkill = clone(session.approvedSkill);
staleSkill.fixedDefaults.memo = "승인 후 변조";
eq(Skill.normalizeSkill(staleSkill), null, "tampered skill approval rejected");

/* Unapproved template can never enter skill registration. */
const fresh = Session.start(sourceInfo(), { now: NOW }).session;
eq(Session.buildSkillCandidate(fresh, { modelOutput: modelOutput() }, { now: NOW }).code,
  "template_not_approved_for_skill", "skill registration requires the approved template first");

/* Cancel leaves no stored artifacts. */
const cancelStorage = fakeStorage();
const cancelled = Session.cancel(fresh);
eq(cancelled.session.status, Session.STATUS_CANCELLED, "cancel reaches cancelled");
eq(cancelStorage.writes.length, 0, "cancel leaves no stored artifacts");

/* Preview/correction/approval phases never touch storage. */
const spyStorage = fakeStorage();
const s1 = Session.start(sourceInfo(), { now: NOW }).session;
Session.correctTemplate(s1, { name: "x" }, { now: NOW });
Session.previewTemplate(s1, sampleDraft(), { now: NOW });
eq(spyStorage.writes.length, 0, "preview/correction perform zero storage mutation");

/* Atomicity: skill write failure rolls the template write back. */
const failingStorage = fakeStorage({ [SkillStore.STORAGE_KEY]: true });
const doomed = Session.commit(session,
  { templateStore: TemplateStore.emptyStore(), skillStore: SkillStore.emptyStore() },
  failingStorage, { now: NOW });
check(doomed.ok === false, "commit fails when the skill write fails");
check(doomed.rolledBack === true, "ATOMIC_REGISTRATION_COMMIT rolls back on partial failure");
eq(failingStorage.getItem(TemplateStore.TEMPLATE_STORAGE_KEY), null, "template write is rolled back");
eq(failingStorage.getItem(SkillStore.STORAGE_KEY), null, "skill key stays untouched");

/* Failed skill commit (duplicate id) leaves the template store unwritten. */
const prefilledSkill = SkillStore.saveApprovedSkill(SkillStore.emptyStore(), session.approvedSkill).store;
const dupStorage = fakeStorage();
const dup = Session.commit(session,
  { templateStore: TemplateStore.emptyStore(), skillStore: prefilledSkill },
  dupStorage, { now: NOW });
check(dup.ok === false, "duplicate skill id fails the commit");
eq(dupStorage.getItem(TemplateStore.TEMPLATE_STORAGE_KEY), null, "PARTIAL_STATE_ON_FAILURE=NO");

/* Module hygiene. */
const sessionSource = fs.readFileSync(path.join(__dirname, "..", "quote-registration-session.js"), "utf8");
check(!/fetch\(|XMLHttpRequest|WebSocket|EventSource/.test(sessionSource), "session performs no network/model call");
check(!/(space-bunny|sensenova|openai|anthropic|kilo\/)/i.test(sessionSource), "session owns no provider/model identity");
check(!/secret|apiKey|api_key|token|password/i.test(sessionSource), "session carries no credential material");
check(!/localStorage|sessionStorage|indexedDB/.test(sessionSource), "session touches no browser storage directly");
check(!/완전히 학습했습니다|완벽하게 학습|학습이 완료되었습니다|AI가 배웠습니다/.test(sessionSource), "no overclaimed copy");

console.log("quote-registration-session contracts: PASS");
