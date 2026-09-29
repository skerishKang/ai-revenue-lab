const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const Core = require("../quote-core.js");
const Template = require("../quote-template.js");
const Skill = require("../quote-skill.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) => assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);
const clone = (value) => JSON.parse(JSON.stringify(value));
const NOW = "2026-09-29T11:00:00.000Z";

function fixedDefaults() {
  return {
    sender: {
      company: "한빛설비",
      rep: "김대표",
      bizNo: "123-45-67890",
      address: "광주광역시",
      phone: "062-000-0000",
      email: "quote@example.com",
      presetId: "saved-skill"
    },
    validDays: 30,
    taxMode: "EXCLUSIVE",
    memo: "발주 후 일정 협의"
  };
}

function provenance() {
  return {
    sourceKind: "file",
    sourceName: "our-real-quotation.pdf",
    sourceRef: "source:synthetic-f02",
    capturedAt: NOW,
    warnings: [],
    unknowns: [],
    evidence: [{ label: "sender", value: "한빛설비" }]
  };
}

function approvedSkill() {
  const base = {
    id: "skill-general",
    name: "우리회사 일반 견적서",
    fixedDefaults: fixedDefaults(),
    variableSchema: { recipient: true, quoteNo: true, issueDate: true, items: true, memo: true, taxMode: true },
    internalTemplate: Template.serializeTemplate(Template.builtInTemplate()),
    provenance: provenance(),
    approval: null,
    createdAt: NOW,
    updatedAt: NOW
  };
  const unapproved = Skill.buildSkill(base);
  check(unapproved && unapproved.approved === false, "a skill is not active before explicit approval");
  return Skill.buildSkill(Object.assign({}, base, {
    approval: {
      schemaVersion: 1,
      status: "approved",
      skillFingerprint: unapproved.fingerprint,
      approvedBy: "central-cto",
      approvedAt: NOW,
      approvalRef: "issue-3218"
    }
  }));
}

function input(overrides) {
  return Object.assign({
    quoteNo: "Q-2026-001",
    issueDate: "2026-09-29",
    recipient: { company: "대한건설", person: "박담당", address: "서울", email: "buyer@example.com" },
    items: [{ id: "item-1", name: "배관 40A", qty: 50, unitPrice: 120000 }],
    taxMode: "EXCLUSIVE",
    memo: "이번 건 납기 협의"
  }, overrides || {});
}

const skill = approvedSkill();
check(skill && skill.approved === true, "EXPLICIT_SAVED_QUOTE_SKILL_APPROVAL=YES");
eq(skill.calculationAuthority, "quote-core", "QuoteCore remains the calculation authority");
eq(skill.rendererContract, "quote-template-renderer.v1", "the existing template renderer remains the render contract");
eq(skill.provenance.sourceName, "our-real-quotation.pdf", "source provenance is retained as metadata");

const compile = Skill.compileSkill(skill);
check(compile.ok === true, "APPROVED_SKILL_COMPILED_FOR_REUSE=YES");
eq(compile.compiled.executionContract.structuredRepeatGenerationModelCalls, 0, "STRUCTURED_REPEAT_GENERATION_MODEL_CALLS=0");
eq(compile.compiled.executionContract.sourceDocumentReanalysisPerRepeat, 0, "SOURCE_DOCUMENT_REANALYSIS=0");
eq(compile.compiled.executionContract.fullDocumentAiRegenerationPerRepeat, 0, "FULL_DOCUMENT_AI_REGENERATION=0");
eq(compile.compiled.executionContract.quoteCoreRecalculationModelCalls, 0, "QUOTECORE_RECALCULATION_MODEL_CALLS=0");
eq(compile.compiled.executionContract.rendererModelCalls, 0, "RENDERER_MODEL_CALLS=0");

const first = Skill.buildRenderModel(skill, input());
check(first.ok === true, "structured repeat generation produces a render model");
eq(first.draft.sender.company, "한빛설비", "approved company defaults are reused");
eq(first.draft.recipient.company, "대한건설", "new recipient facts are applied");
eq(first.draft.items[0].qty, 50, "new item quantity is applied");
eq(first.draft.items[0].unitPrice, 120000, "new item unit price is applied");
eq(first.draft.meta.source, "saved-quote-skill", "repeat generation is marked as Saved Quote Skill execution");

const same = Skill.buildRenderModel(skill, input());
eq(same.draft, first.draft, "same structured input yields the same QuoteDraft");
eq(same.renderModel, first.renderModel, "SAME_INPUT_SAME_RENDER=YES");
eq(same.compiled.skillFingerprint, first.compiled.skillFingerprint, "compiled skill identity is stable");
eq(same.compiled.templateFingerprint, first.compiled.templateFingerprint, "compiled internal template identity is stable");

const numeric = Skill.buildRenderModel(skill, input({
  items: [{ id: "item-1", name: "배관 40A", qty: 80, unitPrice: 135000 }]
}));
check(numeric.ok === true, "numeric-only regeneration succeeds");
eq(numeric.compiled.skillFingerprint, first.compiled.skillFingerprint, "NUMERIC_ONLY_EDIT_REUSES_COMPILED_SKILL=YES");
eq(numeric.compiled.templateFingerprint, first.compiled.templateFingerprint, "numeric-only edit reuses the same compiled template");
check(numeric.renderModel.totals.grandText !== first.renderModel.totals.grandText, "QuoteCore recalculates totals after numeric edits");

const recipientOnly = Skill.buildRenderModel(skill, input({
  recipient: { company: "미래산업", person: "이담당", address: "부산", email: "future@example.com" }
}));
eq(recipientOnly.compiled.skillFingerprint, first.compiled.skillFingerprint, "RECIPIENT_ONLY_EDIT_REUSES_COMPILED_SKILL=YES");
eq(recipientOnly.draft.recipient.company, "미래산업", "source recipient is never frozen into the skill");

const itemOnly = Skill.buildRenderModel(skill, input({
  items: [{ id: "item-1", name: "밸브 20A", qty: 4, unitPrice: 88000 }]
}));
eq(itemOnly.compiled.skillFingerprint, first.compiled.skillFingerprint, "ITEM_ONLY_EDIT_REUSES_COMPILED_SKILL=YES");
eq(itemOnly.draft.items[0].name, "밸브 20A", "new item facts replace source-case facts");

const badRecipientFreeze = Skill.normalizeFixedDefaults(Object.assign({}, fixedDefaults(), {
  recipient: { company: "원본 거래처" }
}));
eq(badRecipientFreeze, null, "SOURCE_RECIPIENT_FROZEN_BY_ACCIDENT=NO");
const badItemFreeze = Skill.normalizeFixedDefaults(Object.assign({}, fixedDefaults(), {
  items: [{ name: "원본 품목", qty: 1, unitPrice: 1 }]
}));
eq(badItemFreeze, null, "SOURCE_ITEM_VALUES_FROZEN_BY_ACCIDENT=NO");
const badAmountFreeze = Skill.normalizeFixedDefaults(Object.assign({}, fixedDefaults(), { grandTotal: 999999 }));
eq(badAmountFreeze, null, "SOURCE_AMOUNTS_FROZEN_BY_ACCIDENT=NO");

const missingCoreVariable = Skill.normalizeVariableSchema({
  recipient: false, quoteNo: true, issueDate: true, items: true, memo: true, taxMode: true
});
eq(missingCoreVariable, null, "recipient cannot be reclassified as fixed");

const unapproved = clone(skill);
unapproved.approval = null;
const normalizedUnapproved = Skill.normalizeSkill(unapproved);
check(normalizedUnapproved && normalizedUnapproved.approved === false, "an unapproved skill can be represented for review");
eq(Skill.compileSkill(unapproved).code, "skill_not_approved", "UNAPPROVED_SAVED_QUOTE_SKILL_ACTIVATION=0");

const tampered = clone(skill);
tampered.fixedDefaults.sender.company = "변조 회사";
eq(Skill.normalizeSkill(tampered), null, "content change invalidates skill approval by fingerprint binding");

const invalidInput = Skill.buildRenderModel(skill, {
  quoteNo: "Q-X",
  issueDate: "2026-09-29",
  recipient: { company: "" },
  items: []
});
check(invalidInput.ok === false, "invalid structured input fails closed instead of inheriting demo business facts");

const invalidDate = Skill.buildRenderModel(skill, input({ issueDate: "2026-99-99" }));
check(invalidDate.ok === false, "invalid calendar dates fail closed before QuoteCore rendering");

const source = fs.readFileSync(path.join(__dirname, "..", "quote-skill.js"), "utf8");
check(!/fetch\(|XMLHttpRequest|WebSocket/.test(source), "repeat-generation Skill code performs no network/model call");
check(!/(space-bunny|sensenova|openai|anthropic|kilo\/)/i.test(source), "browser Skill code owns no provider/model identity");
check(!/FileReader|FormData|indexedDB/i.test(source), "RAW_SOURCE_FILE_BROWSER_PERSISTENCE=0");

console.log("quote-skill contracts: PASS");
