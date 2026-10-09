/* #3871 Slice A — Google Drive 저장 데이터 계약 오프라인 테스트.
   실제 네트워크·Google 계정·모델 호출은 전혀 사용하지 않는다. */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const Core = require("../quote-core.js");
const Contract = require("../quote-drive-contract.js");
const ServerHistory = require("../quote-history-server.js");

const readModule = (name) => fs.readFileSync(path.join(__dirname, "..", name), "utf8");

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

/* ── 1. 무손실 계약: D1 서버 스냅샷(#3405)이 버리는 값을 보존한다 ── */
const draft = richDraft();
assert.ok(draft, "fixture normalizes");
const serverSnapshot = ServerHistory.draftToHistorySnapshot(draft);
assert.ok(serverSnapshot, "D1 snapshot builds");
assert.ok(!("detailGroups" in serverSnapshot), "D1 스냅샷은 detailGroups를 보존하지 않는다(기대된 기존 동작)");
assert.ok(!("calculationPolicy" in serverSnapshot), "D1 스냅샷은 calculationPolicy를 보존하지 않는다(기대된 기존 동작)");

const built = Contract.buildPackage({
  draft: draft,
  template: {
    savedSkillId: "b66skill_2eb55d822407f626b7a75c8c88d32c40",
    fingerprint: "fp-cgi-v1",
    rendererContract: Contract.RENDERER_CONTRACT,
    label: "CGI 기본 견적서"
  },
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

/* ── 2. 왕복: 저장 → 읽기 → QuoteCore 재계산 ── */
const text = Contract.serializePackage(built.package);
const parsed = Contract.readPackage(text, {});
assert.equal(parsed.ok, true, "package reads back");
assert.equal(parsed.totalsIgnored, false, "정상 파일에는 합계가 없다");
const imported = Contract.importPackage(parsed.package, {
  templates: [{
    savedSkillId: "b66skill_2eb55d822407f626b7a75c8c88d32c40",
    fingerprint: "fp-cgi-v1",
    approved: true,
    active: true
  }]
});
assert.equal(imported.ok, true, "package imports");
assert.equal(imported.recalculated, true, "QUOTECORE_RECALCULATES_ON_IMPORT");
assert.equal(imported.totalsAuthority, "quote-core", "IMPORT_TOTALS_AUTHORITY=quote-core");
assert.deepEqual(imported.draft, draft, "EDITABLE_JSON_ROUND_TRIP=PASS");
const expected = Core.computeDraftTotals(draft);
assert.deepEqual(
  [imported.totals.supply, imported.totals.vat, imported.totals.grand],
  [expected.supply, expected.vat, expected.grand],
  "RECALCULATED_TOTALS_MATCH_QUOTECORE"
);
assert.equal(imported.template.status, "resolved", "APPROVED_TEMPLATE_RESOLVED");
assert.equal(imported.certifiedPdfReady, true, "CERTIFIED_PDF_READY");

/* ── 3. 변조된 합계는 무시되고 QuoteCore 가 다시 계산한다 ── */
const tampered = JSON.parse(text);
tampered.totals = { supply: 1, vat: 1, grand: 1, subtotal: 1 };
tampered.manifest.grand = 1;
const tamperedRead = Contract.readPackage(JSON.stringify(tampered), {});
assert.equal(tamperedRead.ok, true, "tampered file still parses (합계는 권위가 아니다)");
assert.equal(tamperedRead.totalsIgnored, true, "STORED_TOTALS_IGNORED=YES");
assert.equal(tamperedRead.package.totals, null, "STORED_TOTALS_DISCARDED");
const tamperedImport = Contract.importPackage(tamperedRead.package, {});
assert.equal(tamperedImport.ok, true, "tampered file imports");
assert.deepEqual(
  [tamperedImport.totals.supply, tamperedImport.totals.vat, tamperedImport.totals.grand],
  [expected.supply, expected.vat, expected.grand],
  "TAMPERED_TOTALS_NEVER_TRUSTED"
);
assert.notEqual(tamperedImport.totals.grand, 1, "변조값이 결과에 반영되지 않는다");

/* ── 4. 금액 권위를 quote-core 가 아닌 값으로 선언하면 명시 거부 ── */
const wrongAuthority = JSON.parse(text);
wrongAuthority.totalsAuthority = "stored";
assert.equal(Contract.readPackage(JSON.stringify(wrongAuthority), {}).code,
  "totals_authority_unsupported", "FOREIGN_TOTALS_AUTHORITY_REJECTED");

/* ── 5. 손상/위험 JSON 명시 거부 ── */
assert.equal(Contract.readPackage("{not json", {}).code, "invalid_json", "CORRUPT_JSON_REJECTED");
assert.equal(Contract.readPackage("", {}).code, "invalid_json_text", "EMPTY_JSON_REJECTED");
assert.equal(Contract.readPackage(null, {}).code, "invalid_json_text", "NULL_JSON_REJECTED");
assert.equal(Contract.readPackage('{"__proto__":{"polluted":true}}', {}).code,
  "unsafe_json_key", "PROTOTYPE_POLLUTION_REJECTED");
assert.equal(Contract.readPackage(JSON.stringify({ hello: "world" }), {}).code,
  "package_kind_unsupported", "FOREIGN_DOCUMENT_REJECTED");

/* ── 6. 스키마 버전 정책: 구버전·미래 버전 모두 조용히 마이그레이션하지 않는다 ── */
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

/* ── 7. 신원 주장 필드는 권한 근거가 될 수 없으므로 거부 ── */
Contract.FORBIDDEN_IDENTITY_KEYS.forEach((key) => {
  const withIdentity = JSON.parse(text);
  withIdentity[key] = "attacker@example.com";
  const result = Contract.readPackage(JSON.stringify(withIdentity), {});
  assert.equal(result.ok, false, `IDENTITY_FIELD_REJECTED: ${key}`);
  assert.ok(
    result.code === "unsupported_package_field" || result.code === "identity_authority_field_rejected",
    `IDENTITY_FIELD_REJECTED_CODE: ${key} -> ${result.code}`
  );
  /* whitelist 밖이므로 어느 쪽이든 거부된다 — 우회 경로가 없음을 확인 */
});
const unknownField = JSON.parse(text);
unknownField.somethingElse = 1;
assert.equal(Contract.readPackage(JSON.stringify(unknownField), {}).code,
  "unsupported_package_field", "UNKNOWN_FIELD_REJECTED");

/* ── 8. 큰 파일·잘못된 형식 거부 ── */
const oversized = "x".repeat(Contract.MAX_JSON_BYTES + 1);
assert.equal(Contract.readPackage(oversized, {}).code, "json_too_large", "OVERSIZED_JSON_REJECTED");
assert.equal(Contract.readPackage('{"kind":"b66.quote-package","contract":"b66.quote-drive.v1","schemaVersion":1,"quote":{}}', {
  byteLength: Contract.MAX_JSON_BYTES + 1
}).code, "json_too_large", "OVERSIZED_DECLARED_BYTES_REJECTED");
assert.equal(Contract.readPackage(JSON.stringify({ kind: "b66.quote-package", contract: "b66.quote-drive.v1", schemaVersion: 1 }), {}).code,
  "invalid_quote_draft", "MISSING_DRAFT_REJECTED");

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

/* ── 9. 파일명 규칙과 중복 이름(덮어쓰기 금지) ── */
assert.equal(Contract.sanitizeFileNamePart('a/b\\c:d*e?f"g<h>i|j', "fallback"), "a b c d e f g h i j",
  "FILE_NAME_SANITIZED");
assert.equal(Contract.sanitizeFileNamePart("   ", "fallback"), "fallback", "EMPTY_NAME_FALLBACK");
const baseName = Contract.buildBaseName(draft);
assert.ok(baseName.indexOf("PQ-20261009-001") !== -1, "FILE_NAME_CONTAINS_QUOTE_NO");
assert.ok(baseName.indexOf("가나상사") !== -1, "FILE_NAME_CONTAINS_RECIPIENT");
assert.ok(/[\\/:*?"<>|]/.test(baseName) === false, "FILE_NAME_NO_ILLEGAL_CHARS");

const firstPlan = Contract.planUniqueFileNames({ draft: draft, existingNames: [] });
assert.equal(firstPlan.ok, true, "plan builds");
assert.equal(firstPlan.renamed, false, "EMPTY_DRIVE_KEEPS_BASE_NAME");
assert.ok(firstPlan.json.endsWith(".json") && firstPlan.pdf.endsWith(".pdf"), "PLANNED_EXTENSIONS");
const dupPlan = Contract.planUniqueFileNames({ draft: draft, existingNames: [firstPlan.json] });
assert.equal(dupPlan.ok, true, "dup plan builds");
assert.notEqual(dupPlan.json, firstPlan.json, "DUPLICATE_JSON_NAME_NOT_OVERWRITTEN");
assert.equal(dupPlan.pdf, firstPlan.pdf, "PDF_NAME_UNAFFECTED");
const dupBoth = Contract.planUniqueFileNames({
  draft: draft,
  existingNames: [firstPlan.json, firstPlan.pdf, dupPlan.json]
});
assert.equal(dupBoth.renamed, true, "DUPLICATE_SUFFIX_APPLIED");
assert.notEqual(dupBoth.json, dupPlan.json, "SECOND_DUPLICATE_SUFFIX");
const limited = Contract.planUniqueFileNames({
  draft: draft,
  existingNames: [Contract.buildBaseName(draft) + ".json"].concat(
    Array.from({ length: Contract.MAX_DUPLICATE_SUFFIX }, (_, index) =>
      Contract.buildBaseName(draft) + "-" + (index + 2) + ".json")
  )
});
assert.equal(limited.ok, false, "DUPLICATE_LIMIT_FAILS_CLOSED");
assert.equal(limited.code, "duplicate_name_limit", "DUPLICATE_LIMIT_CODE");

/* ── 10. 부분 실패는 조용히 넘어가지 않는다 ── */
const complete = Contract.buildUploadOutcome({
  packageId: "pkg-test-0001",
  json: { ok: true, id: "json-id", name: "a.json" },
  pdf: { ok: true, id: "pdf-id", name: "a.pdf" }
});
assert.equal(complete.status, "complete", "COMPLETE_STATUS");
assert.equal(complete.partial, false, "COMPLETE_NOT_PARTIAL");
assert.equal(complete.reported, true, "OUTCOME_REPORTED");

const jsonOnly = Contract.buildUploadOutcome({
  packageId: "pkg-test-0001",
  json: { ok: true, id: "json-id", name: "a.json" },
  pdf: { ok: false, code: "pdf_upload_failed", message: "용량 초과" }
});
assert.equal(jsonOnly.status, "partial_json", "PARTIAL_JSON_STATUS");
assert.equal(jsonOnly.partial, true, "PARTIAL_UPLOAD_REPORTED_NOT_SILENT");
assert.equal(jsonOnly.missing, "pdf", "PARTIAL_MISSING_TARGET");
assert.equal(jsonOnly.retryable, true, "PARTIAL_RETRYABLE");
assert.deepEqual(jsonOnly.recovery, { action: "retry_missing", target: "pdf" }, "PARTIAL_RECOVERY_PLAN");
assert.equal(jsonOnly.ok, false, "PARTIAL_IS_NOT_SUCCESS");
assert.ok(jsonOnly.message.indexOf("실패") !== -1, "PARTIAL_MESSAGE_VISIBLE");

const pdfOnly = Contract.buildUploadOutcome({
  packageId: "pkg-test-0001",
  json: { ok: false, code: "json_upload_failed" },
  pdf: { ok: true, id: "pdf-id", name: "a.pdf" }
});
assert.equal(pdfOnly.status, "partial_pdf", "PARTIAL_PDF_STATUS");
assert.equal(pdfOnly.missing, "json", "PARTIAL_PDF_MISSING_TARGET");

const bothFailed = Contract.buildUploadOutcome({
  packageId: "pkg-test-0001",
  json: { ok: false, code: "json_upload_failed" },
  pdf: { ok: false, code: "pdf_upload_failed" }
});
assert.equal(bothFailed.status, "failed", "BOTH_FAILED_STATUS");
assert.equal(bothFailed.partial, false, "BOTH_FAILED_NOT_PARTIAL");
assert.equal(bothFailed.retryable, false, "BOTH_FAILED_NOT_AUTO_RETRYABLE");

/* ── 11. 템플릿 참조: 없음/비활성/지문 불일치 → 대체하지 않는다 ── */
assert.equal(Contract.resolveTemplateReference(null, []).status, "none", "NO_TEMPLATE_REF");
const unresolved = Contract.resolveTemplateReference({ savedSkillId: "b66skill_missing" }, []);
assert.equal(unresolved.status, "unresolved", "MISSING_SKILL_UNRESOLVED");
assert.equal(unresolved.reason, "saved_skill_unavailable", "MISSING_SKILL_REASON");
const inactive = Contract.resolveTemplateReference({ savedSkillId: "b66skill_x" }, [
  { savedSkillId: "b66skill_x", fingerprint: "fp", approved: true, active: false }
]);
assert.equal(inactive.status, "inactive", "INACTIVE_SKILL_NOT_SUBSTITUTED");
const mismatch = Contract.resolveTemplateReference({ savedSkillId: "b66skill_x", fingerprint: "old" }, [
  { savedSkillId: "b66skill_x", fingerprint: "new", approved: true, active: true }
]);
assert.equal(mismatch.status, "mismatch", "FINGERPRINT_MISMATCH_NOT_SUBSTITUTED");

const unresolvedImport = Contract.importPackage(parsed.package, { templates: [] });
assert.equal(unresolvedImport.ok, true, "템플릿이 없어도 편집 데이터는 복원된다");
assert.equal(unresolvedImport.template.status, "unresolved", "UNRESOLVED_TEMPLATE_REPORTED");
assert.equal(unresolvedImport.certifiedPdfReady, false, "UNRESOLVED_TEMPLATE_BLOCKS_CERTIFIED_PDF");
assert.deepEqual(unresolvedImport.warnings, ["saved_skill_unavailable"], "UNRESOLVED_TEMPLATE_WARNING");
assert.deepEqual(unresolvedImport.draft, draft, "UNRESOLVED_TEMPLATE_STILL_RESTORES_DRAFT");

/* ── 12. 손실 발생 저장은 거부(무손실 계약) ── */
const lossyDraft = JSON.parse(JSON.stringify(draft));
lossyDraft.detailGroups[0].summaryItemId = "item-999";
assert.equal(Contract.buildPackage({ draft: lossyDraft }).ok, false, "LOSSY_DRAFT_REJECTED");
assert.equal(Contract.buildPackage({ draft: null }).code, "invalid_draft", "NULL_DRAFT_REJECTED");

/* ── 13. 모델 호출 0 ── */
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
console.log("QUOTECORE_RECALCULATES_ON_IMPORT=PASS");
console.log("TAMPERED_TOTALS_NEVER_TRUSTED=PASS");
console.log("STORED_TOTALS_NEVER_WRITTEN=PASS");
console.log("CORRUPT_JSON_REJECTED=PASS");
console.log("UNSUPPORTED_SCHEMA_VERSION_REJECTED=PASS");
console.log("OVERSIZED_FILE_REJECTED=PASS");
console.log("PDF_FORMAT_VALIDATED=PASS");
console.log("DUPLICATE_NAME_NO_OVERWRITE=PASS");
console.log("PARTIAL_UPLOAD_REPORTED_NOT_SILENT=PASS");
console.log("IDENTITY_FIELD_NEVER_AUTHORITY=PASS");
console.log("UNRESOLVED_TEMPLATE_NOT_SUBSTITUTED=PASS");
console.log("JSON_PDF_PAIR_LINKED=PASS");
console.log("MODEL_CALLS_FOR_STORAGE=0");
console.log("SLICE_A_OFFLINE_TESTED=PASS");
