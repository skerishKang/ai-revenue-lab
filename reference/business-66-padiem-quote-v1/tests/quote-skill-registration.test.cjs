const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const Core = require("../quote-core.js");
const Template = require("../quote-template.js");
const Extraction = require("../quote-extraction.js");
const Skill = require("../quote-skill.js");
const Candidate = require("../quote-skill-candidate.js");
const Store = require("../quote-skill-store.js");
const Registration = require("../quote-skill-registration.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) => assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);
const clone = (value) => JSON.parse(JSON.stringify(value));
const NOW = "2026-09-30T02:00:00.000Z";

const POISON = {
  recipient: "원본거래처-등록검증",
  quoteNo: "Q-SOURCE-등록검증",
  item: "원본품목-등록검증"
};

/* Synthetic model output shaped like the #3205 F02 scanned quotation facts. */
function modelOutput(overrides) {
  return Object.assign({
    source: { kind: "image", filename: "f02-scanned-quotation.png" },
    sender: {
      company: "주식회사 테스트상사", rep: "김대표", bizNo: "000-00-00000",
      address: "광주광역시 테스트구 견적로 123", phone: "062-000-0000", email: "quote@test.example"
    },
    recipient: { company: POISON.recipient, person: "이담당", address: "서울", email: "b@test.example" },
    quote: { quoteNo: POISON.quoteNo, issueDate: "2026-03-03", validDays: 30 },
    items: [
      { name: POISON.item, qty: 12, unitPrice: 9800 },
      { name: "알루미늄 브래킷", qty: 24, unitPrice: 2200 }
    ],
    tax: { mode: "EXCLUSIVE" },
    memo: "납기 협의",
    evidence: [{ field: "quote.quoteNo", page: 1, snippet: POISON.quoteNo, confidence: 0.9 }],
    warnings: []
  }, overrides || {});
}

function sourceMeta(overrides) {
  return Object.assign({
    sourceKind: "file",
    filename: "f02-scanned-quotation.png",
    sourceRef: "evidence:f02-synthetic",
    capturedAt: NOW
  }, overrides || {});
}

function register(overrides, options) {
  const input = Object.assign({
    modelOutput: modelOutput(),
    sourceMeta: sourceMeta(),
    templateDecision: { mode: "builtin" },
    skillName: "우리회사 일반 견적서"
  }, overrides || {});
  return Registration.buildRegistrationCandidate(input, Object.assign({ now: NOW }, options || {}));
}

function approveCandidate(candidate, id) {
  const approved = Candidate.approveCandidate(candidate, {
    id: id || "skill-general", approvedBy: "local-owner", now: NOW, approvalRef: "issue-3218"
  });
  check(approved.ok === true, "registration candidate approves explicitly");
  check(approved.skill.approved === true, "EXPLICIT_SAVED_QUOTE_SKILL_APPROVAL=YES");
  return approved.skill;
}

function freshInput(overrides) {
  return Object.assign({
    quoteNo: "Q-2026-010",
    issueDate: "2026-09-30",
    recipient: { company: "대한건설", person: "박담당", address: "서울", email: "buyer@example.com" },
    items: [{ id: "item-1", name: "배관 40A", qty: 50, unitPrice: 120000 }]
  }, overrides || {});
}

/* 1. extraction -> candidate happy path with a real review model. */
const ready = register();
check(ready.ok === true, "existing quotation registers to a candidate");
eq(ready.code, "registration_candidate_ready", "registration seam reports its own code");
check(ready.candidate.status === "candidate", "registration output is review-only, never active");
check(ready.review && ready.review.candidateId === ready.candidate.candidateId, "review model accompanies the candidate");
eq(ready.review.source.name, "f02-scanned-quotation.png", "source provenance reaches the review");
check(ready.review.alwaysReusedOrDefault.length > 0, "review shows always-reused defaults");
check(ready.review.changesEachQuote.length > 0, "review shows per-quotation variables");
check(ready.review.calculatedByCore.length === 5, "review shows QuoteCore-calculated fields");
eq(ready.correctionsApplied, [], "no manual correction is recorded when extraction is complete");

/* 2. fixed/default mapping. */
eq(ready.candidate.fixedDefaults.sender.company, "주식회사 테스트상사", "supplier identity becomes a fixed default");
eq(ready.candidate.fixedDefaults.validDays, 30, "validDays becomes a fixed default");
eq(ready.candidate.fixedDefaults.taxMode, "EXCLUSIVE", "default tax mode is stored");
eq(ready.candidate.fixedDefaults.memo, "납기 협의", "default memo is stored");

/* 3. variable mapping: source case values must never freeze into the skill. */
eq(ready.candidate.variableSchema.recipient, true, "recipient stays variable");
eq(ready.candidate.variableSchema.quoteNo, true, "quote number stays variable");
eq(ready.candidate.variableSchema.issueDate, true, "issue date stays variable");
eq(ready.candidate.variableSchema.items, true, "items stay variable");
const candidateJson = JSON.stringify(ready.candidate);
const frozenJson = JSON.stringify({ fixed: ready.candidate.fixedDefaults, schema: ready.candidate.variableSchema });
check(!frozenJson.includes(POISON.recipient), "SOURCE_RECIPIENT_FROZEN_BY_ACCIDENT=NO");
check(!frozenJson.includes(POISON.quoteNo), "source quote number is not frozen into defaults");
check(!frozenJson.includes(POISON.item), "SOURCE_ITEM_VALUES_FROZEN_BY_ACCIDENT=NO");
check(candidateJson.includes(POISON.quoteNo), "source evidence snippet survives as bounded review provenance");

/* 4. QuoteCore calculated exclusion. */
["lineAmounts", "supplyTotal", "vatAmount", "grandTotal", "validUntil"].forEach((key) => {
  check(!candidateJson.includes('"' + key + '"'), `calculated field ${key} is never learned into the skill`);
});
check(!("totals" in Skill.buildRenderModel(approveCandidate(ready.candidate), freshInput()).draft),
  "untrusted source totals never enter QuoteDraft; QuoteCore derives every amount");

/* 5. layout/template mapping: builtin vs approved clone, no auto learning. */
eq(ready.candidate.internalTemplate.id, Template.BUILTIN_TEMPLATE_ID, "MVP registration reuses the built-in document behavior explicitly");
const builtinContent = clone(Template.builtInTemplate().content);
const cloneProfile = Template.buildProfile({
  id: "tpl-company", name: "tpl-company", builtin: false, isDefault: false,
  approval: {
    schemaVersion: 1, status: "approved",
    contentFingerprint: Template.templateFingerprint(builtinContent),
    approvedBy: "central-cto", approvedAt: NOW
  },
  createdAt: NOW, updatedAt: NOW, content: builtinContent
});
check(Template.isApprovedProfile(cloneProfile) === true, "test setup: approved clone profile is approved");
const withClone = register({ templateDecision: { mode: "approved-template", template: Template.serializeTemplate(cloneProfile) } });
check(withClone.ok === true, "an approved clone can be chosen as the document behavior");
eq(withClone.candidate.internalTemplate.id, "tpl-company", "approved clone identity is preserved");
const unapprovedRaw = Template.serializeTemplate(Template.builtInTemplate());
unapprovedRaw.id = "tpl-unapproved";
unapprovedRaw.builtin = false;
eq(register({ templateDecision: { mode: "approved-template", template: unapprovedRaw } }).code,
  "template_not_approved", "UNAPPROVED template cannot back a registration");
eq(register({ templateDecision: { mode: "auto-learn" } }).code,
  "unsupported_template_decision", "no automatic layout learning is claimed");

/* 6. manual correction fills extraction gaps honestly. */
const missingCompany = modelOutput();
missingCompany.sender = { company: null, rep: "김대표", bizNo: null, address: null, phone: null, email: null };
eq(register({ modelOutput: missingCompany }).code,
  "sender_company_requires_correction", "missing company fails closed instead of fabricating");
const correctedCompany = register({
  modelOutput: missingCompany,
  corrections: { sender: { company: "주식회사 테스트상사" } }
});
check(correctedCompany.ok === true, "manual correction completes the company fact");
check(correctedCompany.correctionsApplied.includes("sender.company"), "corrections are recorded");
check(correctedCompany.review.source.warnings.some((w) => w === "manual_correction:sender.company"),
  "corrections stay visible in review warnings");

const missingDays = modelOutput();
missingDays.quote = { quoteNo: null, issueDate: null, validDays: null };
eq(register({ modelOutput: missingDays }).code,
  "valid_days_requires_correction", "missing validDays fails closed (F09 trap)");
check(register({ modelOutput: missingDays, corrections: { validDays: 30 } }).ok === true,
  "manual correction completes validDays");

const badTax = modelOutput();
badTax.tax = { mode: "WEIRD" };
eq(register({ modelOutput: badTax }).code,
  "tax_mode_requires_correction", "unknown tax wording fails closed until the user picks a VAT mode");
const fixedTax = register({ modelOutput: badTax, corrections: { taxMode: "EXCLUSIVE" } });
check(fixedTax.ok === true, "manual tax mode correction completes registration");
check(fixedTax.review.source.warnings.includes("manual_correction:taxMode"),
  "tax mode correction stays visible in review");

/* 7. malformed model output fails closed with extraction codes. */
eq(register({ modelOutput: null }).ok, false, "null model output fails closed");
eq(register({ modelOutput: { source: { kind: "hologram" } } }).code,
  "unsupported_source_kind", "unsupported source kinds fail closed");
const totalsModel = modelOutput();
totalsModel.totals = { grand: "999999" };
check(register({ modelOutput: totalsModel }).ok === true, "unknown model keys do not break registration");
check(!JSON.stringify(register({ modelOutput: totalsModel }).candidate).includes("999999"),
  "SOURCE_AMOUNTS_FROZEN_BY_ACCIDENT=NO");

/* 8. approval is explicit and fingerprint-bound end to end. */
const skill = approveCandidate(ready.candidate);
eq(skill.calculationAuthority, "quote-core", "QUOTECORE_CALCULATION_AUTHORITY=YES");
const edited = Candidate.editCandidate(ready.candidate, { fixedDefaults: Object.assign({}, ready.candidate.fixedDefaults, { memo: "수정한 기본 비고" }) }, { now: NOW });
check(edited.ok === true, "review correction produces a new candidate");
check(edited.candidate.skillFingerprint !== ready.candidate.skillFingerprint, "candidate edit changes the fingerprint");
const reapproved = Candidate.approveCandidate(edited.candidate, { id: "skill-general-2", approvedBy: "local-owner", now: NOW });
check(reapproved.ok === true, "corrected candidate approves under its own fingerprint");
const stale = clone(skill);
stale.fixedDefaults.memo = "승인 후 변조";
eq(Skill.normalizeSkill(stale), null, "STALE_APPROVAL_REUSE=0");

/* 9. store lifecycle on the registration-built skill. */
function fakeStorage() {
  const map = new Map();
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => { map.set(key, String(value)); },
    removeItem: (key) => { map.delete(key); }
  };
}
let store = Store.emptyStore();
const saved = Store.saveApprovedSkill(store, skill);
check(saved.ok === true, "approved registration skill saves");
store = saved.store;
eq(Store.saveApprovedSkill(store, skill).code, "duplicate_skill_id", "duplicate skill id fails closed");
const pendingSkill = Skill.buildSkill({
  id: "skill-pending", name: "미승인", fixedDefaults: ready.candidate.fixedDefaults,
  variableSchema: ready.candidate.variableSchema, internalTemplate: ready.candidate.internalTemplate,
  provenance: ready.candidate.provenance, approval: null, createdAt: NOW, updatedAt: NOW
});
eq(Store.saveApprovedSkill(store, pendingSkill).code, "skill_not_approved", "UNAPPROVED_SAVED_QUOTE_SKILL_ACTIVATION=0");
const defaulted = Store.setDefaultSkill(store, skill.id);
check(defaulted.ok === true, "default skill can be set");
store = defaulted.store;
const renamed = Store.renameSkill(store, skill.id, "우리회사 일반 견적서 v2", { now: NOW });
check(renamed.ok === true, "skill rename works");
store = renamed.store;
const deleted = Store.deleteSkill(store, skill.id);
check(deleted.ok === true, "skill delete works");
check(Store.defaultSkill(deleted.store) === null, "deleting the default skill falls back safely");
eq(Store.normalizeStore({ schemaVersion: 999, skills: [] }).skills.length, 0, "unknown schema versions fail safe");
eq(Store.normalizeStore(null).skills.length, 0, "malformed storage fails safe");
const storage = fakeStorage();
check(Store.writeStore(storage, deleted.store) === true, "store persists");
check(Store.readStore(storage).skills.length === 0, "store round-trips");

