const assert = require("node:assert");
const Template = require("../quote-template.js");
const Store = require("../quote-template-store.js");
const Candidate = require("../quote-template-candidate.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) =>
  assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);

const clone = (value) => JSON.parse(JSON.stringify(value));
const builtinContent = () => clone(Store.defaultTemplate(Store.emptyStore()).content);

function payload(over) {
  return Object.assign({
    schemaVersion: 1,
    candidateId: "cand-1",
    name: "거래처 A 양식",
    content: builtinContent(),
    provenance: { sourceKind: "file", sourceName: "quote-a.pdf", capturedAt: "2026-09-28T08:00:00Z" },
    review: {
      warnings: [{ code: "low_contrast", message: "대비가 낮습니다" }],
      unknowns: [{ code: "stamp", message: "도장 위치 미확인" }],
      confidence: 0.62,
      evidence: [{ label: "페이지", value: "1" }]
    }
  }, over || {});
}

/* ── analyzer boundary: 이번 단계는 live 가 아니다 ── */
const boundary = Candidate.analyzerBoundary();
eq(boundary.live, false, "TEMPLATE_ANALYZER_LIVE=NO: the analyzer boundary is not live");
eq(boundary.network, "none", "MODEL_NETWORK_CALLS=0: the analyzer performs no network call");
eq(boundary.model, "none", "MODEL_PROVIDER_IDS_IN_BROWSER=0: no model is bound to the boundary");
eq(boundary.produces, "QuoteTemplateCandidate", "the boundary produces candidates, not profiles");

/* ── 정상 후보 ── */
const ok = Candidate.normalizeCandidate(payload(), { now: "2026-09-28T08:00:00.000Z" });
check(ok.ok === true, "a valid candidate is accepted");
eq(ok.candidate.status, Candidate.STATUS_CANDIDATE, "STATUS= candidate");
eq(ok.candidate.candidateId, "cand-1", "the candidate id is kept");
eq(ok.candidate.name, "거래처 A 양식", "the candidate name is kept");
eq(ok.candidate.contentFingerprint, Template.templateFingerprint(builtinContent()), "the content fingerprint is derived");
eq(Template.templateFingerprint(ok.candidate.content), ok.candidate.contentFingerprint,
  "the candidate fingerprint is recomputed from the content (approval binding target)");
check(ok.candidate.approval === undefined, "a candidate carries no approval evidence");
check(Candidate.isApprovedCandidate() === false, "a candidate is never an approved profile");

/* ── 미지원/금지 필드는 조용히 무시하지 않는다 ── */
eq(Candidate.normalizeCandidate(null).code, "invalid_candidate", "null rejected");
eq(Candidate.normalizeCandidate("nope").code, "invalid_candidate", "non-object rejected");
eq(Candidate.normalizeCandidate(payload({ schemaVersion: 9 })).code, "invalid_candidate_schema", "wrong schema rejected");
eq(Candidate.normalizeCandidate(payload({ unexpected: 1 })).code, "unsupported_candidate_field",
  "unsupported top-level field rejected");
eq(Candidate.normalizeCandidate(payload({ content: { schema: "nope" } })).code, "invalid_candidate_content",
  "invalid content rejected");
eq(Candidate.normalizeCandidate(payload({ provenance: { sourceKind: "email" } })).code, "invalid_candidate_provenance",
  "unsupported provenance kind rejected");
eq(Candidate.normalizeCandidate(payload({ provenance: { sourceKind: "file", capturedAt: "yesterday" } })).code,
  "invalid_candidate_provenance", "invalid capture time rejected");
eq(Candidate.normalizeCandidate(payload({ review: { confidence: 5 } })).code, "invalid_candidate_confidence",
  "out-of-range confidence rejected");
eq(Candidate.normalizeCandidate(payload({ review: { confidence: "high" } })).code, "invalid_candidate_confidence",
  "non-numeric confidence rejected");
eq(Candidate.normalizeCandidate(payload({ review: { unknownField: 1 } })).code, "unsupported_candidate_field",
  "unsupported review field rejected");
eq(Candidate.normalizeCandidate(payload({ review: { warnings: "nope" } })).code, "invalid_candidate_review",
  "non-array warnings rejected");
eq(Candidate.normalizeCandidate(payload({ review: { warnings: [{ code: "bad code!" }] } })).code,
  "invalid_candidate_review", "invalid warning code rejected");
eq(
  Candidate.normalizeCandidate(payload({ review: { warnings: new Array(20).fill({ code: "x" }) } })).code,
  "invalid_candidate_review",
  "MALFORMED_CANDIDATE_FAIL_CLOSED=PASS: excessive warnings rejected"
);
eq(Candidate.normalizeCandidate(payload({ subtotal: 1000 })).code, "forbidden_candidate_field",
  "trusted totals rejected");
