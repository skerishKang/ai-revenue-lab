const assert = require("node:assert");
const Template = require("../quote-template.js");
const Candidate = require("../quote-skill-candidate.js");
const Skill = require("../quote-skill.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) => assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);
const NOW = "2026-09-29T11:00:00.000Z";

function payload(overrides) {
  return Object.assign({
    schemaVersion: 1,
    candidateId: "skill-cand-1",
    name: "우리회사 일반 견적서",
    fixedDefaults: {
      sender: { company: "한빛설비", rep: "김대표", bizNo: "123-45-67890", address: "광주", phone: "062-000-0000", email: "", presetId: "saved-skill" },
      validDays: 30,
      taxMode: "EXCLUSIVE",
      memo: "기본 비고"
    },
    variableSchema: { recipient: true, quoteNo: true, issueDate: true, items: true, memo: true, taxMode: true },
    internalTemplate: Template.serializeTemplate(Template.builtInTemplate()),
    provenance: {
      sourceKind: "file",
      sourceName: "our-real-quotation.pdf",
      sourceRef: "source:f02",
      capturedAt: NOW,
      warnings: ["도장 위치 미확인"],
      unknowns: ["담당자 직함"],
      evidence: [{ label: "회사명", value: "한빛설비" }]
    }
  }, overrides || {});
}

const ready = Candidate.normalizeCandidate(payload(), { now: NOW });
check(ready.ok === true, "SOURCE_TO_SKILL_CANDIDATE=PASS");
eq(Candidate.isApprovedCandidate(ready.candidate), false, "candidate is never implicitly approved");

const review = Candidate.buildReviewModel(ready.candidate);
check(review.alwaysReusedOrDefault.some((x) => x.key === "sender.company"), "fixed/default company facts are reviewable");
check(review.changesEachQuote.some((x) => x.key === "recipient" && x.required === true), "recipient is explicitly variable");
check(review.changesEachQuote.some((x) => x.key === "items" && x.required === true), "items are explicitly variable");
eq(review.calculatedByCore.map((x) => x.key), Candidate.CALCULATED_FIELDS, "calculated fields stay locked to QuoteCore");

const edited = Candidate.editCandidate(ready.candidate, {
  fixedDefaults: Object.assign({}, ready.candidate.fixedDefaults, { memo: "수정한 기본 비고" }),
  variableSchema: Object.assign({}, ready.candidate.variableSchema, { memo: false })
}, { now: NOW });
check(edited.ok === true, "FIXED_DEFAULT_VARIABLE_CLASSIFICATION_EDITABLE=YES");
eq(edited.candidate.fixedDefaults.memo, "수정한 기본 비고", "review can correct reusable defaults");
eq(edited.candidate.variableSchema.memo, false, "review can classify memo as default-only");

const recipientFreeze = Candidate.normalizeCandidate(payload({
  fixedDefaults: Object.assign({}, payload().fixedDefaults, { recipient: { company: "원본 거래처" } })
}), { now: NOW });
eq(recipientFreeze.code, "invalid_fixed_defaults", "SOURCE_RECIPIENT_FROZEN_BY_ACCIDENT=NO");

const itemFreeze = Candidate.normalizeCandidate(payload({
  fixedDefaults: Object.assign({}, payload().fixedDefaults, { items: [{ name: "원본 품목", qty: 1, unitPrice: 1 }] })
}), { now: NOW });
eq(itemFreeze.code, "invalid_fixed_defaults", "SOURCE_ITEM_VALUES_FROZEN_BY_ACCIDENT=NO");

const variableDemotion = Candidate.normalizeCandidate(payload({
  variableSchema: { recipient: true, quoteNo: false, issueDate: true, items: true, memo: true, taxMode: true }
}), { now: NOW });
eq(variableDemotion.code, "invalid_variable_schema", "quote number cannot silently become fixed");

const approved = Candidate.approveCandidate(edited.candidate, {
  id: "skill-general",
  approvedBy: "central-cto",
  now: NOW,
  approvalRef: "issue-3218"
});
check(approved.ok === true, "EXPLICIT_APPROVAL=YES");
check(approved.skill.approved === true, "APPROVED_SAVED_QUOTE_SKILL_SAVE_READY=YES");
eq(approved.skill.fixedDefaults.memo, "수정한 기본 비고", "approval freezes only reviewed default behavior");
eq(approved.skill.variableSchema.memo, false, "approved classification matches the reviewed candidate");
eq(Skill.compileSkill(approved.skill).ok, true, "approved candidate compiles for repeated use");

const tampered = Object.assign({}, edited.candidate, { skillFingerprint: "0".repeat(64) });
eq(Candidate.approveCandidate(tampered, { id: "skill-tampered", approvedBy: "central-cto", now: NOW }).code,
  "candidate_changed_after_review", "approval is fingerprint-bound to reviewed behavior");

const provenanceTampered = JSON.parse(JSON.stringify(edited.candidate));
provenanceTampered.provenance.evidence[0].value = "변조된 출처 증거";
eq(Candidate.approveCandidate(provenanceTampered, { id: "skill-provenance-tampered", approvedBy: "central-cto", now: NOW }).code,
  "candidate_changed_after_review", "approval is fingerprint-bound to reviewed provenance");

console.log("quote-skill-candidate contracts: PASS");
