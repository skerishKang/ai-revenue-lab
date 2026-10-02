const assert = require("node:assert");
const Core = require("../quote-core.js");
const History = require("../quote-history.js");

function sampleDraft() {
  const draft = Core.createDefaultDraft();
  draft.meta.quoteNo = "Q-OLD-001";
  draft.meta.issueDate = "2026-09-20";
  draft.recipient.company = "홍길동건설";
  draft.recipient.person = "홍길동";
  draft.items = [
    { id: "item-1", name: "홈페이지 제작", qty: 1, unitPrice: 1500000 },
    { id: "item-2", name: "유지보수", qty: 2, unitPrice: 300000 }
  ];
  draft.tax.mode = Core.TAX_MODES.EXCLUSIVE;
  draft.memo = "납기 협의";
  return draft;
}

const empty = History.normalizeEnvelope(null);
assert.deepEqual(empty, { schemaVersion: 1, entries: [] });

const malformed = History.normalizeEnvelope({ schemaVersion: 999, entries: [{ bad: true }] });
assert.deepEqual(malformed.entries, []);

const draft = sampleDraft();
let envelope = History.addEntry(null, draft, {
  id: "history-1",
  savedAt: "2026-09-27T10:00:00.000Z"
});
assert.equal(envelope.entries.length, 1);
assert.equal(envelope.entries[0].id, "history-1");
assert.equal(envelope.entries[0].draft.recipient.company, "홍길동건설");

const meta = History.listMetadata(envelope)[0];
assert.equal(meta.recipientCompany, "홍길동건설");
assert.equal(meta.recipientPerson, "홍길동");
assert.equal(meta.quoteNo, "Q-OLD-001");
assert.equal(meta.itemCount, 2);
assert.equal(meta.grand, 2310000, "history total is derived by QuoteCore");

assert.ok(!("grand" in envelope.entries[0]), "history snapshot does not persist a trusted grand total");
assert.ok(!("totals" in envelope.entries[0]), "history snapshot does not persist source totals");

const loaded = History.getEntry(envelope, "history-1");
assert.ok(loaded);
assert.equal(loaded.draft.items[0].name, "홈페이지 제작");

const sequenceDate = new Date(2026, 8, 28, 2, 30, 45, 123);

assert.deepEqual(
  History.normalizeSequenceState(null),
  { schemaVersion: 1, date: "", lastSequence: 0 },
  "missing sequence state fails safe"
);
assert.deepEqual(
  History.normalizeSequenceState({ schemaVersion: 999, date: "bad", lastSequence: -5 }),
  { schemaVersion: 1, date: "", lastSequence: 0 },
  "malformed sequence fields are sanitized"
);

const sameDay1 = Core.createDefaultDraft();
sameDay1.meta.quoteNo = "PQ-20260928-001";
sameDay1.meta.issueDate = "2026-09-28";
const sameDay2 = Core.createDefaultDraft();
sameDay2.meta.quoteNo = "PQ-20260928-002";
sameDay2.meta.issueDate = "2026-09-28";

const allocated3 = History.allocateQuoteNo(null, [sameDay1, sameDay2], sequenceDate);
assert.equal(allocated3.quoteNo, "PQ-20260928-003", "allocator continues the readable daily sequence");
assert.deepEqual(allocated3.state, {
  schemaVersion: 1,
  date: "2026-09-28",
  lastSequence: 3
});

const allocated4 = History.allocateQuoteNo(allocated3.state, [sameDay1, sameDay2], sequenceDate);
assert.equal(allocated4.quoteNo, "PQ-20260928-004", "same-day repeated allocation cannot collide");

const oldTimestamp = Core.createDefaultDraft();
oldTimestamp.meta.quoteNo = "PQ-20260928-033527353";
const migrationSafe = History.allocateQuoteNo(null, [oldTimestamp], sequenceDate);
assert.equal(migrationSafe.quoteNo, "PQ-20260928-001", "legacy long timestamp IDs do not create huge sequence jumps");

const nextDay = History.allocateQuoteNo(allocated4.state, [], new Date(2026, 8, 29, 9, 0, 0, 0));
assert.equal(nextDay.quoteNo, "PQ-20260929-001", "daily sequence resets on a new local date");

