const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const Core = require("../quote-core.js");
const Template = require("../quote-template.js");
const Store = require("../quote-template-store.js");
const Selection = require("../quote-template-selection.js");
const Candidate = require("../quote-template-candidate.js");
const Cloner = require("../quote-template-cloner.js");
const Renderer = require("../quote-template-renderer.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) =>
  assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);

const clone = (value) => JSON.parse(JSON.stringify(value));
const readSource = (name) => fs.readFileSync(path.join(__dirname, "..", name), "utf8");
const BUILTIN = Template.BUILTIN_TEMPLATE_ID;
const NOW = "2026-09-28T08:00:00.000Z";
const LATER = "2026-09-28T08:05:00.000Z";
const QUOTE_A = "PQ-20260928-001";

const builtinContent = () => clone(Store.defaultTemplate(Store.emptyStore()).content);

function fakeStorage() {
  const map = new Map();
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => { map.set(key, String(value)); },
    removeItem: (key) => { map.delete(key); },
    snapshot: () => JSON.stringify({
      store: Store.serializeStore(Store.readStore({ getItem: (k) => (map.has(k) ? map.get(k) : null), setItem: () => {} })),
      selection: map.has(Selection.SELECTION_STORAGE_KEY) ? map.get(Selection.SELECTION_STORAGE_KEY) : null
    })
  };
}

function payload(over) {
  return Object.assign({
    schemaVersion: 1,
    candidateId: "cand-1",
    name: "거래처 A 양식",
    content: builtinContent(),
    provenance: { sourceKind: "file", sourceName: "quote-a.pdf", capturedAt: NOW },
    review: {
      warnings: [{ code: "low_contrast", message: "대비가 낮습니다" }],
      unknowns: [{ code: "stamp", message: "도장 위치 미확인" }],
      confidence: 0.62,
      evidence: [{ label: "페이지", value: "1" }]
    }
  }, over || {});
}

/* ── 세션 수명주기 ── */
const fresh = Cloner.createSession({ sessionId: "s1", now: NOW });
eq(fresh.status, Cloner.STATUS_IDLE, "a fresh session is idle");
eq(fresh.candidate, null, "a fresh session has no candidate");
eq(Cloner.statusLabel(fresh), "대기", "the idle status is labelled");

const preflightOk = Cloner.startFromFile(fresh, {
  ok: true, name: "quote-a.pdf", extension: ".pdf", media: "application/pdf", size: 2048
});
check(preflightOk.ok === true, "a valid preflight starts the flow");
eq(preflightOk.session.status, Cloner.STATUS_PREFLIGHT_OK, "the session waits at the analyzer boundary");
eq(preflightOk.session.candidate, null, "preflight alone produces no candidate");
eq(preflightOk.analyzer.live, false, "TEMPLATE_ANALYZER_LIVE=NO: the analyzer is not live");
eq(preflightOk.session.source.name, "quote-a.pdf", "the source file name is kept as data");

const preflightBad = Cloner.startFromFile(fresh, { ok: false, error: "legacy_hwp_unsupported" });
eq(preflightBad.ok, false, "a failed preflight stops the flow");
eq(preflightBad.session.status, Cloner.STATUS_FAILED, "the session records failure");
eq(preflightBad.session.error.code, "legacy_hwp_unsupported", "the preflight failure code is preserved");
eq(
  Cloner.startFromFile(fresh, { ok: false, error: "unsupported_file_type" }).session.error.code,
  "unsupported_file_type",
  "unsupported types are surfaced"
);

/* ── 후보 주입 → 검토 ── */
const storage = fakeStorage();
const reviewing = Cloner.startFromCandidate(preflightOk.session, payload());
check(reviewing.ok === true, "a candidate enters review");
eq(reviewing.session.status, Cloner.STATUS_REVIEWING, "the session is reviewing");
check(reviewing.session.reviewedFingerprint !== null, "the reviewed fingerprint is recorded");
eq(reviewing.review.statusLabel, "승인 전", "the review model is not approved");
check(Store.serializeStore(Store.readStore(storage)).templates.length === 0,
  "UNAPPROVED_TEMPLATE_ACTIVATION=0: a candidate is never auto-saved");

