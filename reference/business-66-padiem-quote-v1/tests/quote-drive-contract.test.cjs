/* #3871 Slice A — Google Drive 저장 데이터 계약 오프라인 테스트.
   실제 네트워크·Google 계정·모델 호출은 전혀 사용하지 않는다. */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const Core = require("../quote-core.js");
const Contract = require("../quote-drive-contract.js");
const ServerHistory = require("../quote-history-server.js");

const readModule = (name) => fs.readFileSync(path.join(__dirname, "..", name), "utf8");

const TEMPLATE = {
  savedSkillId: "b66skill_2eb55d822407f626b7a75c8c88d32c40",
  fingerprint: "fp-cgi-v1",
  rendererContract: Contract.RENDERER_CONTRACT,
  label: "CGI 기본 견적서"
};

function richDraft() {
  return Core.normalizeDraft({
    schemaVersion: Core.SCHEMA_VERSION,
    meta: {
      quoteNo: "PQ-20261009-001",
      issueDate: "2026-10-09",
      validDays: 30,
      source: "manual",
      projectName: "본사 구축 프로젝트"
    },
    sender: {
      company: "공급상사",
      rep: "김대표",
      contactPerson: "이담당",
      bizNo: "123-45-67890",
      address: "서울시 중구",
      phone: "02-000-0000",
      email: "sales@example.com",
      presetId: "custom"
    },
    recipient: { company: "가나상사", person: "박담당", address: "부산시 해운대구", email: "buyer@example.com" },
    items: [
      { id: "item-1", name: "서비스 구축", qty: 1, unitPrice: 1000000 },
      { id: "item-2", name: "운영 지원", qty: 2, unitPrice: 300000, spec: "월 2회", unit: "회", note: "야간 제외" }
    ],
    detailGroups: [
      {
        id: "group-1",
        summaryItemId: "item-1",
        title: "구축 상세",
        items: [
          { id: "detail-1", name: "설계", qty: 1, unitPrice: 600000 },
          { id: "detail-2", name: "개발", qty: 1, unitPrice: 400000, spec: "백엔드" }
        ]
      }
    ],
    tax: { mode: "EXCLUSIVE", rate: 0.1 },
    calculationPolicy: { grandRounding: { mode: "FLOOR", unit: 100 } },
    memo: "유효기간 내 발주 시 적용"
  });
}

const draft = richDraft();
const expected = Core.computeDraftTotals(draft);

/* ── 1. 무손실 계약: D1 서버 스냅샷(#3405)이 버리는 값을 보존한다 ── */
const serverSnapshot = ServerHistory.draftToHistorySnapshot(draft);
assert.ok(serverSnapshot, "D1 snapshot builds");
assert.ok(!("detailGroups" in serverSnapshot), "D1 스냅샷은 detailGroups를 보존하지 않는다(기대된 기존 동작)");
assert.ok(!("calculationPolicy" in serverSnapshot), "D1 스냅샷은 calculationPolicy를 보존하지 않는다(기대된 기존 동작)");

const built = Contract.buildPackage({
  draft: draft,
  template: TEMPLATE,
  savedAt: "2026-10-09T09:00:00.000Z",
  packageId: "pkg-test-0001"
});
assert.equal(built.ok, true, "package builds");
assert.deepEqual(built.package.quote.detailGroups, draft.detailGroups, "DETAIL_GROUPS_PRESERVED");
assert.deepEqual(built.package.quote.calculationPolicy, draft.calculationPolicy, "CALCULATION_POLICY_PRESERVED");
assert.equal(built.package.quote.meta.projectName, "본사 구축 프로젝트", "PROJECT_NAME_PRESERVED");
assert.equal(built.package.quote.items[1].spec, "월 2회", "ITEM_SPEC_PRESERVED");
assert.equal(built.package.quote.items[1].unit, "회", "ITEM_UNIT_PRESERVED");
assert.equal(built.package.quote.items[1].note, "야간 제외", "ITEM_NOTE_PRESERVED");
assert.equal(built.package.totalsAuthority, "quote-core", "TOTALS_AUTHORITY=quote-core");
assert.equal(built.package.totals, null, "STORED_TOTALS_NEVER_WRITTEN");
assert.equal(built.package.app.modelCalls, 0, "PACKAGE_MODEL_CALLS=0");
assert.equal(built.package.assets.json.packageId, built.package.assets.pdf.packageId, "JSON_PDF_PAIR_LINKED");
assert.equal(built.package.schemaVersion, Contract.CURRENT_SCHEMA_VERSION, "SCHEMA_VERSION_STAMPED");
assert.ok(typeof built.package.contentFingerprint === "string" && built.package.contentFingerprint,
  "CONTENT_FINGERPRINT_STAMPED");