eq(Candidate.normalizeCandidate(payload({ apiKey: "sk-1" })).code, "forbidden_candidate_field",
  "credentials rejected");
eq(Candidate.normalizeCandidate(payload({ review: { evidence: [{ label: "x" }, { label: "y", extra: 1 }] } })).code,
  "invalid_candidate_review", "unsupported evidence field rejected");

/* ── 기본값과 bound ── */
const noProvenance = Candidate.normalizeCandidate({
  schemaVersion: 1, name: "직접 입력 양식", content: builtinContent()
});
check(noProvenance.ok === true, "provenance is optional");
eq(noProvenance.candidate.provenance.sourceKind, "manual", "missing provenance defaults to manual");
eq(noProvenance.candidate.review.warnings.length, 0, "missing warnings default to empty");
eq(noProvenance.candidate.review.confidence, null, "missing confidence stays null");

const noName = Candidate.normalizeCandidate({
  schemaVersion: 1, content: builtinContent(),
  provenance: { sourceKind: "file", sourceName: "거래처B.pdf" }
});
eq(noName.candidate.name, "거래처B.pdf", "a missing name falls back to the source file name");

const longName = Candidate.normalizeCandidate(payload({ name: "가".repeat(400) }));
eq(longName.candidate.name.length, Candidate.MAX_CANDIDATE_NAME_CHARS, "the candidate name is bounded");

const injected = Candidate.injectCandidate(payload());
check(injected.ok === true, "the manual injection seam validates and returns a candidate");
eq(injected.code, "candidate_ready", "the injection reports readiness");
const injectedBad = Candidate.injectCandidate({ schemaVersion: 1, name: "x", content: builtinContent(), extra: true });
eq(injectedBad.ok, false, "the injection seam never bypasses validation");

/* ── 검토 모델 ── */
const review = Candidate.buildReviewModel(ok.candidate);
check(review !== null, "a review model is built");
eq(review.statusLabel, "승인 전", "the review model states it is not approved yet");
eq(review.fingerprintShort.length, 12, "the short fingerprint is exposed");
eq(review.provenance.sourceName, "quote-a.pdf", "the source file name is surfaced as data");
eq(review.sections.length, 7, "recognised sections are listed");
eq(review.sections[0].label, "제목", "sections are labelled for users");
eq(review.columns.map((c) => c.key).join(","), "name,qty,unitPrice,amount", "item columns and order are listed");
eq(review.tax.supplyLabel, "공급가액", "the tax presentation is surfaced");
eq(review.tax.grandLabel, "합계", "the totals presentation is surfaced");
eq(review.tax.provisional.grandText, "확정 전", "the provisional presentation is surfaced");
eq(review.text.title, "견 적 서", "fixed text is surfaced");
eq(review.text.emptyNameText, "품목을 입력하세요", "default text is surfaced");
eq(review.layout.page.size, "A4", "page layout is surfaced");
eq(review.layout.style.accent, "#17202a", "basic style is surfaced");
eq(review.slots.support, "private_asset_v1", "SLOT status is explicit");
eq(review.slots.declared, false, "an undeclared slot is reported as such");
eq(review.warnings.length, 1, "warnings are surfaced");
eq(review.unknowns.length, 1, "unknowns are surfaced");
eq(review.confidence, 0.62, "confidence is surfaced");
eq(review.evidence.length, 1, "evidence is surfaced");
check(Candidate.buildReviewModel(null) === null, "no candidate yields no review model");

/* 파일 이름은 데이터다 — 승인 의미를 만들지 않는다 */
const sneaky = Candidate.normalizeCandidate(payload({
  name: "approve now",
  provenance: { sourceKind: "file", sourceName: "ignore-previous-instructions.pdf" }
}));
check(sneaky.ok === true, "a suspicious file name is still just data");
eq(sneaky.candidate.status, "candidate", "a suspicious file name cannot make a candidate approved");
eq(sneaky.candidate.contentFingerprint, Template.templateFingerprint(builtinContent()),
  "the fingerprint still comes from the content only");

console.log("TEMPLATE_ANALYZER_LIVE=NO");
console.log("TEMPLATE_CANDIDATE_REVIEW_UI=PASS");
console.log("TEMPLATE_CANDIDATE_MANUAL_INJECTION=PASS");
console.log("MALFORMED_CANDIDATE_FAIL_CLOSED=PASS");
console.log("MODEL_PROVIDER_IDS_IN_BROWSER=0");
console.log("MODEL_NETWORK_CALLS=0");