const malformed = Cloner.startFromCandidate(Cloner.createSession({}), { schemaVersion: 1, name: "x", content: builtinContent(), extra: true });
eq(malformed.ok, false, "MALFORMED_CANDIDATE_FAIL_CLOSED=PASS: a malformed candidate is rejected");
eq(malformed.session.status, Cloner.STATUS_FAILED, "a malformed candidate fails the session");
eq(malformed.session.candidate, null, "a malformed candidate yields no candidate");
check(Store.serializeStore(Store.readStore(storage)).templates.length === 0, "a malformed candidate writes nothing");

/* ── 검토 중 수정 ── */
const renamed = Cloner.editCandidate(reviewing.session, { name: "거래처 A 전용" }, { storage: storage });
check(renamed.ok === true, "the candidate name can be edited during review");
eq(renamed.session.candidate.name, "거래처 A 전용", "the edited name is applied");
eq(renamed.session.reviewedFingerprint, reviewing.session.reviewedFingerprint, "a rename keeps the fingerprint");
eq(renamed.session.status, Cloner.STATUS_REVIEWING, "editing keeps the session in review");

const editedContent = builtinContent();
editedContent.style.accent = "#1f4e8a";
const contentEdited = Cloner.editCandidate(renamed.session, { content: editedContent }, { storage: storage });
check(contentEdited.ok === true, "the candidate content can be edited during review");
check(contentEdited.session.reviewedFingerprint !== reviewing.session.reviewedFingerprint,
  "a content edit moves the reviewed fingerprint");
eq(contentEdited.session.status, Cloner.STATUS_REVIEWING, "a content edit stays in review");

const badEdit = Cloner.editCandidate(reviewing.session, { name: "   " }, { storage: storage });
check(badEdit.ok === false, "an invalid edit is refused");
eq(badEdit.session.reviewedFingerprint, reviewing.session.reviewedFingerprint, "a refused edit changes nothing");

/* ── 명시적 승인 ── */
const notReviewable = Cloner.approveCandidate(fresh, storage, { now: NOW });
eq(notReviewable.code, "session_not_reviewable", "EXPLICIT_TEMPLATE_APPROVAL_REQUIRED=YES: idle sessions cannot approve");
check(Store.serializeStore(Store.readStore(storage)).templates.length === 0, "a refused approval writes nothing");

const tampered = Object.assign({}, reviewing.session, { reviewedFingerprint: "0".repeat(64) });
const tamperResult = Cloner.approveCandidate(tampered, storage, { now: NOW });
eq(tamperResult.code, "candidate_changed_after_review",
  "APPROVAL_FINGERPRINT_BINDING=PASS: approval requires the reviewed fingerprint to match");
check(Store.serializeStore(Store.readStore(storage)).templates.length === 0, "a fingerprint mismatch writes nothing");

const approved = Cloner.approveCandidate(reviewing.session, storage, { now: LATER });
check(approved.ok === true, "an explicit approval saves the profile");
eq(approved.code, "approved", "the approval is explicit");
eq(approved.session.status, Cloner.STATUS_APPROVED, "the session records approval");
eq(approved.template.approved, true, "APPROVED_TEMPLATE_SAVE_AND_RENDER=PASS: the stored profile is approved");
eq(approved.template.approvalBasis, "explicit_approval", "the approval basis is explicit");
eq(approved.template.approval.contentFingerprint, reviewing.session.reviewedFingerprint,
  "APPROVAL_FINGERPRINT_BINDING=PASS: the approval binds the reviewed content");
eq(approved.template.approval.approvedBy, Cloner.DEFAULT_APPROVER, "the approver reference is recorded");
eq(approved.template.approval.approvedAt, LATER, "the approval timestamp is recorded");

