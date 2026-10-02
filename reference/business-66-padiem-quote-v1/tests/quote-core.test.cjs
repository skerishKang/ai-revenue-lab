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

/* KOREAN_MONEY_SHORTHAND — Easy Mode 단가용 결정론적 한국식 금액 파서 */
assert.equal(Core.parseKoreanMoney("1,500,000"), 1500000, "comma money");
assert.equal(Core.parseKoreanMoney("1500000"), 1500000, "plain money");
assert.equal(Core.parseKoreanMoney("₩1,500,000"), 1500000, "won symbol");
assert.equal(Core.parseKoreanMoney("1,500,000원"), 1500000, "won suffix");
assert.equal(Core.parseKoreanMoney("150만원"), 1500000, "manwon shorthand");
assert.equal(Core.parseKoreanMoney("20만"), 200000, "man shorthand");
assert.equal(Core.parseKoreanMoney("1.5만원"), 15000, "decimal man shorthand");
assert.equal(Core.parseKoreanMoney("2억원"), 200000000, "eok shorthand");
assert.equal(Core.parseKoreanMoney("3천원"), 3000, "cheon shorthand");
assert.equal(Core.parseKoreanMoney("0원"), 0, "zero allowed");
assert.equal(Core.parseKoreanMoney("1억5천만원"), null, "mixed unit form fails rather than guesses");
assert.equal(Core.parseKoreanMoney("-5만"), null, "negative shorthand rejected");
assert.equal(Core.parseKoreanMoney("백만원"), null, "non-numeric Korean numeral rejected");
assert.equal(Core.parseKoreanMoney("abc"), null, "garbage rejected");

/* VAT_EXCLUSIVE_CONTRACT — 공급가액에 10% 추가 */
const items = [
  { id: "item-1", name: "서비스 구축", qty: 1, unitPrice: 1000000 },
  { id: "item-2", name: "운영 지원", qty: 1, unitPrice: 300000 }
];
let t = Core.computeTotals(items, "EXCLUSIVE");
assert.deepEqual([t.supply, t.vat, t.grand], [1300000, 130000, 1430000], "EXCLUSIVE math");
assert.deepEqual(
  Object.keys(t).sort(),
  ["amounts", "grand", "mode", "subtotal", "supply", "vat"],
  "STANDARD totals keep the legacy result shape"
);

const floor10000 = { grandRounding: { mode: "FLOOR", unit: 10000 } };
const rounded = Core.computeTotals(
  [{ id: "cgi-summary", name: "ICT환경제어 시스템", qty: 1, unitPrice: 16330000 }],
  "EXCLUSIVE",
  floor10000
);
assert.equal(rounded.supply, 16330000, "reviewed supply remains exact");
assert.equal(rounded.vat, 1633000, "reviewed VAT remains exact");
assert.equal(rounded.rawGrand, 17963000, "raw grand is explicit");
assert.equal(rounded.grand, 17960000, "FLOOR/10000 matches reviewed 2026 family");
assert.equal(rounded.roundingAdjustment, -3000, "rounding adjustment is explicit");
assert.deepEqual(rounded.calculationPolicy, floor10000, "applied policy is explicit");
assert.equal(Core.computeTotals(items, "EXCLUSIVE", { grandRounding: { mode: "ROUND", unit: 10000 } }), null,
  "invalid rounding mode fails closed");
assert.equal(Core.computeTotals(items, "EXCLUSIVE", { grandRounding: { mode: "FLOOR", unit: 3 } }), null,
  "unbounded rounding unit fails closed");

assert.equal(Core.formatKoreanMoneyWords(17960000), "일천칠백구십육만", "Excel NUMBERSTRING-style reviewed grand");
assert.equal(Core.formatKoreanMoneyWords(16330000), "일천육백삼십삼만", "formal Korean money words");
assert.equal(Core.formatKoreanMoneyWords(10000), "일만", "formal one-man retains 일");
assert.equal(Core.formatKoreanMoneyWords(110000000), "일억일천만", "large groups are deterministic");
assert.equal(Core.formatKoreanMoneyWords(0), "영", "zero is explicit");
assert.equal(Core.formatKoreanMoneyWords(-1), null, "negative written money rejected");

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

/* SUMMARY_DETAIL_ROLLUP — detail subtotal is the linked summary unitPrice authority */
const simpleDraftTotals = Core.computeDraftTotals(draft);
assert.deepEqual(
  [simpleDraftTotals.supply, simpleDraftTotals.vat, simpleDraftTotals.grand],
  [1300000, 130000, 1430000],
  "simple QuoteDraft totals remain unchanged"
);