/* 10-11. repeat generation A/B/C + determinism through the registered skill. */
const first = Skill.buildRenderModel(skill, freshInput());
check(first.ok === true, "registered skill renders from new structured facts");
eq(first.draft.sender.company, "주식회사 테스트상사", "approved company defaults are reused");
eq(first.draft.recipient.company, "대한건설", "new recipient facts are applied");
const skillJson = JSON.stringify(skill);
const skillFrozenJson = JSON.stringify({ fixed: skill.fixedDefaults, schema: skill.variableSchema });
check(!skillFrozenJson.includes(POISON.recipient) && !skillFrozenJson.includes(POISON.quoteNo) && !skillFrozenJson.includes(POISON.item),
  "compiled skill freezes no source case values");

const same = Skill.buildRenderModel(skill, freshInput());
assert.deepStrictEqual(same.draft, first.draft, "same structured input yields the same QuoteDraft");
assert.deepStrictEqual(same.renderModel, first.renderModel, "SAME_INPUT_SAME_RENDER=YES");

const numeric = Skill.buildRenderModel(skill, freshInput({ items: [{ id: "item-1", name: "배관 40A", qty: 80, unitPrice: 135000 }] }));
check(numeric.ok === true, "numeric-only regeneration succeeds without source reanalysis");
eq(numeric.compiled.skillFingerprint, first.compiled.skillFingerprint, "NUMERIC_ONLY_EDIT_REUSES_COMPILED_SKILL=YES");
check(numeric.renderModel.totals.grandText !== first.renderModel.totals.grandText, "QuoteCore recalculates totals deterministically");

