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
check(sloppy.style.accent === "#111827", "invalid accent colour falls back to the built-in token");
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

/* HTML 이스케이프 단일 구현 */
check(Template.escapeHtml('<b>"x"&\'') === "&lt;b&gt;&quot;x&quot;&amp;&#039;", "escapeHtml escapes markup");
check(Template.isBuiltInTemplate(profile) === true, "isBuiltInTemplate true for built-in");
check(Template.isBuiltInTemplate(renamedProfile) === false, "isBuiltInTemplate false for user template");

/* 잠금: 프로필은 계산 결과를 담지 않는다 */
check(
  Object.keys(profile.content).every((key) => typeof profile.content[key] !== "number" || key === "layoutVersion"),
  "content holds no numeric totals outside layoutVersion"
);

console.log("QUOTE_TEMPLATE_PROFILE_CONTRACT=PASS");
console.log("TEMPLATE_FINGERPRINT_DETERMINISTIC=PASS");
console.log("TEMPLATE_CANONICAL_JSON=PASS");
console.log("TEMPLATE_FORBIDDEN_FIELD_REJECTION=PASS");
console.log("TRUSTED_TOTALS_IN_TEMPLATE=0");
console.log("RAW_SOURCE_FILE_PERSISTENCE=0");
console.log("MODEL_DEPENDENCY=0");