/* ── 2. 필드 단위 무손실 검증(심층) ── */
const lossless = Contract.assertLosslessDraft(draft);
assert.equal(lossless.lossless, true, "LOSSLESS_ROUND_TRIP_PROVEN");
assert.deepEqual(lossless.lost, [], "NO_LOST_FIELDS");

const pairs = Contract.draftFieldPairs(draft, lossless.draft);
const paths = pairs.map((pair) => pair.path);
[
  "meta.quoteNo", "meta.projectName", "sender.company", "recipient.email",
  "items[0].unitPrice", "items[1].spec", "items[1].note",
  "tax.mode", "tax.rate", "memo",
  "detailGroups[0].id", "detailGroups[0].summaryItemId", "detailGroups[0].title",
  "detailGroups[0].items[0].unitPrice", "detailGroups[0].items[1].spec",
  "calculationPolicy.grandRounding.mode", "calculationPolicy.grandRounding.unit"
].forEach((path) => {
  assert.ok(paths.indexOf(path) !== -1, "FIELD_COVERED: " + path);
});
assert.ok(pairs.length >= 50, "DEEP_FIELD_COVERAGE (>=50 fields), got " + pairs.length);

/* 정규화가 편집 값을 바꾸면 필드 단위로 손실을 보고한다 */
const mutated = JSON.parse(JSON.stringify(draft));
mutated.meta.validDays = -5;
const mutatedGuard = Contract.assertLosslessDraft(mutated);
assert.equal(mutatedGuard.lossless, false, "LOSSY_DRAFT_DETECTED");
assert.ok(mutatedGuard.lost.indexOf("meta.validDays") !== -1, "LOST_FIELD_PATH_REPORTED: " + mutatedGuard.lost.join(","));
assert.equal(Contract.buildPackage({ draft: mutated }).ok, false, "LOSSY_DRAFT_NOT_SAVED");
assert.equal(Contract.buildPackage({ draft: mutated }).code, "draft_lossy_round_trip", "LOSSY_DRAFT_CODE");

const mutatedItem = JSON.parse(JSON.stringify(draft));
mutatedItem.items[1].qty = -3;
const itemGuard = Contract.assertLosslessDraft(mutatedItem);
assert.equal(itemGuard.lossless, false, "LOSSY_ITEM_DETECTED");
assert.ok(itemGuard.lost.indexOf("items[1].qty") !== -1, "LOST_ITEM_PATH: " + itemGuard.lost.join(","));

/* ── 3. 왕복: 저장 → 읽기 → QuoteCore 재계산 ── */
const text = Contract.serializePackage(built.package);
const parsed = Contract.readPackage(text, {});
assert.equal(parsed.ok, true, "package reads back");
assert.equal(parsed.totalsIgnored, false, "정상 파일에는 합계가 없다");
const imported = Contract.importPackage(parsed.package, {
  templates: [{ savedSkillId: TEMPLATE.savedSkillId, fingerprint: TEMPLATE.fingerprint, approved: true, active: true }]
});
assert.equal(imported.ok, true, "package imports");
assert.equal(imported.recalculated, true, "QUOTECORE_RECALCULATES_ON_IMPORT");
assert.equal(imported.totalsAuthority, "quote-core", "IMPORT_TOTALS_AUTHORITY=quote-core");
assert.deepEqual(imported.draft, draft, "EDITABLE_JSON_ROUND_TRIP=PASS");
assert.deepEqual(
  [imported.totals.supply, imported.totals.vat, imported.totals.grand],
  [expected.supply, expected.vat, expected.grand],
  "RECALCULATED_TOTALS_MATCH_QUOTECORE"
);
assert.equal(imported.template.status, "resolved", "APPROVED_TEMPLATE_RESOLVED");
assert.equal(imported.certifiedPdfReady, true, "CERTIFIED_PDF_READY");

