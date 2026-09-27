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

const copied = History.copyAsNew(loaded);
assert.ok(copied);
assert.equal(copied.meta.source, "history-copy");
assert.notEqual(copied.meta.quoteNo, "Q-OLD-001", "copy receives a fresh quote number");
assert.equal(copied.recipient.company, "홍길동건설");
assert.deepEqual(copied.items.map((x) => x.name), ["홈페이지 제작", "유지보수"]);
assert.equal(Core.computeTotals(copied.items, copied.tax.mode).grand, 2310000);

const originalBefore = JSON.stringify(loaded.draft);
copied.items[0].name = "변경됨";
assert.equal(JSON.stringify(loaded.draft), originalBefore, "copy-as-new never mutates the history snapshot");

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
console.log("MALFORMED_HISTORY_FAILS_SAFE=YES");