const copied = History.copyAsNew(loaded, {
  now: sequenceDate,
  quoteNo: allocated3.quoteNo
});
assert.ok(copied);
assert.equal(copied.meta.source, "history-copy");
assert.equal(copied.meta.issueDate, "2026-09-28", "copy receives the current local date");
assert.equal(copied.meta.quoteNo, "PQ-20260928-003", "copy receives the allocated human-readable quote number");
assert.notEqual(copied.meta.quoteNo, loaded.draft.meta.quoteNo, "copy quote number differs from source");
assert.equal(copied.recipient.company, "홍길동건설");
assert.deepEqual(copied.items.map((x) => x.name), ["홈페이지 제작", "유지보수"]);
assert.equal(Core.computeTotals(copied.items, copied.tax.mode).grand, 2310000);

const detailedPolicyDraft = sampleDraft();
detailedPolicyDraft.meta.projectName = "스마트팜 환경제어설비";
detailedPolicyDraft.items = [{
  id: "item-detail",
  name: "ICT환경제어 시스템",
  spec: "주장치 및 스마트팜 전용S/W",
  unit: "식",
  qty: 1,
  unitPrice: 16330000,
  note: "설치 포함"
}];
detailedPolicyDraft.calculationPolicy = { grandRounding: { mode: "FLOOR", unit: 10000 } };
const detailedEntry = History.createEntry(detailedPolicyDraft, {
  id: "history-detail",
  savedAt: "2026-09-27T12:30:00.000Z"
});
const detailedCopy = History.copyAsNew(detailedEntry, {
  now: sequenceDate,
  quoteNo: "PQ-20260928-009"
});
assert.equal(detailedCopy.meta.projectName, "스마트팜 환경제어설비",
  "copy-as-new preserves project name");
assert.equal(detailedCopy.items[0].spec, "주장치 및 스마트팜 전용S/W",
  "copy-as-new preserves item spec");
assert.equal(detailedCopy.items[0].unit, "식", "copy-as-new preserves item unit");
assert.equal(detailedCopy.items[0].note, "설치 포함", "copy-as-new preserves item note");
assert.deepEqual(
  detailedCopy.calculationPolicy,
  { grandRounding: { mode: "FLOOR", unit: 10000 } },
  "copy-as-new preserves reviewed calculation policy"
);
assert.equal(
  Core.computeTotals(
    detailedCopy.items,
    detailedCopy.tax.mode,
    detailedCopy.calculationPolicy
  ).grand,
  17960000,
  "copied history uses the same reviewed QuoteCore policy"
);

const groupedDraft = sampleDraft();
groupedDraft.items = [{ id: "summary-old", name: "부속실 음향", qty: 7, unitPrice: 1 }];
groupedDraft.detailGroups = [{
  id: "detail-c",
  summaryItemId: "summary-old",
  title: "부속실 상세",
  items: [
    { id: "child-1", name: "장비", section: "1) 장비", qty: 1, unitPrice: 3644000 },
    { id: "child-2", name: "인건비", section: "5) 인건비", qty: 1, unitPrice: 1100000 }
  ]
}];
const groupedEntry = History.createEntry(groupedDraft, {
  id: "history-grouped",
  savedAt: "2026-09-27T12:40:00.000Z"
});
const groupedCopy = History.copyAsNew(groupedEntry, {
  now: sequenceDate,
  quoteNo: "PQ-20260928-010"
});
assert.equal(groupedCopy.items[0].id, "item-1", "copy-as-new rekeys summary item");
assert.equal(groupedCopy.detailGroups[0].summaryItemId, "item-1",
  "copy-as-new remaps detail-group link to new summary id");
assert.equal(groupedCopy.detailGroups[0].items[0].section, "1) 장비",
  "copy-as-new preserves detail section headings");
assert.equal(Core.computeDraftTotals(groupedCopy).effectiveItems[0].unitPrice, 4744000,
  "copy-as-new preserves detail subtotal authority");
assert.equal(Core.computeDraftTotals(groupedCopy).amounts[0], 33208000,
  "copy-as-new preserves summary quantity multiplication");

const originalBefore = JSON.stringify(loaded.draft);
copied.items[0].name = "변경됨";
assert.equal(JSON.stringify(loaded.draft), originalBefore, "copy-as-new never mutates the history snapshot");

