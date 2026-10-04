const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const Core = require("../quote-core.js");
const History = require("../quote-history.js");

const production = Core.createProductionDraft();

assert.equal(production.sender.company, "", "Production sender starts blank");
assert.equal(production.sender.presetId, "custom", "Production sender is not the demo preset");
assert.deepEqual(
  production.recipient,
  { company: "", person: "", address: "", email: "" },
  "Production recipient starts blank"
);
assert.deepEqual(
  production.items,
  [{ id: "item-1", name: "", qty: 1, unitPrice: 0 }],
  "Production draft starts with one blank line item"
);
assert.equal(production.memo, "", "Production memo starts blank");
assert.deepEqual(
  Core.printReadiness(production),
  { ready: false, missing: ["sender_company", "recipient", "items"] },
  "Production startup draft is never print-ready"
);
assert.equal(
  History.isMeaningfulDraft(production),
  false,
  "truthful Production startup draft is not shown as resumable work"
);

const legacyDemo = Core.createDefaultDraft();
assert.equal(
  History.isMeaningfulDraft(legacyDemo),
  false,
  "untouched legacy demo state remains non-resumable"
);
assert.equal(
  Core.printReadiness(legacyDemo).ready,
  true,
  "explicit demo fixture remains available for tests/demos only"
);

const appSource = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");
assert.ok(
  appSource.includes("let draft = loadDraft() || Core.createProductionDraft();"),
  "app startup uses Production draft authority"
);
assert.ok(
  appSource.includes('const fresh = Core.createProductionDraft();'),
  "new Production quote allocation starts from blank business facts"
);
assert.ok(
  appSource.includes("isUntouchedLegacyDemoDraft"),
  "app migrates untouched legacy demo startup state"
);
assert.ok(
  !appSource.includes("let draft = loadDraft() || Core.createDefaultDraft();"),
  "app never falls back to printable demo data"
);

const repoRoot = path.join(__dirname, "..", "..", "..");
const workflow = fs.readFileSync(
  path.join(repoRoot, ".github", "workflows", "b66-neutral-pages-beta.yml"),
  "utf8"
);
assert.ok(
  !workflow.includes("grep -F '샘플 공급사'"),
  "deploy smoke no longer depends on demo business text"
);
assert.ok(
  workflow.includes("grep -F 'id=\"easyView\"'"),
  "deploy smoke uses a stable product structure marker"
);

/* #3479 — demo business fact가 Production truth로 스며드는 경로 전면 차단 증명.
   createDefaultDraft()는 explicit demo fixture이고, Production normalization/
   새 견적/copy-as-new/reset 은 truthful blank authority만 사용한다. */
const DEMO_BUSINESS_FACTS = [
  "샘플 공급사",
  "대표자명",
  "000-00-00000",
  "고객사",
  "담당자님",
  "서비스 구축",
  "운영 지원",
  "hello@example.com",
  "견적 유효기간 내 발주 시"
];
const containsDemoFact = (value) =>
  DEMO_BUSINESS_FACTS.some((fact) => String(value).includes(fact));

/* NORMALIZATION_FABRICATES_DEMO_BUSINESS_FACTS=0 — missing/malformed 필드가
   데모 값으로 보충되지 않는다. */
const malformedCases = [
  { schemaVersion: 1 },
  { schemaVersion: 1, meta: {}, sender: {}, recipient: {}, items: [], memo: null },
  { schemaVersion: 1, meta: { quoteNo: "" }, sender: { company: "" }, items: [{ id: "item-1" }] },
  JSON.parse(JSON.stringify(production))
];
malformedCases.forEach((raw, index) => {
  const normalized = Core.normalizeDraft(raw);
  assert.ok(normalized, "malformed case " + index + " still normalizes");
  assert.equal(
    containsDemoFact(JSON.stringify(normalized)),
    false,
    "normalizeDraft never fabricates demo business facts (case " + index + ")"
  );
  assert.equal(normalized.sender.company, "", "missing sender stays blank (case " + index + ")");
  assert.equal(normalized.recipient.company, "", "missing recipient stays blank (case " + index + ")");
  assert.equal(normalized.memo, "", "missing memo stays blank (case " + index + ")");
  assert.equal(normalized.items[0].name, "", "missing item names stay blank (case " + index + ")");
});
const partialUser = Core.normalizeDraft({
  schemaVersion: 1,
  meta: { quoteNo: "PQ-20260101-009" },
  sender: { company: "우리상사" },
  items: [{ id: "item-1", name: "실제 품목", qty: 2, unitPrice: 5000 }]
});
assert.equal(partialUser.sender.company, "우리상사", "user-provided sender survives normalization");
assert.equal(containsDemoFact(JSON.stringify(partialUser)), false,
  "partial user draft gains no demo facts from normalization");

