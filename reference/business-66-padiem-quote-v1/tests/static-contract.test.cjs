const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert");

const read = (name) => fs.readFileSync(path.join(__dirname, "..", name), "utf8");
const html = read("index.html");
const css = read("styles.css");
const js = read("app.js");

// index.html — 화면 구조 계약
const htmlMarkers = [
  "Padiem Quote",
  "파디엠 견적",
  'id="senderPreset"',
  'id="recipientCompany"',
  'id="quoteDate"',
  'id="quoteNo"',
  'id="items"',
  'id="vatEnabled"',
  'id="quotePaper"',
  'id="printPdf"',
  'href="styles.css"',
  'src="app.js"',
  "파일 올리기 · 다음 단계",
  "채팅으로 만들기 · 다음 단계",
  "이메일 보내기 · 다음 단계"
];

for (const marker of htmlMarkers) {
  assert.ok(html.includes(marker), `index.html missing contract marker: ${marker}`);
}

// styles.css — A4 인쇄 계약
assert.ok(
  css.includes("@media print") && css.includes("@page { size: A4"),
  "print-to-PDF contract missing"
);

// app.js — 결정론적 계산 / 브라우저 로컬 저장 계약
const jsMarkers = [
  "window.print()",
  "localStorage",
  "Math.round(qty * price)",
  "Math.round(subtotal * 0.10)"
];

for (const marker of jsMarkers) {
  assert.ok(js.includes(marker), `app.js missing contract marker: ${marker}`);
}

assert.ok(
  js.includes("이 데모에서는 파일을 외부로 전송하지 않습니다."),
  "upload must be clearly non-live"
);

console.log("B66_PADIEM_QUOTE_STATIC_CONTRACT=PASS");