const updatedDraft = sampleDraft();
updatedDraft.recipient.company = "홍길동건설 수정본";
updatedDraft.items[0].unitPrice = 1800000;
const upserted = History.upsertEntryByQuoteNo(envelope, updatedDraft, {
  savedAt: "2026-09-27T11:00:00.000Z"
});
assert.equal(upserted.entries.length, 1, "same quote number updates instead of duplicating");
assert.equal(upserted.entries[0].id, "history-1", "upsert preserves stable history id");
assert.equal(upserted.entries[0].savedAt, "2026-09-27T11:00:00.000Z", "upsert refreshes savedAt");
assert.equal(upserted.entries[0].draft.recipient.company, "홍길동건설 수정본", "upsert stores latest content");
assert.equal(upserted.entries[0].draft.items[0].unitPrice, 1800000, "upsert stores latest item values");

const differentDraft = sampleDraft();
differentDraft.meta.quoteNo = "Q-NEW-002";
const withSecondQuote = History.upsertEntryByQuoteNo(upserted, differentDraft, {
  id: "history-2",
  savedAt: "2026-09-27T12:00:00.000Z"
});
assert.equal(withSecondQuote.entries.length, 2, "different quote number creates new history entry");
assert.equal(withSecondQuote.entries[0].id, "history-2", "new quote snapshot is first");
assert.equal(withSecondQuote.entries[1].id, "history-1", "updated prior quote remains once");

const duplicateLegacyEnvelope = {
  schemaVersion: 1,
  entries: [
    History.createEntry(updatedDraft, { id: "dup-new", savedAt: "2026-09-27T11:10:00Z" }),
    History.createEntry(updatedDraft, { id: "dup-old", savedAt: "2026-09-27T10:10:00Z" })
  ]
};
const collapsedLegacy = History.upsertEntryByQuoteNo(duplicateLegacyEnvelope, updatedDraft, {
  savedAt: "2026-09-27T13:00:00Z"
});
assert.equal(collapsedLegacy.entries.length, 1, "saving collapses pre-existing duplicate quote-number snapshots");
assert.equal(collapsedLegacy.entries[0].id, "dup-new", "newest matching stable id is retained");

const deleted = History.deleteEntry(envelope, "history-1");
assert.equal(deleted.entries.length, 0);

let bounded = { schemaVersion: 1, entries: [] };
for (let i = 0; i < History.MAX_HISTORY + 5; i += 1) {
  const d = sampleDraft();
  d.meta.quoteNo = "Q-" + i;
  bounded = History.addEntry(bounded, d, {
    id: "id-" + i,
    savedAt: "2026-09-27T10:" + String(i).padStart(2, "0") + ":00.000Z"
  });
}
assert.equal(bounded.entries.length, History.MAX_HISTORY, "history is bounded");
assert.equal(bounded.entries[0].id, "id-24", "newest snapshot is first");
assert.equal(bounded.entries[History.MAX_HISTORY - 1].id, "id-5", "oldest overflow is dropped");

const base = Core.createDefaultDraft();
assert.equal(History.isMeaningfulDraft(base), false, "untouched default draft is not resumable");
const changed = Core.createDefaultDraft();
changed.recipient.company = "실제 고객";
assert.equal(History.isMeaningfulDraft(changed), true, "edited draft is resumable");
const extracted = Core.createDefaultDraft();
extracted.meta.source = "extraction:image";
assert.equal(History.isMeaningfulDraft(extracted), true, "non-manual source is resumable");

const badEnvelope = {
  schemaVersion: 1,
  entries: [
    { id: "", savedAt: "x", draft },
    { id: "bad-draft", savedAt: "x", draft: { schemaVersion: 999 } },
    { id: "good", savedAt: "2026-09-27T10:00:00Z", draft }
  ]
};
assert.deepEqual(History.normalizeEnvelope(badEnvelope).entries.map((x) => x.id), ["good"]);

console.log("B66_HISTORY_CONTRACT=PASS");
console.log("RECENT_HISTORY_BOUNDED=YES");
console.log("HISTORY_TOTALS_DERIVED=YES");
console.log("HISTORY_COPY_AS_NEW=PASS");
console.log("HISTORY_DETAIL_FIELDS_PRESERVED=YES");
console.log("HISTORY_CALCULATION_POLICY_PRESERVED=YES");
console.log("HISTORY_DETAIL_GROUP_LINK_PRESERVED=YES");
console.log("HISTORY_SAVE_UPSERT=PASS");
console.log("SAME_QUOTE_REPEATED_SAVE_DUPLICATES=0");
console.log("HUMAN_READABLE_QUOTE_NO=YES");
console.log("SAME_DAY_COLLISION_TEST=PASS");
console.log("COPY_QUOTE_NO_DIFFERS_FROM_SOURCE=YES");
console.log("MALFORMED_HISTORY_FAILS_SAFE=YES");