const detail2026 = Core.normalizeDraft(Object.assign(JSON.parse(JSON.stringify(draft)), {
  items: [{ id: "summary-1", name: "ICT환경제어 시스템", qty: 1, unitPrice: 1 }],
  detailGroups: [{
    id: "detail-1",
    summaryItemId: "summary-1",
    title: "스마트팜 상세내역",
    items: [
      { id: "d1", name: "주장치", section: "1. 스마트팜", qty: 1, unitPrice: 15000000 },
      { id: "d2", name: "설치 및 잡자재", section: "3. 인건비 및 잡자재", qty: 1, unitPrice: 1330000 }
    ]
  }],
  calculationPolicy: floor10000
}));
assert.ok(detail2026, "2026-style detail draft normalizes");
assert.equal(detail2026.items[0].unitPrice, 1, "stored summary unit price is not silently rewritten");
const rollup2026 = Core.computeDraftTotals(detail2026);
assert.equal(rollup2026.detailGroups[0].subtotal, 16330000, "detail subtotal is derived from child lines");
assert.equal(rollup2026.effectiveItems[0].unitPrice, 16330000, "linked summary effective unit price comes from detail subtotal");
assert.equal(rollup2026.amounts[0], 16330000, "summary amount uses derived unit price");
assert.equal(rollup2026.rawGrand, 17963000, "detail rollup feeds existing VAT policy");
assert.equal(rollup2026.grand, 17960000, "detail rollup feeds existing reviewed rounding policy");

const detail2020 = Core.normalizeDraft(Object.assign(JSON.parse(JSON.stringify(draft)), {
  items: [
    { id: "summary-a", name: "2층 대예배실 음향", qty: 1, unitPrice: 0 },
    { id: "summary-b", name: "1층 중예배실 음향", qty: 1, unitPrice: 0 },
    { id: "summary-c", name: "부속실 음향", qty: 7, unitPrice: 0 }
  ],
  detailGroups: [
    { id: "detail-a", summaryItemId: "summary-a", items: [{ name: "A 상세", qty: 1, unitPrice: 300329000 }] },
    { id: "detail-b", summaryItemId: "summary-b", items: [{ name: "B 상세", qty: 1, unitPrice: 64657500 }] },
    { id: "detail-c", summaryItemId: "summary-c", items: [{ name: "C 상세", qty: 1, unitPrice: 4744000 }] }
  ]
}));
const rollup2020 = Core.computeDraftTotals(detail2020);
assert.deepEqual(
  rollup2020.effectiveItems.map((item) => item.unitPrice),
  [300329000, 64657500, 4744000],
  "multiple detail groups independently derive summary unit prices"
);
assert.deepEqual(
  rollup2020.amounts,
  [300329000, 64657500, 33208000],
  "summary quantity multiplies each linked detail subtotal"
);
assert.equal(rollup2020.supply, 398194500, "2020 reviewed summary subtotal is reproduced");

const badDetailMissingLink = JSON.parse(JSON.stringify(detail2026));
badDetailMissingLink.detailGroups[0].summaryItemId = "missing-summary";
assert.equal(Core.normalizeDraft(badDetailMissingLink), null, "broken detail summary link fails closed");
const badDetailDuplicateLink = JSON.parse(JSON.stringify(detail2026));
badDetailDuplicateLink.detailGroups.push({
  id: "detail-2",
  summaryItemId: "summary-1",
  items: [{ name: "중복", qty: 1, unitPrice: 1 }]
});
assert.equal(Core.normalizeDraft(badDetailDuplicateLink), null, "duplicate summary link fails closed");
const badNestedDetail = JSON.parse(JSON.stringify(detail2026));
badNestedDetail.detailGroups[0].items[0].detailGroups = [];
assert.equal(Core.normalizeDraft(badNestedDetail), null, "nested detail groups fail closed");
const badDetailAmount = JSON.parse(JSON.stringify(detail2026));
badDetailAmount.detailGroups[0].items[0].amount = 15000000;
assert.equal(Core.normalizeDraft(badDetailAmount), null, "trusted detail amount input fails closed");

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
assert.equal(draft.sender.company, "샘플 공급사", "neutral default sender");
assert.equal(draft.sender.presetId, "sample", "neutral sender preset");