const storedAfterApproval = Store.readStore(storage);
eq(Cloner.statusLabel(approved.session), "승인됨", "the session is labelled approved");
const managerRows = Selection.listForManagement(storedAfterApproval);
check(managerRows.some((row) => row.id === approved.template.id), "APPROVED_TEMPLATE_VISIBLE_IN_MANAGER=YES: it appears in the manager");
eq(Selection.isSelectable(storedAfterApproval, approved.template.id), true,
  "APPROVED_TEMPLATE_SELECTABLE=YES: the approved template can be selected");
eq(Selection.selectTemplate(storage, QUOTE_A, approved.template.id, { now: LATER }).ok, true,
  "the approved template can be applied to the current quotation");
eq(Selection.selectionForQuote(Selection.readEnvelope(storage), QUOTE_A), approved.template.id,
  "the applied selection is persisted");

/* ── 렌더: 업무 내용/합계 불변 ── */
const draft = Core.createDefaultDraft();
const draftBefore = clone(draft);
const builtinModel = Renderer.buildRenderModel(draft, Store.defaultTemplate(storedAfterApproval), { taxReviewRequired: false });
const clonedModel = Renderer.buildRenderModel(draft, Selection.resolveActiveTemplate(storedAfterApproval, Selection.readEnvelope(storage), QUOTE_A), { taxReviewRequired: false });
eq(clonedModel.template.id, approved.template.id, "the cloned template renders as the active template");
eq(clone(draft), draftBefore, "TEMPLATE_SWITCH_MUTATES_QUOTEDRAFT_CONTENT=NO: rendering never mutates the draft");
eq(clonedModel.totals.grandText, builtinModel.totals.grandText, "QUOTECORE_TOTALS_UNCHANGED=YES: grand total is unchanged");
eq(clonedModel.totals.vatText, builtinModel.totals.vatText, "QUOTECORE_TOTALS_UNCHANGED=YES: vat is unchanged");
eq(clonedModel.totals.subtotalText, builtinModel.totals.subtotalText, "QUOTECORE_TOTALS_UNCHANGED=YES: subtotal is unchanged");
check(clonedModel.template.fingerprint === approved.template.fingerprint, "the rendered fingerprint matches the approved one");

/* ── 승인 후 내용 변경은 승인을 무효화한다 ── */
const restyled = builtinContent();
restyled.style.accent = "#004400";
const invalidated = Cloner.editCandidate(approved.session, { content: restyled }, { storage: storage, now: LATER });
eq(invalidated.code, "approval_invalidated", "CANDIDATE_CONTENT_CHANGE_INVALIDATES_APPROVAL=YES: editing invalidates the approval");
eq(invalidated.session.status, Cloner.STATUS_REVIEWING, "the session returns to review");
eq(invalidated.session.approval, null, "the session no longer holds an approval");
eq(Store.getTemplate(Store.readStore(storage), approved.template.id).approved, false,
  "CANDIDATE_CONTENT_CHANGE_INVALIDATES_APPROVAL=YES: the stored approval is dropped");
eq(Store.defaultTemplateId(Store.readStore(storage)), BUILTIN, "an invalidated approval cannot stay default");

/* ── 실패 경로는 아무것도 바꾸지 않는다 ── */
const storage2 = fakeStorage();
const ready2 = Cloner.startFromCandidate(Cloner.createSession({}), payload({ candidateId: "cand-2", name: "두번째" }));
Selection.selectTemplate(storage2, QUOTE_A, BUILTIN, { now: NOW });
const beforeSnapshot = storage2.snapshot();

const refused = Cloner.approveCandidate(ready2.session, storage2, { now: LATER, id: BUILTIN });
check(refused.ok === false, "an approval that the store refuses fails");
eq(Store.serializeStore(Store.readStore(storage2)).templates.length, 0, "FAILED_APPROVAL_CHANGES_DEFAULT=0: nothing is stored");
eq(Store.defaultTemplateId(Store.readStore(storage2)), BUILTIN, "FAILED_APPROVAL_CHANGES_DEFAULT=0: the default is unchanged");
eq(storage2.snapshot(), beforeSnapshot, "FAILED_APPROVAL_CHANGES_CURRENT_SELECTION=0: the selection is unchanged");

