const assert = require("node:assert");
const crypto = require("node:crypto");
const Template = require("../quote-template.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) =>
  assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);

const clone = (value) => JSON.parse(JSON.stringify(value));
const builtin = () => Template.builtInTemplate();
const builtinContent = () => clone(builtin().content);
const nodeSha256 = (text) => crypto.createHash("sha256").update(text, "utf8").digest("hex");

/* TEMPLATE_FINGERPRINT_DETERMINISTIC — 자체 구현이 표준 SHA-256 과 바이트 단위로 일치해야 한다 */
[
  "",
  "abc",
  "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
  "a".repeat(1000),
  "견적서",
  "샘플 공급사 · 1,500,000원",
  "\u{1F600}emoji",
  "\ud800 unpaired high",
  "unpaired low \udfff"
].forEach((sample) => {
  eq(Template.sha256Hex(sample), nodeSha256(sample), `sha256 vector ${JSON.stringify(sample)}`);
});
eq(Template.sha256Hex(""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "sha256 empty");
eq(Template.sha256Hex("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "sha256 abc");

/* 결정적 차분: 무작위(시드 고정) 문자열에서도 node:crypto 와 완전히 동일 */
let seed = 20260928;
const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
for (let i = 0; i < 40; i += 1) {
  const length = Math.floor(rnd() * 400);
  let sample = "";
  for (let k = 0; k < length; k += 1) sample += String.fromCharCode(Math.floor(rnd() * 0x10000));
  eq(Template.sha256Hex(sample), nodeSha256(sample), `sha256 differential #${i}`);
}
check(Template.sha256Hex("").length === 64, "TEMPLATE_FINGERPRINT_DETERMINISTIC: 64 hex chars");

/* canonicalJson — 키 순서에 의존하지 않는 결정적 직렬화 */
eq(
  Template.canonicalJson({ b: 1, a: [2, { d: 3, c: 4 }] }),
  Template.canonicalJson({ a: [2, { c: 4, d: 3 }], b: 1 }),
  "canonicalJson ignores key insertion order"
);
eq(Template.canonicalJson([1, 2, 3]), "[1,2,3]", "canonicalJson preserves array order");
check(
  (() => { try { Template.canonicalJson({ a: Number.NaN }); return false; } catch (err) { return true; } })(),
  "canonicalJson rejects non-finite numbers"
);

/* QUOTE_TEMPLATE_PROFILE_CONTRACT — 내장 기본 프로필 구조 */
const profile = builtin();
check(profile.id === Template.BUILTIN_TEMPLATE_ID, "built-in template id");
check(profile.name === Template.BUILTIN_TEMPLATE_NAME, "built-in template name");
check(profile.builtin === true, "built-in flag");
check(profile.schemaVersion === Template.TEMPLATE_SCHEMA_VERSION, "built-in schema version");
check(typeof profile.fingerprint === "string" && /^[0-9a-f]{64}$/.test(profile.fingerprint), "built-in fingerprint");
eq(profile.content.sections, ["title", "meta", "parties", "items", "totals", "memo", "mark"], "built-in sections");
eq(
  profile.content.items.columns.map((column) => column.key),
  ["name", "qty", "unitPrice", "amount"],
  "built-in item columns"
);
check(profile.content.page.size === "A4", "built-in page size");
check(profile.content.totals.supplyLabel === "공급가액", "built-in supply label");
check(profile.content.totals.grandLabel === "합계", "built-in grand label");
check(profile.content.totals.vatLabels.EXCLUSIVE === "부가세", "built-in vat label EXCLUSIVE");
check(profile.content.totals.vatLabels.INCLUSIVE === "부가세 (포함가 분리)", "built-in vat label INCLUSIVE");
check(profile.content.totals.vatLabels.EXEMPT === "부가세 (면세)", "built-in vat label EXEMPT");
check(profile.content.mark.text === "견적서 베타", "built-in mark text");
check(profile.content.fallbackText === "-", "built-in dash fallback");

/* 정규화된 내장 content 는 원본을 그대로 보존한다(왕복 항등) */
eq(
  Template.normalizeTemplateContent(profile.content),
  profile.content,
  "built-in content round-trips unchanged"
);
check(profile.fingerprint === Template.templateFingerprint(profile.content), "built-in fingerprint is derived from content");

const extendedContent = builtinContent();
extendedContent.sections = ["title", "meta", "parties", "project", "items", "totals", "memo", "mark"];
extendedContent.project = { prefix: "건   명 : " };
extendedContent.items.columns = [
  { key: "no", label: "NO", width: "6%", align: "center" },
  { key: "name", label: "품명", width: "20%", align: "left" },
  { key: "spec", label: "규격", width: "22%", align: "left" },
  { key: "unit", label: "단위", width: "8%", align: "center" },
  { key: "qty", label: "수량", width: "8%", align: "right" },
  { key: "unitPrice", label: "단가", width: "12%", align: "right" },
  { key: "amount", label: "금액", width: "14%", align: "right" },
  { key: "note", label: "비고", width: "10%", align: "left" }
];
const extendedNormalized = Template.normalizeTemplateContent(extendedContent);
check(extendedNormalized !== null, "extended quotation columns normalize");
eq(
  extendedNormalized.items.columns.map((column) => column.key),
  ["no", "name", "spec", "unit", "qty", "unitPrice", "amount", "note"],
  "eight-column quotation order is preserved"
);
eq(extendedNormalized.project, { prefix: "건   명 : " }, "optional project presentation section is preserved");
eq(
  Template.normalizeTemplateContent(builtinContent()),
  builtinContent(),
  "existing four-column builtin stays canonical after extended-column support"
);

const writtenContent = builtinContent();
writtenContent.sections = ["title", "meta", "parties", "items", "totals", "writtenTotal", "memo", "mark"];
writtenContent.writtenTotal = { prefix: "일금 ", suffix: "원정[부가세포함]" };
const writtenNormalized = Template.normalizeTemplateContent(writtenContent);
check(writtenNormalized !== null, "written-total template section normalizes");
eq(
  writtenNormalized.writtenTotal,
  { prefix: "일금 ", suffix: "원정[부가세포함]" },
  "template owns written-total presentation text only"
);
eq(
  Template.normalizeTemplateContent(builtinContent()),
  builtinContent(),
  "optional written-total support does not change built-in canonical content"
);

const detailPageContent = builtinContent();
detailPageContent.sections = ["title", "meta", "parties", "items", "totals", "detailPages", "memo", "mark"];
detailPageContent.detailPages = {
  titlePrefix: "상세내역  ",
  subtotalLabel: "소 계",
  columns: [
    { key: "no", label: "NO", width: "6%", align: "center" },
    { key: "name", label: "품명", width: "20%", align: "left" },
    { key: "spec", label: "규격", width: "22%", align: "left" },
    { key: "unit", label: "단위", width: "8%", align: "center" },
    { key: "qty", label: "수량", width: "8%", align: "right" },
    { key: "unitPrice", label: "단가", width: "12%", align: "right" },
    { key: "amount", label: "금액", width: "14%", align: "right" },
    { key: "note", label: "비고", width: "10%", align: "left" }
  ]
};
const detailPageNormalized = Template.normalizeTemplateContent(detailPageContent);
check(detailPageNormalized !== null, "optional detail-pages contract normalizes");
eq(detailPageNormalized.detailPages.titlePrefix, "상세내역  ", "detail page title prefix preserved");
eq(detailPageNormalized.detailPages.subtotalLabel, "소 계", "detail page subtotal label preserved");
eq(
  detailPageNormalized.detailPages.columns.map((column) => column.key),
  ["no", "name", "spec", "unit", "qty", "unitPrice", "amount", "note"],
  "detail page columns preserve approved order"
);
eq(
  Template.normalizeTemplateContent(builtinContent()),
  builtinContent(),
  "optional detail-pages support does not change built-in canonical content"
);

const formalContent = builtinContent();
formalContent.layoutVariant = "formal-grid-v1";
formalContent.meta.issueDateFormat = "yyyy. mm.";
formalContent.sender.contactPrefix = "MP : ";
formalContent.recipient.suffix = "귀중";
formalContent.items.minRows = 9;
formalContent.items.heading = "(1) 샘플 내역";
formalContent.summaryTerms = {
  validity: { label: "유효기간 : ", valuePrefix: "발행일로부터 ", valueSuffix: "일" },
  rows: [
    { label: "납품기간 : ", value: "협의" },
    { label: "결제조건 : ", value: "협의" }
  ]
};
formalContent.totals.supplyLabel = "(1) {firstItemName} 합계 (부가세별도)";
formalContent.memo.heading = "<특기사항>";
formalContent.sections = ["title", "meta", "parties", "items", "totals", "detailPages", "memo", "mark"];
formalContent.detailPages = {
  titlePrefix: "",
  subtotalLabel: "소 계",
  finalLabel: "총 계",
  mergeRepeatedName: true,
  columns: [
    { key: "name", label: "품명", width: "22%", align: "left" },
    { key: "spec", label: "규격", width: "34%", align: "left" },
    { key: "qty", label: "수량", width: "5%", align: "right" },
    { key: "unit", label: "단위", width: "5%", align: "center" },
    { key: "unitPrice", label: "단가", width: "11%", align: "right" },
    { key: "amount", label: "금액", width: "11%", align: "right" },
    { key: "note", label: "비고", width: "12%", align: "left" }
  ]
};
const formalNormalized = Template.normalizeTemplateContent(formalContent);
check(formalNormalized !== null, "formal-grid presentation options normalize");
eq(formalNormalized.layoutVariant, "formal-grid-v1", "formal layout variant preserved");
eq(formalNormalized.meta.issueDateFormat, "yyyy. mm.", "bounded issue-date presentation format preserved");
eq(formalNormalized.sender.contactPrefix, "MP : ", "sender contact prefix is presentation-only");
eq(formalNormalized.recipient.suffix, "귀중", "recipient suffix is presentation-only");
eq(formalNormalized.items.minRows, 9, "bounded summary minimum rows preserved");
eq(formalNormalized.items.heading, "(1) 샘플 내역", "optional summary item heading preserved");
eq(formalNormalized.summaryTerms.validity.valuePrefix, "발행일로부터 ", "dynamic validity presentation prefix preserved");
eq(formalNormalized.summaryTerms.rows.length, 2, "bounded recurring summary terms preserved");
eq(formalNormalized.totals.supplyLabel, "(1) {firstItemName} 합계 (부가세별도)", "first-item display token stays inert in template");
eq(formalNormalized.memo.heading, "<특기사항>", "memo heading is presentation-only");
eq(formalNormalized.detailPages.mergeRepeatedName, true, "detail repeated-name merge is opt-in");
eq(formalNormalized.detailPages.finalLabel, "총 계", "optional detail final label is presentation-only");
eq(
  Template.normalizeTemplateContent(builtinContent()),
  builtinContent(),
  "formal-grid options do not alter built-in canonical content"
);
const invalidFormal = builtinContent();
invalidFormal.layoutVariant = "company-secret-layout";
check(Template.normalizeTemplateContent(invalidFormal) === null, "unknown layout variant fails closed");
const invalidRows = builtinContent();
invalidRows.items.minRows = Template.MAX_SUMMARY_MIN_ROWS + 1;
check(Template.normalizeTemplateContent(invalidRows) === null, "unbounded summary filler rows fail closed");
const invalidDateFormat = builtinContent();
invalidDateFormat.meta.issueDateFormat = "javascript-date";
check(Template.normalizeTemplateContent(invalidDateFormat) === null, "unknown issue-date presentation format fails closed");
const invalidTerms = builtinContent();
invalidTerms.summaryTerms = {
  rows: Array.from({ length: Template.MAX_SUMMARY_TERMS_ROWS + 1 }, (_, i) => ({ label: "L" + i, value: "V" + i }))
};
check(Template.normalizeTemplateContent(invalidTerms) === null, "unbounded summary terms fail closed");

/* TEMPLATE_FINGERPRINT_DETERMINISTIC — 동일 내용 → 동일 지문, 스타일 변경 → 다른 지문 */
const contentA = builtinContent();
const contentB = builtinContent();
check(Template.templateFingerprint(contentA) === Template.templateFingerprint(contentB), "same content, same fingerprint");

const restyled = builtinContent();
restyled.style.accent = "#1d4ed8";
check(Template.templateFingerprint(restyled) !== Template.templateFingerprint(contentA), "style change changes fingerprint");

const relabelled = builtinContent();
relabelled.totals.supplyLabel = "공급가";
check(Template.templateFingerprint(relabelled) !== Template.templateFingerprint(contentA), "label change changes fingerprint");

/* id/name 은 내용이 아니므로 지문을 바꾸지 않는다 */
const renamedProfile = Template.buildProfile({
  id: "custom-1",
  name: "우리 회사 양식",
  builtin: false,
  isDefault: false,
  createdAt: "2026-09-28T00:00:00.000Z",
  updatedAt: "2026-09-28T00:00:00.000Z",
  content: contentA
});
check(renamedProfile.fingerprint === profile.fingerprint, "id/name do not change fingerprint");

/* 손상 입력은 fail-closed (호출측이 내장 기본으로 fallback) */
check(Template.normalizeTemplate(null) === null, "null template rejected");
check(Template.normalizeTemplate("nope") === null, "string template rejected");
check(Template.normalizeTemplate([]) === null, "array template rejected");
check(Template.normalizeTemplate({ schemaVersion: 99, id: "x", content: contentA }) === null, "wrong schema version rejected");
check(Template.normalizeTemplate({ schemaVersion: 1, id: "", content: contentA }) === null, "invalid id rejected");
check(Template.normalizeTemplate({ schemaVersion: 1, id: "x" }) === null, "missing content rejected");
check(
  Template.normalizeTemplate({
    schemaVersion: 1,
    id: "x",
    content: Object.assign(builtinContent(), { sections: ["nope"] })
  }) === null,
  "invalid sections rejected"
);
check(
  Template.normalizeTemplate({
    schemaVersion: 1,
    id: "x",
    content: Object.assign(builtinContent(), { items: { columns: [{ key: "name" }] } })
  }) === null,
  "partial column set rejected"
);
check(
  Template.normalizeTemplate({
    schemaVersion: 1,
    id: "x",
    content: Object.assign(builtinContent(), {
      items: { columns: [{ key: "name" }, { key: "name" }, { key: "qty" }, { key: "amount" }] }
    })
  }) === null,
  "duplicate column key rejected"
);

/* 지문 불일치(변조) → 거부 */
const tampered = Template.serializeTemplate(profile);
tampered.fingerprint = "0".repeat(64);
check(Template.normalizeTemplate(tampered) === null, "tampered fingerprint rejected");
check(Template.normalizeTemplate(Template.serializeTemplate(profile)) !== null, "intact serialized template accepted");

/* FORBIDDEN_TEMPLATE_KEYS — 계산 authority/자격증명/원본 바이트/신뢰 합계 */
const forbiddenSamples = [
  { subtotal: 1000 },
  { supply: 1000 },
  { vat: 100 },
  { grand: 1100 },
  { total: 1100 },
  { trustedTotals: { grand: 1100 } },
  { computed_totals: { supply: 1 } },
  { apiKey: "sk-x" },
  { accessToken: "t" },
  { credentials: { password: "p" } },
  { provider_id: "kilo" },
  { model_id: "some-model" },
  { model_policy_ref: "x" },
  { raw_bytes: "AAAA" },
  { data_url: "data:application/pdf;base64,AAAA" },
  { uploadedBytes: 10 },
  { tools: ["x"] },
  { authority: "root" },
  { nested: { deeper: { vat: 10 } } },
  { items: [{ subtotal: 5 }] }
];
forbiddenSamples.forEach((sample, index) => {
  check(Template.findForbiddenKeys(sample).length > 0, `forbidden keys detected #${index}`);
});

check(Template.findForbiddenKeys(profile.content).length === 0, "built-in content has no forbidden keys");
check(Template.findForbiddenKeys(Template.serializeTemplate(profile)).length === 0, "serialized template has no forbidden keys");

const leaky = Template.serializeTemplate(profile);
leaky.content = Object.assign(clone(profile.content), { subtotal: 1234 });
check(Template.findForbiddenKeys(leaky).length > 0, "injected subtotal detected");
check(Template.normalizeTemplate(leaky) === null, "template carrying trusted totals is rejected");

/* 화이트리스트 정규화 — 모르는 키는 보존되지 않는다 */
const noisy = Template.normalizeTemplateContent(
  Object.assign(builtinContent(), { subtotal: 1234, unknownSection: { a: 1 } })
);
check(noisy !== null, "noisy content still normalizes");
check(!Object.prototype.hasOwnProperty.call(noisy, "subtotal"), "unknown/forbidden key is not preserved");
check(!Object.prototype.hasOwnProperty.call(noisy, "unknownSection"), "unknown key is dropped");
eq(
  Template.templateFingerprint(noisy),
  Template.templateFingerprint(builtinContent()),
  "dropped keys do not change the fingerprint"
);

/* 값 검증 실패는 내장 기본값으로 복구된다 */
const sloppy = Template.normalizeTemplateContent({
  sections: ["items"],
  items: { columns: [{ key: "name", label: "품목", width: "42%", align: "sideways" }].concat(
    ["qty", "unitPrice", "amount"].map((key) => ({ key: key, label: key, width: "", align: "nope" }))
  ) },
  style: { accent: "javascript:alert(1)", titleRule: "<script>", headerAlignment: "middle" },
  page: { size: "A4", margin: "10mm" }
});
check(sloppy !== null, "sloppy content normalizes against defaults");
check(sloppy.style.accent === "#17202a", "invalid accent colour falls back to the built-in token");
check(sloppy.style.titleRule === "2px solid #111827", "invalid border token falls back");
check(sloppy.style.headerAlignment === "space-between", "invalid alignment falls back");
check(sloppy.totals.supplyLabel === "공급가액", "missing label falls back to built-in");
check(sloppy.meta.quoteNoPrefix === "견적번호  ", "missing prefix falls back to built-in");

/* 문자열 bound */
const longText = "가".repeat(Template.MAX_TEMPLATE_STRING_CHARS * 2);
const bounded = Template.normalizeTemplateContent(
  Object.assign(builtinContent(), { title: { text: longText } })
);
check(bounded.title.text.length === Template.MAX_TEMPLATE_STRING_CHARS, "long string is bounded");

/* 구조가 깨지면 조용한 기본값 대신 fail-closed 로 떨어진다 */
check(
  Template.normalizeTemplateContent({ sections: ["items"], items: { columns: ["name", "qty", "unitPrice", "amount"] } }) === null,
  "non-object column entries fail closed"
);
check(Template.normalizeTemplateContent({ items: { columns: [] } }) === null, "missing sections fail closed");
check(Template.normalizeTemplateContent(builtinContent()) !== null, "valid content normalizes");

/* APPROVAL_REQUIRED_FOR_USER_PROFILE — #3181 Candidate → explicit Approval → Profile 경계 */
check(Template.APPROVAL_SCHEMA_VERSION === 1, "approval schema version");
check(Template.SLOT_SUPPORT === "private_asset_v1", "slot support uses private account-bound asset refs");
check(Template.ALLOWED_ALIGNMENTS.indexOf("right") !== -1, "alignment enum is exported");
check(Template.isBuiltInException(profile) === true, "built-in is the trusted exception");
check(profile.approved === true && profile.approvalBasis === "trusted_builtin", "built-in is approved by exception");
check(profile.approval === null, "built-in carries no approval evidence");

const candidate = Template.buildProfile({
  id: "u1", name: "u1", builtin: false, isDefault: false, approval: null,
  createdAt: "", updatedAt: "", content: builtinContent()
});
check(candidate.approved === false, "a profile without approval evidence is not approved");
check(candidate.approvalBasis === "unapproved", "unapproved basis is recorded");
check(Template.isApprovedProfile(candidate) === false, "unapproved profile is not an active profile");
check(Template.isBuiltInException(candidate) === false, "a user profile is not the built-in exception");

const goodEvidence = {
  schemaVersion: 1,
  status: "approved",
  contentFingerprint: candidate.fingerprint,
  approvedBy: "central-cto",
  approvedAt: "2026-09-28T05:00:00Z"
};
const approvedCandidate = Template.buildProfile({
  id: "u1", name: "u1", builtin: false, isDefault: false, approval: goodEvidence,
  createdAt: "", updatedAt: "", content: builtinContent()
});
check(approvedCandidate.approved === true, "matching approval evidence activates the profile");
check(approvedCandidate.approvalBasis === "explicit_approval", "explicit approval basis is recorded");
check(approvedCandidate.fingerprint === candidate.fingerprint, "approval does not change the content fingerprint");

/* negative: 결함 있는 승인 증거는 전부 거부된다 */
[
  null, {}, "approved",
  Object.assign({}, goodEvidence, { schemaVersion: 9 }),
  Object.assign({}, goodEvidence, { status: "candidate" }),
  Object.assign({}, goodEvidence, { contentFingerprint: "f".repeat(64) }),
  Object.assign({}, goodEvidence, { contentFingerprint: "not-a-hash" }),
  Object.assign({}, goodEvidence, { approvedBy: "" }),
  Object.assign({}, goodEvidence, { approvedBy: "a" }),
  Object.assign({}, goodEvidence, { approvedBy: "<script>" }),
  Object.assign({}, goodEvidence, { approvedAt: "2026-09-28 05:00:00" }),
  Object.assign({}, goodEvidence, { approvedAt: "" }),
  Object.assign({}, goodEvidence, { approvalRef: "<bad>" })
].forEach((evidence, index) => {
  check(Template.normalizeApproval(evidence, candidate.fingerprint) === null, `invalid approval rejected #${index}`);
});
check(Template.normalizeApproval(goodEvidence, candidate.fingerprint) !== null, "valid approval accepted");
check(Template.approvalIsValid(goodEvidence, candidate.fingerprint) === true, "approvalIsValid confirms a match");

/* CONTENT_CHANGE_INVALIDATES_APPROVAL — 지문이 바뀌면 승인은 무효다 */
const changedContent = builtinContent();
changedContent.style.accent = "#8a1f1f";
check(Template.templateFingerprint(changedContent) !== candidate.fingerprint, "content change moves the fingerprint");
check(Template.approvalIsValid(goodEvidence, Template.templateFingerprint(changedContent)) === false,
  "content change invalidates the approval");

/* 지문 필드가 내용과 어긋나는 기록은 fail closed 다 */
const mismatchedEntry = Template.serializeTemplate(approvedCandidate);
mismatchedEntry.fingerprint = "0".repeat(64);
check(Template.normalizeTemplate(mismatchedEntry) === null, "fingerprint mismatch fails closed");

/* 내용이 바뀐 저장 항목은 후보로 남되 승인을 보존하지 않는다 */
const staleEntry = Template.serializeTemplate(approvedCandidate);
staleEntry.content = changedContent;
staleEntry.fingerprint = Template.templateFingerprint(changedContent);
const staleNormalized = Template.normalizeTemplate(staleEntry);
check(staleNormalized !== null, "a template with stale approval is still readable as a candidate");
check(staleNormalized.approved === false, "stale approval does not keep the profile approved");
check(staleNormalized.approval === null, "stale approval is dropped, never silently preserved");

/* metadata(이름) 변경은 지문을 바꾸지 않으므로 재승인이 필요 없다 */
const renamedApproved = Template.buildProfile({
  id: "u1", name: "다른 이름", builtin: false, isDefault: false, approval: goodEvidence,
  createdAt: "", updatedAt: "", content: builtinContent()
});
check(renamedApproved.fingerprint === approvedCandidate.fingerprint, "rename keeps the content fingerprint");
check(renamedApproved.approved === true, "rename does not require re-approval");

/* PAGE/ALIGNMENT/SLOT — bounded enum·정규식만 통과한다 */
const pageAlt = Template.normalizeTemplateContent(Object.assign(builtinContent(), {
  page: { size: "A5", margin: "8mm", orientation: "landscape" },
  style: Object.assign({}, builtinContent().style, {
    headerAlignment: "flex-end", metaAlignment: "center", numericAlignment: "left",
    textAlignment: "center", totalsWidth: "420px"
  })
}));
check(pageAlt.page.size === "A5" && pageAlt.page.orientation === "landscape" && pageAlt.page.margin === "8mm",
  "valid page override accepted");
check(pageAlt.style.headerAlignment === "flex-end" && pageAlt.style.metaAlignment === "center",
  "valid alignment override accepted");
check(pageAlt.style.totalsWidth === "420px", "valid totals width accepted");

const pageSloppy = Template.normalizeTemplateContent(Object.assign(builtinContent(), {
  page: { size: "A4} </style><script>alert(1)</script>", margin: "10mm; } body{display:none}", orientation: "diagonal" },
  style: Object.assign({}, builtinContent().style, { headerAlignment: "middle", metaAlignment: "justify" })
}));
check(pageSloppy.page.size === "A4", "invalid page size falls back");
check(pageSloppy.page.margin === "10mm", "invalid page margin falls back");
check(pageSloppy.page.orientation === "portrait", "invalid orientation falls back");
check(pageSloppy.style.headerAlignment === "space-between", "invalid justify falls back");
check(pageSloppy.style.metaAlignment === "right", "invalid alignment falls back");

const slotBad = Template.normalizeTemplateContent(Object.assign(builtinContent(), {
  slots: { logo: "</style><img src=x>", stamp: "" }
}));
check(slotBad.slots.logo === "", "invalid slot reference falls back to empty");
const privateAssetId = "b66asset_" + "a".repeat(32);
const slotOk = Template.normalizeTemplateContent(Object.assign(builtinContent(), {
  slots: { logo: privateAssetId, stamp: "" }
}));
check(slotOk.slots.logo === privateAssetId, "validated private asset reference is preserved");
const slotUrl = Template.normalizeTemplateContent(Object.assign(builtinContent(), {
  slots: { logo: "https://example.test/logo.png", stamp: "" }
}));
check(slotUrl.slots.logo === "", "arbitrary asset URLs are rejected");
const slotData = Template.normalizeTemplateContent(Object.assign(builtinContent(), {
  slots: { logo: "data:image/png;base64,AAAA", stamp: "" }
}));
check(slotData.slots.logo === "", "inline asset bytes are rejected from template persistence");

/* FORGED_BUILTIN_FLAG_BYPASS=0 — builtin:true 플래그만으로는 신뢰되지 않는다 */
const canonicalContent = () => clone(Template.builtInTemplate().content);
const forgedContent = canonicalContent();
forgedContent.totals.supplyLabel = "조작된 공급가액";

const forgedWrongId = Template.buildProfile({
  id: "user-forged", name: "forged", builtin: true, isDefault: true, approval: null,
  createdAt: "", updatedAt: "", content: canonicalContent()
});
check(forgedWrongId.builtin === false, "a forged builtin flag on a non-canonical id is not trusted");
check(forgedWrongId.approved === false, "a forged builtin flag grants no approval");
check(forgedWrongId.approvalBasis === "unapproved", "a forged builtin records the unapproved basis");
check(Template.isBuiltInException(forgedWrongId) === false, "a forged builtin is not the built-in exception");
check(Template.isApprovedProfile(forgedWrongId) === false, "a forged builtin is not an approved profile");

const forgedWrongContent = Template.buildProfile({
  id: Template.BUILTIN_TEMPLATE_ID, name: "forged", builtin: true, isDefault: true, approval: null,
  createdAt: "", updatedAt: "", content: forgedContent
});
check(forgedWrongContent.builtin === false, "the canonical id with non-canonical content is not trusted");
check(forgedWrongContent.approved === false, "the canonical id with non-canonical content is not approved");
check(forgedWrongContent.approvalBasis === "unapproved", "content mismatch records the unapproved basis");
check(Template.isApprovedProfile(forgedWrongContent) === false, "content mismatch is not an approved profile");
check(Template.isCanonicalBuiltInContent(forgedContent) === false, "non-canonical content is rejected");