/* NEW_QUOTE_DOMAIN_CONTRACT — 새 고객 견적은 sender만 유지하고 내용은 비움 */
const currentForNew = Core.createDefaultDraft();
currentForNew.sender = {
  company: "내 회사",
  rep: "홍대표",
  bizNo: "123-45-67890",
  address: "광주광역시",
  phone: "010-1234-5678",
  email: "owner@example.com",
  presetId: "custom"
};
currentForNew.meta.validDays = 14;
currentForNew.recipient.company = "이전 고객";
currentForNew.items = [{ id: "item-9", name: "기존 품목", qty: 3, unitPrice: 99000 }];
currentForNew.tax.mode = "INCLUSIVE";
currentForNew.memo = "이전 견적 메모";

const blankNext = Core.createBlankQuoteDraft(currentForNew, {
  quoteNo: "PQ-20260928-002",
  issueDate: "2026-09-28",
  source: "manual"
});
assert.ok(blankNext, "blank next quote is valid");
assert.deepEqual(blankNext.sender, currentForNew.sender, "sender is preserved");
assert.equal(blankNext.meta.quoteNo, "PQ-20260928-002", "fresh quote number injected");
assert.equal(blankNext.meta.issueDate, "2026-09-28", "fresh issue date injected");
assert.equal(blankNext.meta.validDays, 14, "validity preference preserved");
assert.deepEqual(blankNext.recipient, { company: "", person: "", address: "", email: "" }, "recipient cleared");
assert.deepEqual(blankNext.items, [{ id: "item-1", name: "", qty: 1, unitPrice: 0 }], "one blank item");
assert.equal(blankNext.tax.mode, "EXCLUSIVE", "new quote tax resets to explicit default");
assert.equal(blankNext.memo, Core.createDefaultDraft().memo, "ordinary default memo restored");
assert.equal(currentForNew.recipient.company, "이전 고객", "source draft not mutated");
assert.equal(currentForNew.items[0].name, "기존 품목", "source items not mutated");

const familyCurrent = Core.normalizeDraft(Object.assign(JSON.parse(JSON.stringify(currentForNew)), {
  calculationPolicy: floor10000
}));
const familyNext = Core.createBlankQuoteDraft(familyCurrent, {
  quoteNo: "PQ-20260928-003",
  issueDate: "2026-09-28",
  source: "manual"
});
assert.deepEqual(familyNext.calculationPolicy, floor10000,
  "new quote preserves the reviewed family calculation policy");
assert.notEqual(familyNext.calculationPolicy, familyCurrent.calculationPolicy,
  "new quote receives a normalized policy snapshot rather than shared mutable state");

/* PRINT_READINESS_CONTRACT — 최소 출력 필수값 */
const printable = Core.createDefaultDraft();
assert.deepEqual(Core.printReadiness(printable), { ready: true, missing: [] }, "default demo is printable");

const noQuoteNo = JSON.parse(JSON.stringify(printable));
noQuoteNo.meta.quoteNo = "";
assert.deepEqual(Core.printReadiness(noQuoteNo).missing, ["quote_no"], "quote number required");

const noDate = JSON.parse(JSON.stringify(printable));
noDate.meta.issueDate = "";
assert.deepEqual(Core.printReadiness(noDate).missing, ["issue_date"], "valid issue date required");

const noSender = JSON.parse(JSON.stringify(printable));
noSender.sender.company = "";
assert.deepEqual(Core.printReadiness(noSender).missing, ["sender_company"], "sender company required");

const noRecipient = JSON.parse(JSON.stringify(printable));
noRecipient.recipient.company = "";
noRecipient.recipient.person = "";
assert.deepEqual(Core.printReadiness(noRecipient).missing, ["recipient"], "recipient company or person required");

const noNamedItem = JSON.parse(JSON.stringify(printable));
noNamedItem.items = [{ id: "item-1", name: "", qty: 1, unitPrice: 0 }];
assert.deepEqual(Core.printReadiness(noNamedItem).missing, ["items"], "at least one named positive-qty item required");