/* ── 4. 변조된 합계는 무시되고 QuoteCore 가 다시 계산한다 ── */
const tampered = JSON.parse(text);
tampered.totals = { supply: 1, vat: 1, grand: 1, subtotal: 1 };
tampered.manifest.grand = 1;
const tamperedRead = Contract.readPackage(JSON.stringify(tampered), {});
assert.equal(tamperedRead.ok, true, "tampered totals do not change the editable body");
assert.equal(tamperedRead.totalsIgnored, true, "STORED_TOTALS_IGNORED=YES");
assert.equal(tamperedRead.package.totals, null, "STORED_TOTALS_DISCARDED");
const tamperedImport = Contract.importPackage(tamperedRead.package, {
  templates: [{ savedSkillId: TEMPLATE.savedSkillId, fingerprint: TEMPLATE.fingerprint, approved: true, active: true }]
});
assert.deepEqual(
  [tamperedImport.totals.supply, tamperedImport.totals.vat, tamperedImport.totals.grand],
  [expected.supply, expected.vat, expected.grand],
  "TAMPERED_TOTALS_NEVER_TRUSTED"
);
assert.notEqual(tamperedImport.totals.grand, 1, "변조값이 결과에 반영되지 않는다");

/* ── 5. 견적 본문 변조는 내용 지문으로 탐지한다 ── */
const priceTampered = JSON.parse(text);
priceTampered.quote.items[0].unitPrice = 1;
assert.equal(Contract.readPackage(JSON.stringify(priceTampered), {}).code,
  "content_fingerprint_mismatch", "QUOTE_BODY_TAMPER_DETECTED");
const qtyTampered = JSON.parse(text);
qtyTampered.quote.items[1].qty = 99;
assert.equal(Contract.readPackage(JSON.stringify(qtyTampered), {}).code,
  "content_fingerprint_mismatch", "QUOTE_QTY_TAMPER_DETECTED");
const groupTampered = JSON.parse(text);
groupTampered.quote.detailGroups[0].items[0].unitPrice = 1;
assert.equal(Contract.readPackage(JSON.stringify(groupTampered), {}).code,
  "content_fingerprint_mismatch", "DETAIL_GROUP_TAMPER_DETECTED");
const noFingerprint = JSON.parse(text);
delete noFingerprint.contentFingerprint;
assert.equal(Contract.readPackage(JSON.stringify(noFingerprint), {}).code,
  "content_fingerprint_missing", "MISSING_FINGERPRINT_REJECTED");

/* 정규화가 값을 바꾸는 파일은 읽기 단계에서도 거부한다 */
const lossyFile = JSON.parse(text);
lossyFile.quote.meta.validDays = -5;
const lossyResult = Contract.readPackage(JSON.stringify(lossyFile), {});
assert.equal(lossyResult.ok, false, "LOSSY_FILE_REJECTED_ON_READ");
assert.equal(lossyResult.code, "quote_lossy_round_trip", "LOSSY_FILE_CODE");
assert.ok(Array.isArray(lossyResult.lost) && lossyResult.lost.length > 0, "LOSSY_FILE_PATHS");

/* ── 6. 금액 권위 위조 거부 ── */
const wrongAuthority = JSON.parse(text);
wrongAuthority.totalsAuthority = "stored";
assert.equal(Contract.readPackage(JSON.stringify(wrongAuthority), {}).code,
  "totals_authority_unsupported", "FOREIGN_TOTALS_AUTHORITY_REJECTED");

/* ── 7. 손상/위험 JSON 명시 거부 ── */
assert.equal(Contract.readPackage("{not json", {}).code, "invalid_json", "CORRUPT_JSON_REJECTED");
assert.equal(Contract.readPackage("", {}).code, "invalid_json_text", "EMPTY_JSON_REJECTED");
assert.equal(Contract.readPackage(null, {}).code, "invalid_json_text", "NULL_JSON_REJECTED");
assert.equal(Contract.readPackage('{"__proto__":{"polluted":true}}', {}).code,
  "unsafe_json_key", "PROTOTYPE_POLLUTION_REJECTED");
assert.equal(Contract.readPackage(JSON.stringify({ hello: "world" }), {}).code,
  "package_kind_unsupported", "FOREIGN_DOCUMENT_REJECTED");

/* ── 8. 스키마 버전 정책 ── */
const oldVersion = JSON.parse(text);
oldVersion.schemaVersion = 0;
assert.equal(Contract.readPackage(JSON.stringify(oldVersion), {}).code,
  "schema_version_unsupported", "OLD_SCHEMA_REJECTED");