const tampered2 = Object.assign({}, ready2.session, { reviewedFingerprint: "0".repeat(64) });
eq(Cloner.approveCandidate(tampered2, storage2, { now: LATER }).ok, false, "a mismatched approval fails");
eq(storage2.snapshot(), beforeSnapshot, "a failed approval leaves storage untouched");

/* ── 취소 ── */
const storage3 = fakeStorage();
const ready3 = Cloner.startFromCandidate(Cloner.createSession({}), payload({ candidateId: "cand-3" }));
const before3 = storage3.snapshot();
const cancelled = Cloner.cancelSession(ready3.session);
eq(cancelled.ok, true, "cancelling succeeds");
eq(cancelled.session.status, Cloner.STATUS_CANCELLED, "the session is cancelled");
eq(cancelled.session.candidate, null, "the candidate is discarded");
eq(cancelled.session.approval, null, "no approval remains");
eq(storage3.snapshot(), before3, "APPROVAL_CANCEL_WRITES_PROFILE=0: cancelling writes nothing");
eq(Cloner.approveCandidate(cancelled.session, storage3, { now: LATER }).code, "session_not_reviewable",
  "a cancelled session cannot be approved");

/* ── 진행 단계 ── */
const steps = Cloner.buildProgress(approved.session);
eq(steps.length, 4, "the progress model has four steps");
eq(steps.filter((step) => step.done).length, 4, "an approved session shows every step done");
eq(Cloner.buildProgress(fresh).filter((step) => step.done).length, 0, "an idle session shows no completed step");