/* PRODUCTION_DEFAULT_MEMO_BLANK_OR_APPROVED_ONLY=YES,
   NEW_PRODUCTION_QUOTE_DEMO_MEMO=0, NEW_PRODUCTION_QUOTE_DEMO_ITEMS=0 */
const currentUserDraft = Core.normalizeDraft({
  schemaVersion: 1,
  meta: { quoteNo: "PQ-20260101-001", validDays: 14 },
  sender: { company: "사용자상사", rep: "홍대표" },
  recipient: { company: "실제고객" },
  items: [{ id: "item-1", name: "실제 품목", qty: 1, unitPrice: 10000 }],
  memo: "사용자 메모"
});
const blankNext = Core.createBlankQuoteDraft(currentUserDraft, {
  quoteNo: "PQ-20260101-010",
  issueDate: "2026-01-01"
});
assert.ok(blankNext, "blank next quote is valid");
assert.equal(blankNext.memo, "", "new Production quote memo is truthful blank");
assert.equal(
  containsDemoFact(JSON.stringify(blankNext)),
  false,
  "createBlankQuoteDraft never inherits demo memo/business wording"
);
assert.deepEqual(
  blankNext.items,
  [{ id: "item-1", name: "", qty: 1, unitPrice: 0 }],
  "new Production quote items are blank"
);
assert.equal(blankNext.sender.company, "사용자상사",
  "new quote sender comes from the current authority only");
const blankNextFromDemoCurrent = Core.createBlankQuoteDraft(legacyDemo, {
  quoteNo: "PQ-20260101-012"
});
assert.equal(blankNextFromDemoCurrent.memo, "",
  "even a legacy demo current can no longer hand its demo memo to a new quote");
const blankFromInvalid = Core.createBlankQuoteDraft(null);
assert.equal(blankFromInvalid.sender.company, "", "invalid current falls back to Production blank, not demo");

/* copy-as-new는 사용자 source facts만 복사한다. */
const userEntry = {
  draft: Core.normalizeDraft({
    schemaVersion: 1,
    meta: { quoteNo: "PQ-20260101-001" },
    sender: { company: "사용자상사", rep: "홍대표" },
    recipient: { company: "실제고객" },
    items: [{ id: "item-1", name: "실제 품목", qty: 1, unitPrice: 10000 }],
    memo: "사용자 메모"
  })
};
const copied = History.copyAsNew(userEntry, { quoteNo: "PQ-20260101-011", now: new Date("2026-01-02T09:00:00Z") });
assert.ok(copied, "copyAsNew works");
assert.equal(copied.sender.company, "사용자상사", "copy-as-new keeps user sender facts");
assert.equal(copied.items[0].name, "실제 품목", "copy-as-new keeps user items");
assert.equal(copied.memo, "사용자 메모", "copy-as-new keeps user memo");
assert.equal(copied.meta.source, "history-copy", "copy-as-new marks its source");
assert.equal(
  containsDemoFact(JSON.stringify(copied)),
  false,
  "copy-as-new never inserts demo business data into a new quote"
);

/* app.js reset 경로도 데모로 돌아가지 않는다. */
assert.ok(
  appSource.includes("draft = Core.createProductionDraft();"),
  "local data reset restarts from the Production blank authority"
);
assert.ok(
  !appSource.includes("draft = Core.createDefaultDraft();"),
  "local data reset never reinstates the demo fixture as a live draft"
);

console.log("B66_PRODUCTION_DRAFT_SAFETY=PASS");
console.log("PRODUCTION_DEFAULT_DRAFT_PRINT_READY=NO");
console.log("DEMO_BUSINESS_FACTS_CAN_BECOME_FINAL_QUOTE=0");
console.log("NORMALIZATION_FABRICATES_DEMO_BUSINESS_FACTS=0");
console.log("NEW_PRODUCTION_QUOTE_DEMO_MEMO=0");
console.log("NEW_PRODUCTION_QUOTE_DEMO_ITEMS=0");
console.log("PRODUCTION_DEFAULT_SENDER_BLANK=YES");
console.log("PRODUCTION_DEFAULT_RECIPIENT_BLANK=YES");
console.log("PRODUCTION_DEFAULT_ITEMS_BLANK=YES");
console.log("PRODUCTION_DEFAULT_MEMO_BLANK_OR_APPROVED_ONLY=YES");
console.log("LEGACY_DEMO_FIXTURE_STILL_EXPLICITLY_AVAILABLE=YES");
console.log("PRODUCTION_DEPLOY_GUARD_REQUIRES_DEMO_BUSINESS_DATA=NO");