const recipientOnly = Skill.buildRenderModel(skill, freshInput({
  recipient: { company: "미래산업", person: "이담당", address: "부산", email: "future@example.com" }
}));
eq(recipientOnly.compiled.skillFingerprint, first.compiled.skillFingerprint, "RECIPIENT_ONLY_EDIT_REUSES_COMPILED_SKILL=YES");
eq(recipientOnly.draft.recipient.company, "미래산업", "source recipient never resurfaces");

const itemOnly = Skill.buildRenderModel(skill, freshInput({
  items: [{ id: "item-1", name: "밸브 20A", qty: 4, unitPrice: 88000 }]
}));
eq(itemOnly.compiled.skillFingerprint, first.compiled.skillFingerprint, "ITEM_ONLY_EDIT_REUSES_COMPILED_SKILL=YES");
eq(itemOnly.draft.items[0].name, "밸브 20A", "source items never resurface");

/* 12. zero model calls: structural + static proof. */
eq(Skill.buildRenderModel.length, 2, "repeat path takes (skill, input) only: no source/model parameter exists");
const registrationSource = fs.readFileSync(path.join(__dirname, "..", "quote-skill-registration.js"), "utf8");
check(!/fetch\(|XMLHttpRequest|WebSocket|EventSource/.test(registrationSource), "registration performs no network/model call");
check(!/(space-bunny|sensenova|openai|anthropic|kilo\/)/i.test(registrationSource), "registration owns no provider/model identity");
check(!/secret|apiKey|api_key|token|password/i.test(registrationSource), "registration carries no credential material");
check(!/FileReader|FormData|indexedDB|localStorage|sessionStorage/.test(registrationSource), "RAW_SOURCE_FILE_BROWSER_PERSISTENCE=0");

console.log("quote-skill-registration contracts: PASS");
