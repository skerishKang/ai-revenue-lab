const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");

const required = [
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
  "window.print()",
  "localStorage",
  "Math.round(qty * price)",
  "Math.round(subtotal * 0.10)",
  "파일 올리기 · 다음 단계",
  "채팅으로 만들기 · 다음 단계",
  "이메일 보내기 · 다음 단계"
];

for (const marker of required) {
  assert.ok(html.includes(marker), `missing contract marker: ${marker}`);
}

assert.ok(
  html.includes("@media print") && html.includes("@page { size: A4"),
  "print-to-PDF contract missing"
);

assert.ok(
  html.includes("이 데모에서는 파일을 외부로 전송하지 않습니다."),
  "upload must be clearly non-live"
);

console.log("B66_PADIEM_QUOTE_STATIC_CONTRACT=PASS");