const freeItem = JSON.parse(JSON.stringify(printable));
freeItem.items = [{ id: "item-1", name: "무상 지원", qty: 1, unitPrice: 0 }];
assert.equal(Core.printReadiness(freeItem).ready, true, "zero-price named item may still be printable");

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
const detailed = Core.normalizeDraft({
  schemaVersion: 1,
  meta: { quoteNo: "Q-DETAIL-1", issueDate: "2026-10-02", validDays: 30, source: "chat", projectName: "스마트팜 환경제어설비" },
  sender: draft.sender,
  recipient: draft.recipient,
  items: [{
    id: "detail-1",
    name: "ICT환경제어 시스템",
    spec: "주장치 및 스마트팜 전용S/W",
    unit: "식",
    qty: 1,
    unitPrice: 16330000,
    note: "설치 포함"
  }],
  tax: { mode: "EXCLUSIVE", rate: 0.1 },
  memo: ""
});
assert.equal(detailed.meta.projectName, "스마트팜 환경제어설비", "optional project name preserved");
assert.deepEqual(detailed.items[0], {
  id: "detail-1",
  name: "ICT환경제어 시스템",
  qty: 1,
  unitPrice: 16330000,
  spec: "주장치 및 스마트팜 전용S/W",
  unit: "식",
  note: "설치 포함"
}, "optional item presentation fields preserved");
assert.deepEqual(
  Core.computeTotals(detailed.items, "EXCLUSIVE"),
  Core.computeTotals([{ id: "detail-1", name: "ICT환경제어 시스템", qty: 1, unitPrice: 16330000 }], "EXCLUSIVE"),
  "spec/unit/note never change QuoteCore totals"
);
const policyDraft = Core.normalizeDraft(Object.assign(JSON.parse(JSON.stringify(draft)), {
  calculationPolicy: floor10000
}));
assert.deepEqual(policyDraft.calculationPolicy, floor10000, "QuoteDraft snapshots reviewed calculation policy");
assert.equal(
  Core.computeTotals(policyDraft.items, policyDraft.tax.mode, policyDraft.calculationPolicy).grand,
  Math.floor(Core.computeTotals(policyDraft.items, policyDraft.tax.mode).grand / 10000) * 10000,
  "restored draft reproduces the same reviewed rounding"
);
assert.equal(
  Core.normalizeDraft(Object.assign(JSON.parse(JSON.stringify(draft)), {
    calculationPolicy: { grandRounding: { mode: "FLOOR", unit: 7 } }
  })),
  null,
  "invalid stored calculation policy fails closed"
);

assert.equal(Core.normalizeDraft("garbage"), null, "string input rejected");
assert.equal(Core.normalizeDraft(null), null, "null rejected");
assert.equal(Core.normalizeDraft({ schemaVersion: 99 }), null, "wrong schema rejected");
const badShape = Core.normalizeDraft({ schemaVersion: 1, items: "not-an-array" });
assert.ok(Array.isArray(badShape.items) && badShape.items.length === 2, "non-array items fall back to defaults");
const badItems = Core.normalizeDraft({ schemaVersion: 1, items: [{ qty: -3, unitPrice: "x" }] });
assert.equal(badItems.items[0].qty, 1, "negative qty falls back");
assert.equal(badItems.items[0].unitPrice, 0, "garbage price falls back");

console.log("KOREAN_MONEY_INPUT_CONTRACT=PASS");
console.log("KOREAN_MONEY_SHORTHAND=PASS");
console.log("AMBIGUOUS_MIXED_UNIT_FAILS_SAFE=YES");
console.log("VAT_EXCLUSIVE_CONTRACT=PASS");
console.log("VAT_INCLUSIVE_CONTRACT=PASS");
console.log("VAT_EXEMPT_CONTRACT=PASS");
console.log("STANDARD_TOTALS_UNCHANGED=PASS");
console.log("FLOOR_10000_POLICY=PASS");
console.log("ROUNDING_ADJUSTMENT_EXPLICIT=PASS");
console.log("KOREAN_WRITTEN_GRAND_FROM_QUOTECORE=PASS");
console.log("VALID_UNTIL_CONTRACT=PASS");
console.log("QUOTEDRAFT_SCHEMA_CONTRACT=PASS");
console.log("NEW_QUOTE_DOMAIN_CONTRACT=PASS");
console.log("PRINT_READINESS_CONTRACT=PASS");
console.log("DRAFT_RESTORE_CONTRACT=PASS");
console.log("SIMPLE_QUOTE_TOTALS_UNCHANGED=PASS");
console.log("DETAIL_GROUP_SUBTOTAL=PASS");
console.log("SUMMARY_UNIT_PRICE_DERIVED_FROM_DETAIL=PASS");
console.log("SUMMARY_QTY_MULTIPLIES_DETAIL_SUBTOTAL=PASS");
console.log("MULTIPLE_DETAIL_GROUPS=PASS");
console.log("BROKEN_DETAIL_LINK_FAIL_CLOSED=YES");
console.log("NESTED_DETAIL_GROUPS=0");
console.log("B66_QUOTE_CORE_UNIT=PASS");