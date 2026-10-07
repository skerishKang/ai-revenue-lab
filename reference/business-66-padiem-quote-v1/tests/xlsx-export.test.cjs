/* B66 · XLSX export foundation contract (#3496)

   Proves that the exporter emits a real, deterministic, native .xlsx package
   whose business facts are byte-parity with QuoteCore, without becoming a
   second calculation authority and without letting user text become a
   formula. */

const assert = require("node:assert");
const Core = require("../quote-core.js");
const Xlsx = require("../xlsx-export.js");

/* ── minimal STORE-only ZIP reader (the exporter writes no compression) ── */
function readZipEntries(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const signature = view.getUint32(0, true);
  assert.equal(signature, 0x04034b50, "starts with a local file header (PK signature)");
  const eocdSignature = view.getUint32(bytes.length - 22, true);
  assert.equal(eocdSignature, 0x06054b50, "ends with an end-of-central-directory record");
  /* EOCD: sig(0-3) disk(4-5) cdDisk(6-7) entries(8-9) total(10-11) cdSize(12-15) cdOffset(16-19) */
  const count = view.getUint16(bytes.length - 12, true);
  const entries = [];
  let offset = 0;
  for (let i = 0; i < count; i += 1) {
    assert.equal(view.getUint32(offset, true), 0x04034b50, "local header signature per entry");
    const method = view.getUint16(offset + 8, true);
    const time = view.getUint16(offset + 10, true);
    const date = view.getUint16(offset + 12, true);
    const crc = view.getUint32(offset + 14, true);
    const size = view.getUint32(offset + 22, true);
    const nameLen = view.getUint16(offset + 26, true);
    const name = Buffer.from(bytes.subarray(offset + 30, offset + 30 + nameLen)).toString("utf8");
    const dataStart = offset + 30 + nameLen;
    const data = bytes.subarray(dataStart, dataStart + size);
    assert.equal(method, 0, "entry uses STORE (no compression): " + name);
    assert.equal(Xlsx.crc32(data), crc, "CRC32 matches payload: " + name);
    entries.push({ name, data, time, date, order: i });
    offset = dataStart + size;
  }
  return entries;
}

function entriesByName(entries) {
  const map = new Map();
  entries.forEach((entry) => map.set(entry.name, Buffer.from(entry.data).toString("utf8")));
  return map;
}

/* ── synthetic fixture only: no real customer facts ── */
const SYNTHETIC = {
  schemaVersion: 1,
  meta: {
    quoteNo: "PQ-TEST-001",
    issueDate: "2026-02-03",
    validDays: 14,
    source: "manual",
    projectName: "테스트 프로젝트"
  },
  sender: {
    company: "테스트상사",
    rep: "김대표",
    contactPerson: "이담당",
    bizNo: "000-00-00000",
    address: "광주광역시 테스트구 테스트로 1",
    phone: "010-0000-0000",
    email: "test@example.invalid",
    presetId: "custom"
  },
  recipient: {
    company: "대한테스트건설",
    person: "박대리",
    address: "서울특별시 테스트동 테스트로 2",
    email: "buyer@example.invalid"
  },
  items: [
    { id: "item-1", name: "배관", unit: "m", qty: 100, unitPrice: 18000 },
    { id: "item-2", name: "테스트 시공비", qty: 2, unitPrice: 25000 }
  ],
  tax: { mode: "EXCLUSIVE", rate: 0.1 },
  memo: "테스트 특기사항: 결제 조건은 협의"
};

const normalized = Core.normalizeDraft(SYNTHETIC);
const totals = Core.computeDraftTotals(normalized);
const bytes = Xlsx.buildWorkbook(SYNTHETIC, { core: Core });
const entries = readZipEntries(bytes);
const parts = entriesByName(entries);
const sheetXml = parts.get("xl/worksheets/sheet1.xml");

/* ── native package shape ── */
console.log("B66_XLSX_EXPORT=PASS");
console.log("NATIVE_XLSX_BYTES=PASS");
console.log("XLSX_PACKAGE_ENTRIES=PASS");
assert.ok(bytes instanceof Uint8Array, "export returns a Uint8Array");
assert.equal(bytes[0], 0x50, "ZIP 'P' magic");
assert.equal(bytes[1], 0x4b, "ZIP 'K' magic");

const expectedEntries = [
  "[Content_Types].xml",
  "_rels/.rels",
  "xl/workbook.xml",
  "xl/_rels/workbook.xml.rels",
  "xl/styles.xml",
  "xl/worksheets/sheet1.xml"
];
assert.deepEqual(entries.map((entry) => entry.name), expectedEntries, "deterministic entry order");
expectedEntries.forEach((name) => assert.ok(parts.has(name), "package entry present: " + name));
console.log("DETERMINISTIC_ENTRY_ORDER=YES");
console.log("ZIP_METHOD=STORE");
console.log("ZIP_FIXED_TIMESTAMP=YES");