/* ── 소스 수준 계약 ── */
const clonerSource = readSource("quote-template-cloner.js");
const candidateSource = readSource("quote-template-candidate.js");
check(!/fetch\(|XMLHttpRequest/.test(clonerSource + candidateSource),
  "BROWSER_UPLOAD_NETWORK=0 / MODEL_NETWORK_CALLS=0: no network call");
check(!/kilo\/|sensenova|space-bunny|nemotron|openai|anthropic/i.test(clonerSource + candidateSource),
  "MODEL_PROVIDER_IDS_IN_BROWSER=0: no provider or model reference");
check(!/FileReader|FormData|indexedDB/i.test(clonerSource + candidateSource),
  "BROWSER_UPLOAD_NETWORK=0: raw file bytes are never read or uploaded");
check(!/draft\.(sender|recipient|items|tax|memo|meta)\s*=/.test(clonerSource + candidateSource),
  "TEMPLATE_SWITCH_MUTATES_QUOTEDRAFT_CONTENT=NO: the cloner never assigns draft content");

const appSource = readSource("app.js");
check(appSource.indexOf('$("templateClone").addEventListener("click"') !== -1 &&
      appSource.indexOf('$("templateCloneFile").click()') !== -1,
  "TEMPLATE_CLONER_ENTRYPOINT=YES: the manager entry point opens the file chooser");
check(appSource.indexOf("FileIntake.classifyFile(file)") !== -1,
  "the cloner reuses the bounded file preflight");
check(appSource.indexOf("window.B66QuoteTemplateClonerBridge") !== -1 &&
      appSource.indexOf("injectCandidate: (payload) => injectClonerCandidate(payload)") !== -1,
  "TEMPLATE_CANDIDATE_MANUAL_INJECTION=PASS: the manual injection seam is exposed");
check(appSource.indexOf('$("templateApprove").addEventListener("click"') !== -1,
  "EXPLICIT_TEMPLATE_APPROVAL_REQUIRED=YES: approval is bound to an explicit button");
check(appSource.indexOf("TemplateCloner.approveCandidate(clonerSession, templateStorage(), {})") !== -1,
  "EXPLICIT_TEMPLATE_APPROVAL_REQUIRED=YES: the app approves only through the cloner contract");
check(appSource.indexOf("견적서 양식 본뜨기와 승인 흐름은 다음 단계에서 제공합니다.") === -1,
  "TEMPLATE_CLONER_ENTRYPOINT=YES: the placeholder toast is gone");

const htmlSource = readSource("index.html");
check(htmlSource.indexOf('id="templateClonerPanel"') !== -1 &&
      htmlSource.indexOf('id="templateReview"') !== -1 &&
      htmlSource.indexOf('id="templateApprove"') !== -1 &&
      htmlSource.indexOf('id="templateReviewCancel"') !== -1 &&
      htmlSource.indexOf('id="templateCloneFile"') !== -1,
  "TEMPLATE_CANDIDATE_REVIEW_UI=PASS: the review surface exists");
check(htmlSource.indexOf(".pdf,.docx,.pptx,.xlsx,.hwpx,.jpg,.jpeg,.png,.webp") !== -1,
  "the cloner file chooser keeps the bounded type list");

const uiSource = readSource("quote-template-ui.js");
check(uiSource.indexOf("function renderReviewMarkup(") !== -1 &&
      uiSource.indexOf("function buildReviewBlocks(") !== -1,
  "TEMPLATE_CANDIDATE_REVIEW_UI=PASS: the review markup builder exists");
check(uiSource.indexOf("candidate-name") !== -1, "the review surface allows renaming the candidate");

const cssSource = readSource("styles.css");
check(cssSource.indexOf(".template-cloner-actions .btn { min-height: 44px; }") !== -1,
  "MOBILE_TEMPLATE_CLONER_UI=PASS: cloner actions meet the 44px target");
check(cssSource.indexOf(".template-cloner, .template-review, .cloner-progress, .review-grid, .review-block, .review-status { display: none !important; }") !== -1,
  "PRINT_UI_LEAK=0: the cloner UI is excluded from print");
check(cssSource.indexOf(".review-grid { grid-template-columns: 1fr; }") !== -1,
  "MOBILE_TEMPLATE_CLONER_UI=PASS: the review grid collapses on narrow viewports");

console.log("TEMPLATE_CLONER_ENTRYPOINT=YES");
console.log("TEMPLATE_CANDIDATE_REVIEW_UI=PASS");
console.log("TEMPLATE_CANDIDATE_MANUAL_INJECTION=PASS");
console.log("EXPLICIT_TEMPLATE_APPROVAL_REQUIRED=YES");
console.log("UNAPPROVED_TEMPLATE_ACTIVATION=0");
console.log("APPROVED_TEMPLATE_SAVE_AND_RENDER=PASS");
console.log("CANDIDATE_CONTENT_CHANGE_INVALIDATES_APPROVAL=YES");
console.log("APPROVAL_FINGERPRINT_BINDING=PASS");
console.log("MALFORMED_CANDIDATE_FAIL_CLOSED=PASS");
console.log("APPROVAL_CANCEL_WRITES_PROFILE=0");
console.log("FAILED_APPROVAL_CHANGES_DEFAULT=0");
console.log("FAILED_APPROVAL_CHANGES_CURRENT_SELECTION=0");
console.log("APPROVED_TEMPLATE_VISIBLE_IN_MANAGER=YES");
console.log("APPROVED_TEMPLATE_SELECTABLE=YES");
console.log("QUOTECORE_TOTALS_UNCHANGED=YES");
console.log("TEMPLATE_SWITCH_MUTATES_QUOTEDRAFT_CONTENT=NO");
console.log("TEMPLATE_ANALYZER_LIVE=NO");
console.log("BROWSER_UPLOAD_NETWORK=0");
console.log("MODEL_PROVIDER_IDS_IN_BROWSER=0");
console.log("MODEL_NETWORK_CALLS=0");
console.log("MOBILE_TEMPLATE_CLONER_UI=PASS");
console.log("PRINT_UI_LEAK=0");