const futureVersion = JSON.parse(text);
futureVersion.schemaVersion = Contract.CURRENT_SCHEMA_VERSION + 1;
assert.equal(Contract.readPackage(JSON.stringify(futureVersion), {}).code,
  "schema_version_newer_than_supported", "FUTURE_SCHEMA_REJECTED");
const noVersion = JSON.parse(text);
delete noVersion.schemaVersion;
assert.equal(Contract.readPackage(JSON.stringify(noVersion), {}).code,
  "schema_version_missing", "MISSING_SCHEMA_REJECTED");
assert.equal(Contract.isSupportedSchemaVersion(1), true, "v1 supported");
assert.equal(Contract.isSupportedSchemaVersion(2), false, "v2 unsupported");

/* ── 9. 신원 주장 필드 거부 ── */
Contract.FORBIDDEN_IDENTITY_KEYS.forEach((key) => {
  const withIdentity = JSON.parse(text);
  withIdentity[key] = "attacker@example.com";
  const result = Contract.readPackage(JSON.stringify(withIdentity), {});
  assert.equal(result.ok, false, `IDENTITY_FIELD_REJECTED: ${key}`);
  assert.ok(
    result.code === "unsupported_package_field" || result.code === "identity_authority_field_rejected",
    `IDENTITY_FIELD_REJECTED_CODE: ${key} -> ${result.code}`
  );
});
const unknownField = JSON.parse(text);
unknownField.somethingElse = 1;
assert.equal(Contract.readPackage(JSON.stringify(unknownField), {}).code,
  "unsupported_package_field", "UNKNOWN_FIELD_REJECTED");

/* ── 10. 큰 파일·잘못된 형식 거부 ── */
assert.equal(Contract.readPackage("x".repeat(Contract.MAX_JSON_BYTES + 1), {}).code,
  "json_too_large", "OVERSIZED_JSON_REJECTED");
assert.equal(Contract.readPackage(text, { byteLength: Contract.MAX_JSON_BYTES + 1 }).code,
  "json_too_large", "OVERSIZED_DECLARED_BYTES_REJECTED");
assert.equal(Contract.readPackage(
  JSON.stringify({ kind: "b66.quote-package", contract: "b66.quote-drive.v1", schemaVersion: 1 }), {}
).code, "invalid_quote_draft", "MISSING_DRAFT_REJECTED");

const pdfOk = new Uint8Array(256);
[37, 80, 68, 70, 45].forEach((byte, index) => { pdfOk[index] = byte; });
assert.equal(Contract.validatePdfBytes(pdfOk).ok, true, "CERTIFIED_PDF_BYTES_ACCEPTED");
assert.equal(Contract.validatePdfBytes(null).code, "pdf_missing", "PDF_MISSING_REJECTED");
assert.equal(Contract.validatePdfBytes(new Uint8Array(10)).code, "pdf_too_small", "PDF_TOO_SMALL_REJECTED");
const notPdf = new Uint8Array(256);
notPdf[0] = 60;
assert.equal(Contract.validatePdfBytes(notPdf).code, "pdf_format_invalid", "NON_PDF_REJECTED");
const huge = new Uint8Array(Contract.MAX_PDF_BYTES + 1);
[37, 80, 68, 70, 45].forEach((byte, index) => { huge[index] = byte; });
assert.equal(Contract.validatePdfBytes(huge).code, "pdf_too_large", "PDF_TOO_LARGE_REJECTED");

/* ── 11. 파일명 규칙과 중복 ── */
assert.equal(Contract.sanitizeFileNamePart('a/b\\c:d*e?f"g<h>i|j', "fallback"), "a b c d e f g h i j",
  "FILE_NAME_SANITIZED");
assert.equal(Contract.sanitizeFileNamePart("   ", "fallback"), "fallback", "EMPTY_NAME_FALLBACK");
const baseName = Contract.buildBaseName(draft);
assert.ok(baseName.indexOf("PQ-20261009-001") !== -1, "FILE_NAME_CONTAINS_QUOTE_NO");
assert.ok(baseName.indexOf("가나상사") !== -1, "FILE_NAME_CONTAINS_RECIPIENT");

