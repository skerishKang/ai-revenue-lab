const assert = require("node:assert");
const Core = require("../quote-core.js");

/* KOREAN_MONEY_INPUT_CONTRACT — 콤마/빈값/불량 문자열 모두 NaN 없이 처리 */
assert.equal(Core.parseMoney("1000000"), 1000000, "plain digits");
assert.equal(Core.parseMoney("1,000,000"), 1000000, "comma display string");
assert.equal(Core.parseMoney("1500000"), 1500000, "plain digits 2");
assert.equal(Core.parseMoney("1,500,000"), 1500000, "comma display string 2");
assert.equal(Core.parseMoney(""), 0, "empty string");
assert.equal(Core.parseMoney(null), 0, "null");
assert.equal(Core.parseMoney("abc"), 0, "garbage string");
assert.equal(Core.parseMoney("12a3"), 0, "mixed garbage");
assert.equal(Core.parseMoney("-500"), 0, "negative rejected");
assert.ok(Number.isFinite(Core.parseMoney("1,000,000")), "never NaN");
assert.equal(Core.formatMoney(1430000), "₩1,430,000", "money display");
assert.equal(Core.formatInputNumber(1500000), "1,500,000", "input display format");

/* VAT_EXCLUSIVE_CONTRACT — 공급가액에 10% 추가 */
const items = [
  { id: "item-1", name: "서비스 구축", qty: 1, unitPrice: 1000000 },
  { id: "item-2", name: "운영 지원", qty: 1, unitPrice: 300000 }
];
let t = Core.computeTotals(items, "EXCLUSIVE");
assert.deepEqual([t.supply, t.vat, t.grand], [1300000, 130000, 1430000], "EXCLUSIVE math");

/* VAT_INCLUSIVE_CONTRACT — 표시 금액 합계가 곧 합계, 공급가액/부가세 분리 */
t = Core.computeTotals(items, "INCLUSIVE");
assert.deepEqual([t.supply, t.vat, t.grand], [1181818, 118182, 1300000], "INCLUSIVE math");
assert.equal(t.supply + t.vat, t.grand, "INCLUSIVE split always sums");

/* VAT_EXEMPT_CONTRACT — 면세 */
t = Core.computeTotals(items, "EXEMPT");
assert.deepEqual([t.supply, t.vat, t.grand], [1300000, 0, 1300000], "EXEMPT math");

/* 품목 금액 반올림·소수 수량·불량 값 견고성 */
t = Core.computeTotals([{ qty: 2.5, unitPrice: 333333 }], "EXCLUSIVE");
assert.equal(t.supply, Math.round(2.5 * 333333), "round per item");
t = Core.computeTotals([{ qty: "1,000", unitPrice: "1,500,000" }], "EXCLUSIVE");
assert.equal(t.supply, 1500000000, "comma strings inside items");
t = Core.computeTotals([{ qty: "abc", unitPrice: "1,000,000" }], "EXCLUSIVE");
assert.equal(t.supply, 0, "garbage qty never poisons totals");
t = Core.computeTotals([], "EXCLUSIVE");
assert.deepEqual([t.supply, t.vat, t.grand], [0, 0, 0], "empty items");
t = Core.computeTotals(items, "UNKNOWN_MODE");
assert.equal(t.mode, "EXCLUSIVE", "unknown mode falls back to EXCLUSIVE");

/* VALID_UNTIL_CONTRACT — 견적일 + 유효기간 파생, 파싱 실패는 null */
assert.equal(Core.computeValidUntil("2026-09-27", 30), "2026-10-27", "month rollover");
assert.equal(Core.computeValidUntil("2026-09-27", "30"), "2026-10-27", "string days");
assert.equal(Core.computeValidUntil("2026-01-01", 7), "2026-01-08", "same month");
assert.equal(Core.computeValidUntil("2026-12-15", 30), "2027-01-14", "year rollover");
assert.equal(Core.computeValidUntil("2024-02-29", 1), "2024-03-01", "leap year");
assert.equal(Core.computeValidUntil("not-a-date", 30), null, "garbage date");
assert.equal(Core.computeValidUntil("2026-13-40", 30), null, "impossible date");
assert.equal(Core.computeValidUntil("2026-09-27", "abc"), null, "garbage days");
assert.equal(Core.computeValidUntil("2026-09-27", 0), null, "non-positive days");

/* QUOTEDRAFT_SCHEMA_CONTRACT — 기본 draft 구조 */
const draft = Core.createDefaultDraft();
assert.equal(draft.schemaVersion, 1, "schema version");
["meta", "sender", "recipient", "items", "tax", "memo"].forEach((k) => {
  assert.ok(k in draft, `draft has ${k}`);
});
["quoteNo", "issueDate", "validDays", "source"].forEach((k) => {
  assert.ok(k in draft.meta, `meta has ${k}`);
});
["company", "rep", "bizNo", "address", "phone", "email", "presetId"].forEach((k) => {
  assert.ok(k in draft.sender, `sender has ${k}`);
});
["company", "person", "address", "email"].forEach((k) => {
  assert.ok(k in draft.recipient, `recipient has ${k}`);
});
assert.equal(draft.items.length, 2, "default items");
assert.equal(draft.tax.mode, "EXCLUSIVE", "default tax mode");

/* DRAFT_RESTORE_CONTRACT — 정상·부분·손상 입력 */
assert.deepEqual(Core.normalizeDraft(JSON.parse(JSON.stringify(draft))), draft, "round trip");
const partial = Core.normalizeDraft({
  schemaVersion: 1,
  items: [{ id: "a", name: "X", qty: 2, unitPrice: 500 }],
  tax: { mode: "INCLUSIVE" }
});
assert.equal(partial.items[0].qty, 2, "partial draft keeps items");
assert.equal(partial.tax.mode, "INCLUSIVE", "partial draft keeps tax mode");
assert.equal(partial.meta.validDays, 30, "partial draft fills defaults");
assert.equal(Core.normalizeDraft("garbage"), null, "string input rejected");
assert.equal(Core.normalizeDraft(null), null, "null rejected");
assert.equal(Core.normalizeDraft({ schemaVersion: 99 }), null, "wrong schema rejected");
const badShape = Core.normalizeDraft({ schemaVersion: 1, items: "not-an-array" });
assert.ok(Array.isArray(badShape.items) && badShape.items.length === 2, "non-array items fall back to defaults");
const badItems = Core.normalizeDraft({ schemaVersion: 1, items: [{ qty: -3, unitPrice: "x" }] });
assert.equal(badItems.items[0].qty, 1, "negative qty falls back");
assert.equal(badItems.items[0].unitPrice, 0, "garbage price falls back");

console.log("KOREAN_MONEY_INPUT_CONTRACT=PASS");
console.log("VAT_EXCLUSIVE_CONTRACT=PASS");
console.log("VAT_INCLUSIVE_CONTRACT=PASS");
console.log("VAT_EXEMPT_CONTRACT=PASS");
console.log("VALID_UNTIL_CONTRACT=PASS");
console.log("QUOTEDRAFT_SCHEMA_CONTRACT=PASS");
console.log("DRAFT_RESTORE_CONTRACT=PASS");
console.log("B66_QUOTE_CORE_UNIT=PASS");