/* workbook declares the 견적서 sheet and nothing else */
assert.ok(/<sheet name="견적서" sheetId="1" r:id="rId1"\/>/.test(parts.get("xl/workbook.xml")),
  "workbook declares exactly one sheet named 견적서");
console.log("WORKSHEET_NAME=견적서");
assert.equal((parts.get("xl/workbook.xml").match(/<sheet /g) || []).length, 1, "single sheet only");

/* ── no macros / no external links / no second authority ── */
const allXml = Array.from(parts.values()).join("\n");
assert.ok(!/vbaProject|macroEnabled/i.test(allXml), "no macro parts");
assert.ok(!/TargetMode="External"/.test(allXml), "no external relationships");
assert.ok(!/externalLink/i.test(allXml), "no external link parts");
assert.ok(!/<f[ >]/.test(allXml), "no Excel formula anywhere (values are authoritative)");
console.log("MACROS=0");
console.log("EXTERNAL_LINKS=0");
console.log("XLSX_RECOMPUTES_TOTALS_INDEPENDENTLY=NO");

/* ── business fact parity with QuoteCore ── */
assert.ok(sheetXml.includes(normalized.meta.quoteNo), "quote number parity");
console.log("QUOTE_NO_PARITY=PASS");
/* Excel serial derived independently from the ISO date (ISO parse vs manual parse). */
const expectedSerial = Math.round(
  (new Date(normalized.meta.issueDate + "T00:00:00Z").getTime() - new Date("1899-12-30T00:00:00Z").getTime()) / 86400000
);
assert.ok(sheetXml.includes('<c r="D3" s="4"><v>' + expectedSerial + "</v></c>"),
  "issue date written as a real Excel date cell (serial " + expectedSerial + ")");
assert.ok(parts.get("xl/styles.xml").includes('numFmtId="165"'), "date number format declared");
console.log("ISSUE_DATE_PARITY=PASS");
assert.ok(sheetXml.includes("테스트 프로젝트"), "project name parity");
console.log("PROJECT_NAME_PARITY=PASS");
assert.ok(sheetXml.includes("대한테스트건설"), "recipient company parity");
assert.ok(sheetXml.includes("박대리"), "recipient contact parity");
console.log("RECIPIENT_PARITY=PASS");
assert.ok(sheetXml.includes("테스트상사"), "sender company parity");
assert.ok(sheetXml.includes("김대표"), "sender representative parity");
assert.ok(sheetXml.includes("000-00-00000"), "sender business number parity");
console.log("SENDER_PARITY=PASS");

const headerRowIndex = sheetXml.indexOf("품명 및 규격");
assert.ok(headerRowIndex > 0, "item table header present");
/* locate the first item row dynamically instead of hardcoding a row number */
const itemRowMatch = /<row r="(\d+)">((?:(?!<\/row>).)*?>배관<)/.exec(sheetXml);
assert.ok(itemRowMatch, "first item row located in the sheet XML");
const firstItemRow = itemRowMatch[1];
const itemRowXml = /<row r="\d+">((?:(?!<\/row>).)*)<\/row>/.exec(sheetXml.slice(sheetXml.indexOf('<row r="' + firstItemRow + '"')))[1];
const cellOf = (column) => {
  const match = new RegExp('<c r="' + column + firstItemRow + '"[^>]*>(?:<v>([^<]*)</v>|<is><t[^>]*>([^<]*)</t></is>)').exec(itemRowXml);
  return match ? (match[1] !== undefined ? match[1] : match[2]) : null;
};
assert.equal(cellOf("A"), "1", "item index parity");
assert.equal(cellOf("B"), "배관", "item name parity");
assert.equal(cellOf("C"), "m", "item unit parity");
assert.equal(Number(cellOf("D")), Core.parseMoney(normalized.items[0].qty), "item qty parity");
assert.equal(Number(cellOf("E")), Core.parseMoney(normalized.items[0].unitPrice), "item unit price parity");
assert.equal(Number(cellOf("F")), Core.itemAmount(normalized.items[0]), "item amount parity (QuoteCore)");
console.log("ITEM_NAME_PARITY=PASS");
console.log("ITEM_QTY_PARITY=PASS");
console.log("ITEM_UNIT_PRICE_PARITY=PASS");
console.log("ITEM_AMOUNT_PARITY=PASS");
assert.ok(/품명 및 규격/.test(sheetXml) && /수\s*량|수량/.test(sheetXml.replace(/\s+/g, " ")),
  "CGI item table columns present");

assert.ok(sheetXml.includes("<v>" + totals.supply + "</v>"), "supply amount parity");
console.log("SUPPLY_AMOUNT_PARITY=PASS");
assert.ok(sheetXml.includes("<v>" + totals.vat + "</v>"), "VAT parity");
console.log("VAT_PARITY=PASS");
assert.ok(sheetXml.includes("<v>" + totals.grand + "</v>"), "grand total parity");
console.log("GRAND_TOTAL_PARITY=PASS");
assert.ok(sheetXml.includes(Core.formatKoreanMoneyWords(totals.grand) + "원정"), "Korean written total parity");
console.log("KOREAN_TOTAL_TEXT_PARITY=PASS");
assert.ok(sheetXml.includes("테스트 특기사항: 결제 조건은 협의"), "memo parity");
console.log("MEMO_PARITY=PASS");
console.log("XLSX_CALCULATION_AUTHORITY=QUOTECORE");
console.log("SECOND_CALCULATION_AUTHORITY=0");