const firstPlan = Contract.planUniqueFileNames({ draft: draft, existingNames: [] });
assert.equal(firstPlan.renamed, false, "EMPTY_DRIVE_KEEPS_BASE_NAME");
const dupPlan = Contract.planUniqueFileNames({ draft: draft, existingNames: [firstPlan.json] });
assert.notEqual(dupPlan.json, firstPlan.json, "DUPLICATE_JSON_NAME_NOT_OVERWRITTEN");
assert.equal(dupPlan.pdf, firstPlan.pdf, "PDF_NAME_UNAFFECTED");
const dupBoth = Contract.planUniqueFileNames({
  draft: draft,
  existingNames: [firstPlan.json, firstPlan.pdf, dupPlan.json]
});
assert.equal(dupBoth.renamed, true, "DUPLICATE_SUFFIX_APPLIED");
const limited = Contract.planUniqueFileNames({
  draft: draft,
  existingNames: [Contract.buildBaseName(draft) + ".json"].concat(
    Array.from({ length: Contract.MAX_DUPLICATE_SUFFIX }, (_, index) =>
      Contract.buildBaseName(draft) + "-" + (index + 2) + ".json")
  )
});
assert.equal(limited.code, "duplicate_name_limit", "DUPLICATE_LIMIT_FAILS_CLOSED");

/* ── 12. 부분 실패 결과 모델 ── */
const pair = Contract.buildPairBinding({
  packageId: "pkg-test-0001",
  createdAt: "2026-10-09T09:00:00.000Z",
  baseName: baseName,
  jsonName: "a.json",
  pdfName: "a.pdf",
  draftFingerprint: built.package.contentFingerprint,
  pdfFingerprint: Contract.pdfFingerprint(pdfOk)
});
assert.ok(pair.draftFingerprint && pair.pdfFingerprint, "PAIR_BINDING_FINGERPRINTS");

const complete = Contract.buildUploadOutcome({
  packageId: "pkg-test-0001",
  pair: pair,
  json: { ok: true, id: "json-id", name: "a.json" },
  pdf: { ok: true, id: "pdf-id", name: "a.pdf" }
});
assert.equal(complete.status, "complete", "COMPLETE_STATUS");
assert.equal(complete.partial, false, "COMPLETE_NOT_PARTIAL");

const jsonOnly = Contract.buildUploadOutcome({
  packageId: "pkg-test-0001",
  pair: pair,
  json: { ok: true, id: "json-id", name: "a.json" },
  pdf: { ok: false, code: "pdf_upload_failed", message: "용량 초과" }
});
assert.equal(jsonOnly.status, "partial_json", "PARTIAL_JSON_STATUS");
assert.equal(jsonOnly.partial, true, "PARTIAL_UPLOAD_REPORTED_NOT_SILENT");
assert.equal(jsonOnly.missing, "pdf", "PARTIAL_MISSING_TARGET");
assert.equal(jsonOnly.retryable, true, "PARTIAL_RETRYABLE");
assert.equal(jsonOnly.ok, false, "PARTIAL_IS_NOT_SUCCESS");
assert.equal(jsonOnly.pair.jsonName, "a.json", "PARTIAL_KEEPS_ORIGINAL_JSON_NAME");
assert.equal(jsonOnly.pair.pdfName, "a.pdf", "PARTIAL_KEEPS_ORIGINAL_PDF_NAME");

const partialWithoutPair = Contract.buildUploadOutcome({
  packageId: "pkg-test-0001",
  json: { ok: true, id: "json-id", name: "a.json" },
  pdf: { ok: false, code: "pdf_upload_failed" }
});
assert.equal(partialWithoutPair.retryable, false, "NO_PAIR_BINDING_MEANS_NOT_RETRYABLE");

const pdfOnly = Contract.buildUploadOutcome({
  packageId: "pkg-test-0001",
  pair: pair,
  json: { ok: false, code: "json_upload_failed" },
  pdf: { ok: true, id: "pdf-id", name: "a.pdf" }
});
assert.equal(pdfOnly.status, "partial_pdf", "PARTIAL_PDF_STATUS");
assert.equal(pdfOnly.missing, "json", "PARTIAL_PDF_MISSING_TARGET");

const bothFailed = Contract.buildUploadOutcome({
  packageId: "pkg-test-0001",
  pair: pair,
  json: { ok: false, code: "json_upload_failed" },
  pdf: { ok: false, code: "pdf_upload_failed" }
});
assert.equal(bothFailed.status, "failed", "BOTH_FAILED_STATUS");
assert.equal(bothFailed.retryable, false, "BOTH_FAILED_NOT_RETRYABLE");

