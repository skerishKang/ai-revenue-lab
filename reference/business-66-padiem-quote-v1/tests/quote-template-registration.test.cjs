const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const Core = require("../quote-core.js");
const Template = require("../quote-template.js");
const TemplateCandidate = require("../quote-template-candidate.js");
const TemplateStore = require("../quote-template-store.js");
const TemplateRegistration = require("../quote-template-registration.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) => assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);
const clone = (value) => JSON.parse(JSON.stringify(value));
const NOW = "2026-09-30T03:00:00.000Z";

function sourceInfo(overrides) {
  return Object.assign({
    filename: "synthetic-company-quotation.pdf",
    mediaType: "application/pdf",
    byteSize: 3544
  }, overrides || {});
}

function sampleDraft() {
  return Core.normalizeDraft({
    schemaVersion: 1,
    meta: { quoteNo: "Q-PREVIEW-1", issueDate: "2026-09-30", validDays: 30, source: "preview" },
    sender: { company: "주식회사 테스트상사", presetId: "custom" },
    recipient: { company: "미리보기 거래처" },
    items: [{ id: "item-1", name: "스테인리스 배관 40x40", qty: 12, unitPrice: 9800 }],
    tax: { mode: "EXCLUSIVE", rate: 0.1 },
    memo: ""
  });
}

/* 1. file/source -> template candidate seeded from builtin, no source bytes. */
const seeded = TemplateRegistration.buildTemplateCandidateFromSource(sourceInfo(), { now: NOW });
check(seeded.ok === true, "source metadata seeds a template candidate");
eq(seeded.code, "template_candidate_ready", "template registration reports its own code");
check(seeded.candidate.status === "candidate", "seeded output is review-only");
check(seeded.review.sections.length > 0, "review exposes sections");
check(seeded.draftNote === TemplateRegistration.DRAFT_NOTE, "honest draft note accompanies the seed");
check(TemplateRegistration.DRAFT_NOTE.includes("자동으로 분석하지 않") &&
      TemplateRegistration.DRAFT_NOTE.includes("비교") &&
      !/완전히 학습|AI가/.test(TemplateRegistration.DRAFT_NOTE),
  "honest copy: default draft + no auto-analysis + compare-and-correct");
eq(seeded.candidate.provenance.sourceName, "synthetic-company-quotation.pdf", "source filename is provenance only");
check(!JSON.stringify(seeded.candidate).includes("base64"), "no source bytes enter the candidate");
eq(seeded.candidate.review.warnings.map((w) => w.code), ["manual_layout_review_required"], "manual review is required, not assumed");
eq(registerCheckInvalidSource(), "invalid_source_info", "missing filename fails closed");
function registerCheckInvalidSource() {
  return TemplateRegistration.buildTemplateCandidateFromSource({ filename: "  " }, { now: NOW }).code;
}

/* 2. manual correction across the supported schema (§5 minimum set). */
function correctedContent() {
  const content = clone(Template.builtInTemplate().content);
  content.title.text = "테스트상사 견적서";
  content.sections = ["title", "meta", "parties", "items", "totals", "memo"];
  content.items.columns = [
    { key: "qty", label: "수량", width: "15%", align: "right" },
    { key: "name", label: "품목명", width: "43%", align: "left" },
    { key: "unitPrice", label: "단가", width: "", align: "right" },
    { key: "amount", label: "금액", width: "", align: "right" }
  ];
  content.totals.supplyLabel = "공급가액 합계";
  content.totals.grandLabel = "청구 총액";
  content.page = { size: "A4", margin: "18mm", orientation: "landscape" };
  content.style.accent = "#0b5fff";
  content.style.titleRule = "double";
  content.style.headerAlignment = "center";
  content.style.metaAlignment = "right";
  content.style.numericAlignment = "right";
  content.style.totalsWidth = "62%";
  content.items.emptyNameText = "품목명을 입력하세요";
  content.memo.emptyText = "비고 없음";
  content.mark.text = "SYNTHETIC TEST DATA";
  return content;
}

const corrected = TemplateRegistration.correctTemplateCandidate(seeded.candidate, {
  name: "테스트상사 견적 양식",
  content: correctedContent()
}, { now: NOW });
check(corrected.ok === true, "layout correction within the supported schema succeeds");
eq(corrected.candidate.name, "테스트상사 견적 양식", "template name is correctable");
eq(corrected.candidate.content.title.text, "테스트상사 견적서", "document title is correctable");
eq(corrected.candidate.content.items.columns.map((c) => c.key).join(","),
  "qty,name,unitPrice,amount", "column order is correctable");
eq(corrected.candidate.content.totals.supplyLabel, "공급가액 합계", "total labels are correctable");
eq(corrected.candidate.content.page.orientation, "landscape", "page rules are correctable");
eq(corrected.candidate.content.style.accent, "#0b5fff", "accent token is correctable");
eq(corrected.review.columns[0].key, "qty", "review reflects the corrected column order");

const badPatch = TemplateRegistration.correctTemplateCandidate(seeded.candidate, { content: { sections: ["nope"] } }, { now: NOW });
check(badPatch.ok === false, "unsupported sections fail closed");
eq(TemplateRegistration.correctTemplateCandidate(seeded.candidate, { layout: {} }, { now: NOW }).code,
  "unsupported_template_correction", "unknown correction keys fail closed");

/* #3402: candidate schema can describe private refs, but browser-local approval cannot own them. */
const privateLogoId = "b66asset_" + "a".repeat(32);
const slotContent = correctedContent();
slotContent.slots = { logo: privateLogoId, stamp: "" };
const slotCandidate = TemplateRegistration.correctTemplateCandidate(seeded.candidate, { content: slotContent }, { now: NOW });
check(slotCandidate.ok === true, "candidate content may describe private asset slots");
const slotStore = TemplateStore.emptyStore();
const slotApproval = TemplateRegistration.approveTemplateCandidate(slotCandidate.candidate, slotStore, {
  id: "tpl-slot", approvedBy: "local-owner", approvedAt: NOW
}, { now: NOW });
eq(slotApproval.code, "private_asset_requires_account_skill",
  "private assets require account-bound Saved Quote Skill authority");
const urlSlotContent = correctedContent();
urlSlotContent.slots = { logo: "https://example.test/logo.png", stamp: "" };
const urlSlotCandidate = TemplateRegistration.correctTemplateCandidate(
  seeded.candidate,
  { content: urlSlotContent },
  { now: NOW }
);
check(urlSlotCandidate.ok === true, "invalid slot URL is normalized rather than persisted");
eq(urlSlotCandidate.candidate.content.slots.logo, "", "arbitrary logo URL is removed by template normalization");

/* 3. preview without any storage mutation. */
const draft = sampleDraft();
check(draft !== null, "test setup: sample draft normalizes");
const preview = TemplateRegistration.previewTemplateCandidate(corrected.candidate, draft, { now: NOW });
check(preview.ok === true, "candidate preview renders through the existing renderer");
eq(preview.renderModel.template.fallbackReason, "preview_unapproved_candidate", "preview is explicitly marked unapproved");
check(preview.renderModel.template.approved === false, "preview never forges approval");
check(preview.renderModel.template.id === "preview-unapproved-candidate", "preview identity is explicit");
eq(preview.contentFingerprint, corrected.candidate.contentFingerprint, "preview proves the corrected layout");
check(preview.renderModel.sections.includes("items"), "preview carries the corrected sections");
const previewTitles = JSON.stringify(preview.renderModel);
check(previewTitles.includes("테스트상사 견적서") || previewTitles.includes("품목명"),
  "preview reflects corrected content, not the built-in fallback");
eq(TemplateRegistration.previewTemplateCandidate.length, 3, "preview takes (candidate, draft, options): no storage parameter exists");

/* 4. explicit template approval, fingerprint-bound, no default hijack. */
const approved = TemplateRegistration.approveTemplateCandidate(corrected.candidate, TemplateStore.emptyStore(), {
  id: "tpl-synthetic", approvedBy: "local-owner", approvedAt: NOW, approvalRef: "issue-3218"
}, { now: NOW });
check(approved.ok === true, "corrected candidate approves explicitly");
check(approved.template.approved === true, "EXPLICIT_TEMPLATE_APPROVAL=YES");
eq(approved.template.fingerprint, corrected.candidate.contentFingerprint, "TEMPLATE_FINGERPRINT_BOUND=YES");
eq(approved.template.isDefault, false, "registration never hijacks the default template");
const tamperedApproval = TemplateRegistration.approveTemplateCandidate(corrected.candidate, TemplateStore.emptyStore(), {
  id: "tpl-tampered", approvedBy: "x", approvedAt: NOW
}, { now: NOW });
check(tamperedApproval.ok === false, "invalid approver fails closed");
eq(TemplateRegistration.approveTemplateCandidate(corrected.candidate, TemplateStore.emptyStore(), {
  id: "tpl-bad<>id", approvedBy: "local-owner", approvedAt: NOW
}, { now: NOW }).ok, true, "store id policy governs template ids");

/* 5. stored tamper/stale approval rejection through the real store. */
const storedTampered = clone(approved.store);
storedTampered.templates[0].content.title.text = "변조된 제목";
check(TemplateStore.getTemplate(storedTampered, "tpl-synthetic") === null,
  "TEMPLATE_STALE_APPROVAL_REUSE=0");

/* 6. module hygiene: no network/model/credential/raw-byte surface. */
const source = fs.readFileSync(path.join(__dirname, "..", "quote-template-registration.js"), "utf8");
check(!/fetch\(|XMLHttpRequest|WebSocket|EventSource/.test(source), "template registration performs no network/model call");
check(!/(space-bunny|sensenova|openai|anthropic|kilo\/)/i.test(source), "template registration owns no provider/model identity");
check(!/secret|apiKey|api_key|token|password/i.test(source), "template registration carries no credential material");
check(!/FileReader|FormData|indexedDB|localStorage|sessionStorage/.test(source), "RAW_SOURCE_FILE_BROWSER_PERSISTENCE=0");
check(!/완전히 학습했습니다|완벽하게 학습|학습이 완료되었습니다|AI가 배웠습니다/.test(source), "no overclaimed AI-learning copy in the module");

console.log("quote-template-registration contracts: PASS");