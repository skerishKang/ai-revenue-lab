const assert = require("node:assert");
const Extraction = require("../quote-extraction.js");

function ok(raw) {
  const result = Extraction.normalizeExtraction(raw);
  assert.equal(result.ok, true, JSON.stringify(result));
  return result.value;
}

function fail(raw, code) {
  const result = Extraction.normalizeExtraction(raw);
  assert.equal(result.ok, false, JSON.stringify(result));
  assert.equal(result.error, code);
}

const complete = ok({
  source: { kind: "image", filename: "견적서.png" },
  sender: {
    company: "테스트상사",
    rep: "김테스트",
    bizNo: "123-45-67890",
    address: "광주광역시 테스트로 100",
    phone: "010-1234-5678",
    email: "test@example.com"
  },
  recipient: {
    company: "홍길동건설",
    person: "홍길동",
    address: "서울특별시 테스트길 20",
    email: "hong@example.com"
  },
  quote: {
    quoteNo: "Q-20260927-1",
    issueDate: "2026-09-27",
    validDays: 30
  },
  items: [
    { name: "웹사이트 제작", qty: "1", unitPrice: "1,500,000" },
    { name: "유지보수", qty: 2, unitPrice: "300,000" }
  ],
  tax: { mode: "EXCLUSIVE" },
  memo: "납기 협의",
  evidence: [
    { field: "sender.company", page: 1, snippet: "테스트상사", confidence: 0.99 }
  ],
  warnings: ["low_contrast_logo"],
  totals: { supply: 1, vat: 2, grand: 3 }
});

assert.equal(complete.source.kind, "image");
assert.equal(complete.source.filename, "견적서.png");
assert.equal(complete.items[0].unitPrice, 1500000, "comma money normalized");
assert.equal(complete.items[1].qty, 2);
assert.deepEqual(complete.items.map((x) => x.name), ["웹사이트 제작", "유지보수"], "item order preserved");
assert.equal(complete.tax.mode, "EXCLUSIVE");
assert.equal(complete.evidence[0].page, 1);
assert.equal(complete.evidence[0].confidence, 0.99);
assert.ok(!("totals" in complete), "source totals are ignored and never trusted");

const partial = ok({
  source: { kind: "native_document" },
  sender: { company: "부분 공급사" },
  items: [{ name: "품목만 있음" }]
});
assert.equal(partial.sender.company, "부분 공급사");
assert.equal(partial.sender.rep, null);
assert.equal(partial.items[0].qty, null);
assert.equal(partial.items[0].unitPrice, null);
assert.equal(partial.quote.quoteNo, null);
assert.equal(partial.tax.mode, null);
assert.equal(partial.memo, null);

const missingItems = ok({
  source: { kind: "text" }
});
assert.deepEqual(missingItems.items, [], "missing items stay empty");

const unknownTax = ok({
  source: { kind: "image" },
  tax: { mode: "UNKNOWN" }
});
assert.equal(unknownTax.tax.mode, null, "unknown tax is not promoted to a confident mode");
assert.ok(unknownTax.warnings.includes("unknown_tax_mode"));

const zeroValues = ok({
  source: { kind: "image" },
  items: [{ name: "", qty: 0, unitPrice: "0" }]
});
assert.equal(zeroValues.items[0].name, null);
assert.equal(zeroValues.items[0].qty, 0);
assert.equal(zeroValues.items[0].unitPrice, 0);

fail(null, "invalid_extraction");
fail([], "invalid_extraction");
fail("{}", "invalid_extraction");
fail({}, "invalid_source");
fail({ source: { kind: "audio" } }, "unsupported_source_kind");
fail({ source: { kind: "image" }, sender: "not-object" }, "invalid_sender");
fail({ source: { kind: "image" }, quote: "not-object" }, "invalid_quote");
fail({ source: { kind: "image" }, items: "not-array" }, "invalid_items");
fail({ source: { kind: "image" }, items: [null] }, "invalid_item_0");
fail({ source: { kind: "image" }, items: [{ qty: -1 }] }, "invalid_item_qty");
fail({ source: { kind: "image" }, items: [{ unitPrice: "12a3" }] }, "invalid_item_unit_price");
fail({ source: { kind: "image" }, quote: { issueDate: "2026-13-40" } }, "invalid_issue_date");
fail({ source: { kind: "image" }, quote: { validDays: 0 } }, "invalid_valid_days");
fail({
  source: { kind: "image" },
  evidence: [{ field: "items.0.name", confidence: 1.2 }]
}, "invalid_evidence_confidence");

const tooMany = Array.from({ length: Extraction.MAX_ITEMS + 1 }, (_, i) => ({ name: "품목" + i }));
fail({ source: { kind: "image" }, items: tooMany }, "too_many_items");

fail({
  source: { kind: "image" },
  sender: { company: "가".repeat(Extraction.MAX_TEXT + 1) }
}, "invalid_sender_company");

const scanned = ok({
  source: { kind: "scanned_pdf", filename: "scan.pdf" },
  items: [
    { name: "첫째", qty: 1, unitPrice: 1000 },
    { name: "둘째", qty: 1, unitPrice: 2000 },
    { name: "셋째", qty: 1, unitPrice: 3000 }
  ],
  evidence: [
    { field: "items.0.name", page: 2, snippet: "첫째" },
    { field: "items.1.name", page: 2, snippet: "둘째" },
    { field: "items.2.name", page: 3, snippet: "셋째" }
  ]
});
assert.deepEqual(scanned.items.map((x) => x.name), ["첫째", "둘째", "셋째"]);
assert.deepEqual(scanned.evidence.map((x) => x.page), [2, 2, 3]);

console.log("B66_EXTRACTION_CONTRACT=PASS");
console.log("MALFORMED_OUTPUT_FAILS_SAFE=YES");
console.log("MISSING_FIELDS_NOT_FABRICATED=YES");
console.log("ITEM_ORDER_PRESERVED=YES");
console.log("SOURCE_TOTALS_NOT_TRUSTED=YES");