/* ── 13. 재시도 쌍 고정 가드 ── */
const guardOk = Contract.pairRetryGuard(jsonOnly, { draft: draft, template: TEMPLATE, pdfBytes: pdfOk });
assert.equal(guardOk.ok, true, "PAIR_RETRY_GUARD_OK");
assert.equal(guardOk.target, "pdf", "PAIR_RETRY_TARGET");

const editedDraft = JSON.parse(JSON.stringify(draft));
editedDraft.items[0].unitPrice = 1234567;
const guardStale = Contract.pairRetryGuard(jsonOnly, { draft: editedDraft, template: TEMPLATE, pdfBytes: pdfOk });
assert.equal(guardStale.ok, false, "EDITED_DRAFT_BLOCKS_RETRY");
assert.equal(guardStale.code, "pending_pair_stale", "PENDING_PAIR_STALE");

const changedPdf = new Uint8Array(256);
[37, 80, 68, 70, 45].forEach((byte, index) => { changedPdf[index] = byte; });
changedPdf[200] = 1;
const guardPdf = Contract.pairRetryGuard(jsonOnly, { draft: draft, template: TEMPLATE, pdfBytes: changedPdf });
assert.equal(guardPdf.code, "pending_pdf_changed", "PENDING_PDF_CHANGED");

const otherTemplate = { savedSkillId: "b66skill_other", fingerprint: "fp-other" };
const guardTemplate = Contract.pairRetryGuard(jsonOnly, { draft: draft, template: otherTemplate, pdfBytes: pdfOk });
assert.equal(guardTemplate.code, "pending_pair_stale", "TEMPLATE_CHANGE_BLOCKS_RETRY");

assert.equal(Contract.pairRetryGuard(null, {}).code, "pending_pair_missing", "NO_OUTCOME_NOT_RETRYABLE");
assert.equal(Contract.pairRetryGuard(complete, { draft: draft, template: TEMPLATE, pdfBytes: pdfOk }).code,
  "pending_pair_incomplete", "COMPLETE_OUTCOME_NOT_RETRYABLE");

/* ── 14. 템플릿 참조: 없음/비활성/지문 불일치 → 적용하지 않는다 ── */
assert.equal(Contract.resolveTemplateReference(null, []).status, "none", "NO_TEMPLATE_REF_STATUS");
assert.equal(Contract.resolveTemplateReference(null, []).reason, "template_reference_missing", "NO_TEMPLATE_REF_REASON");
const unresolved = Contract.resolveTemplateReference({ savedSkillId: "b66skill_missing" }, []);
assert.equal(unresolved.status, "unresolved", "MISSING_SKILL_UNRESOLVED");
const inactive = Contract.resolveTemplateReference({ savedSkillId: "b66skill_x" }, [
  { savedSkillId: "b66skill_x", fingerprint: "fp", approved: true, active: false }
]);
assert.equal(inactive.status, "inactive", "INACTIVE_SKILL_NOT_SUBSTITUTED");
const mismatch = Contract.resolveTemplateReference({ savedSkillId: "b66skill_x", fingerprint: "old" }, [
  { savedSkillId: "b66skill_x", fingerprint: "new", approved: true, active: true }
]);
assert.equal(mismatch.status, "mismatch", "FINGERPRINT_MISMATCH_NOT_SUBSTITUTED");
const noFp = Contract.resolveTemplateReference({ savedSkillId: "b66skill_x" }, [
  { savedSkillId: "b66skill_x", fingerprint: "new", approved: true, active: true }
]);
assert.equal(noFp.status, "mismatch", "MISSING_REF_FINGERPRINT_NOT_ACCEPTED");

const blockedImport = Contract.importPackage(parsed.package, { templates: [] });
assert.equal(blockedImport.ok, false, "UNRESOLVED_TEMPLATE_BLOCKS_IMPORT");
assert.equal(blockedImport.code, "saved_skill_unavailable", "UNRESOLVED_TEMPLATE_CODE");
assert.equal(blockedImport.draft, null, "UNRESOLVED_TEMPLATE_RETURNS_NO_DRAFT");
assert.ok(blockedImport.message && blockedImport.message.length > 0, "UNRESOLVED_TEMPLATE_MESSAGE");

const inactiveImport = Contract.importPackage(parsed.package, {
  templates: [{ savedSkillId: TEMPLATE.savedSkillId, fingerprint: TEMPLATE.fingerprint, approved: false, active: true }]
});
assert.equal(inactiveImport.code, "saved_skill_inactive", "INACTIVE_TEMPLATE_BLOCKED");