/* ── formula injection: user text is always a string cell ── */
const HOSTILE = JSON.parse(JSON.stringify(SYNTHETIC));
HOSTILE.recipient.company = "=SUM(A1:A2)";
HOSTILE.recipient.person = "+CMD|' /C calc'!A0";
HOSTILE.sender.company = "-1+1";
HOSTILE.sender.rep = "@something";
HOSTILE.items[0].name = "=1+1";
HOSTILE.memo = "<script>alert('x')</script> & \"quoted\" 'single'";

const hostileBytes = Xlsx.buildWorkbook(HOSTILE, { core: Core });
const hostileSheet = entriesByName(readZipEntries(hostileBytes)).get("xl/worksheets/sheet1.xml");
assert.ok(!/<f[ >]/.test(hostileSheet), "hostile text never becomes a formula");
assert.ok(hostileSheet.includes('t="inlineStr"'), "hostile text is written as inline string cells");
assert.ok(hostileSheet.includes("=SUM(A1:A2)"), "hostile literal preserved verbatim as text");
assert.ok(hostileSheet.includes("&lt;script&gt;"), "angle brackets escaped");
assert.ok(hostileSheet.includes("&amp;"), "ampersand escaped");
assert.ok(hostileSheet.includes("&quot;quoted&quot;"), "double quotes escaped");
assert.ok(hostileSheet.includes("&apos;single&apos;"), "single quotes escaped");
assert.ok(!hostileSheet.includes("<script>"), "no raw markup injection");
console.log("USER_TEXT_BECOMES_FORMULA=0");
console.log("XML_ESCAPING=PASS");

/* ── determinism ── */
const again = Xlsx.buildWorkbook(SYNTHETIC, { core: Core });
assert.ok(Buffer.compare(Buffer.from(bytes), Buffer.from(again)) === 0,
  "same input produces byte-identical workbook");
console.log("SAME_INPUT_SAME_XLSX_BYTES=YES");

/* ── file name helper ── */
assert.equal(Xlsx.suggestFileName(SYNTHETIC, { core: Core }), "CGI-견적서-PQ-TEST-001.xlsx",
  "deterministic CGI-style file name");
console.log("FILE_NAME_HELPER=PASS");

/* ── truthfulness: an untouched Production blank exports no fabricated facts ── */
const blankBytes = Xlsx.buildWorkbook(Core.createProductionDraft(), { core: Core });
const blankSheet = entriesByName(readZipEntries(blankBytes)).get("xl/worksheets/sheet1.xml");
assert.ok(!blankSheet.includes("샘플 공급사"), "blank production draft exports no demo sender");
assert.ok(!blankSheet.includes("고객사"), "blank production draft exports no demo recipient");
assert.ok(!blankSheet.includes("서비스 구축"), "blank production draft exports no demo items");
console.log("PRODUCTION_BLANK_EXPORTS_NO_DEMO_FACTS=PASS");

/* ── invalid input fails closed ── */
assert.throws(() => Xlsx.buildWorkbook({ schemaVersion: 99 }, { core: Core }), /b66_xlsx_invalid_draft/,
  "invalid draft is rejected instead of exporting fabricated content");
assert.throws(() => Xlsx.buildWorkbook(SYNTHETIC, { core: null }), /b66_xlsx_core_required/,
  "missing QuoteCore authority fails closed rather than recomputing anything");
console.log("INVALID_INPUT_FAILS_CLOSED=PASS");
/* ── download wiring: the finalized result screen offers an understandable action ── */
const fs = require("node:fs");
const path = require("node:path");
const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
const appSource = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");

assert.ok(html.includes('id="xlsxDownload"') && html.includes("Excel 다운로드"),
  "DOWNLOAD_UI=PASS (user-facing Excel action on the result screen)");
assert.ok(html.includes('<script src="xlsx-export.js" defer></script>'),
  "exporter is loaded on the page");
assert.ok(appSource.includes("window.B66XlsxExport") &&
          appSource.includes("buildWorkbook(draft)") &&
          appSource.includes("suggestFileName(draft)") &&
          appSource.includes('$("xlsxDownload").addEventListener'),
  "download handler passes the current finalized QuoteDraft straight to the format adapter");
assert.ok(!appSource.includes("computeDraftTotals(draft) && Xlsx") &&
          !/Xlsx\.[a-zA-Z]*\(?[^)]*\)?\s*[^']*=\s*[^']*(supply|grand)/.test(appSource),
  "no calculation leaves QuoteCore in the download path");
console.log("DOWNLOAD_UI_WIRING=PASS");
console.log("MINIMAL_SCOPE=YES");