const mismatchImport = Contract.importPackage(parsed.package, {
  templates: [{ savedSkillId: TEMPLATE.savedSkillId, fingerprint: "other", approved: true, active: true }]
});
assert.equal(mismatchImport.code, "template_fingerprint_mismatch", "MISMATCHED_TEMPLATE_BLOCKED");

const noTemplatePackage = Contract.buildPackage({ draft: draft, packageId: "pkg-no-template" }).package;
const noTemplateImport = Contract.importPackage(noTemplatePackage, { templates: [] });
assert.equal(noTemplateImport.ok, false, "MISSING_TEMPLATE_REFERENCE_BLOCKED");
assert.equal(noTemplateImport.code, "template_authority_unverified", "MISSING_TEMPLATE_REFERENCE_CODE");

const relaxedImport = Contract.importPackage(parsed.package, { templates: [], requireApprovedTemplate: false });
assert.equal(relaxedImport.ok, true, "EXPLICIT_RELAXATION_ALLOWS_DRAFT_ONLY_READ");
assert.equal(relaxedImport.certifiedPdfReady, false, "RELAXED_IMPORT_NOT_PDF_READY");

/* ── 15. 손실 발생 저장 거부 ── */
const lossyDraft = JSON.parse(JSON.stringify(draft));
lossyDraft.detailGroups[0].summaryItemId = "item-999";
assert.equal(Contract.buildPackage({ draft: lossyDraft }).ok, false, "LOSSY_DRAFT_REJECTED");
assert.equal(Contract.buildPackage({ draft: null }).code, "invalid_draft", "NULL_DRAFT_REJECTED");

/* ── 16. 모델 호출 0 ── */
const contractSource = readModule("quote-drive-contract.js");
const clientSource = readModule("quote-drive-client.js");
const combined = contractSource + clientSource;
assert.ok(!/(kilo\/|sensenova|space-bunny|nemotron|openai|anthropic|gpt-|claude|glm-)/i.test(combined),
  "MODEL_PROVIDER_IDS=0");
assert.ok(!/XMLHttpRequest|WebSocket|EventSource/.test(combined), "NO_UNBOUNDED_TRANSPORT");
assert.ok(!/localStorage|sessionStorage|indexedDB/.test(combined), "TOKEN_NEVER_PERSISTED_SOURCE=YES");
assert.ok(combined.indexOf("https://www.googleapis.com") !== -1, "GOOGLE_ENDPOINT_DECLARED");
assert.ok(combined.indexOf("https://oauth2.googleapis.com") !== -1, "GOOGLE_OAUTH_ENDPOINT_DECLARED");

console.log("B66_DRIVE_CONTRACT=PASS");
console.log("EDITABLE_JSON_ROUND_TRIP=PASS");
console.log("DETAIL_GROUPS_PRESERVED=PASS");
console.log("CALCULATION_POLICY_PRESERVED=PASS");
console.log("FIELD_LEVEL_LOSSLESS_PROOF=PASS (fields=" + pairs.length + ")");
console.log("LOSSY_FILE_REJECTED_ON_READ=PASS");
console.log("QUOTECORE_RECALCULATES_ON_IMPORT=PASS");
console.log("TAMPERED_TOTALS_NEVER_TRUSTED=PASS");
console.log("QUOTE_BODY_TAMPER_DETECTED=PASS");
console.log("STORED_TOTALS_NEVER_WRITTEN=PASS");
console.log("CORRUPT_JSON_REJECTED=PASS");
console.log("UNSUPPORTED_SCHEMA_VERSION_REJECTED=PASS");
console.log("OVERSIZED_FILE_REJECTED=PASS");
console.log("PDF_FORMAT_VALIDATED=PASS");
console.log("DUPLICATE_NAME_NO_OVERWRITE=PASS");
console.log("PARTIAL_UPLOAD_REPORTED_NOT_SILENT=PASS");
console.log("PAIR_BINDING_FROZEN=PASS");
console.log("PENDING_PAIR_STALE_BLOCKED=PASS");
console.log("IDENTITY_FIELD_NEVER_AUTHORITY=PASS");
console.log("UNRESOLVED_TEMPLATE_NOT_APPLIED=PASS");
console.log("JSON_PDF_PAIR_LINKED=PASS");
console.log("MODEL_CALLS_FOR_STORAGE=0");
console.log("SLICE_A_OFFLINE_TESTED=PASS");
