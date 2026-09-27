const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert");

const read = (name) => fs.readFileSync(path.join(__dirname, "..", name), "utf8");
const html = read("index.html");
const css = read("styles.css");
const app = read("app.js");
const core = read("quote-core.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);

/* B66_STATIC_CONTRACT — 화면 구조/스크립트 계약 */
[
  "Padiem Quote",
  "파디엠 견적",
  'href="styles.css"',
  'src="quote-core.js"',
  'src="app.js"',
  'id="senderPreset"',
  'id="senderCompany"',
  'id="senderAddress"',
  'id="recipientCompany"',
  'id="recipientAddress"',
  'id="quoteDate"',
  'id="quoteNo"',
  'id="items"',
  'id="taxMode"',
  'id="newQuote"',
  'id="quotePaper"',
  'id="printPdf"',
  'id="pvValidUntil"',
  'id="pvTaxMode"'
].forEach((marker) => check(html.includes(marker), `B66_STATIC_CONTRACT missing in index.html: ${marker}`));

/* KOREAN_MONEY_INPUT_CONTRACT — 한국식 콤마 단가 입력 계약
   (품목 행의 단가/수량 입력은 app.js 템플릿에서 생성되므로 app.js를 검사) */
check(app.includes('inputmode="numeric"'), "KOREAN_MONEY_INPUT_CONTRACT: price inputmode");
check(app.includes('inputmode="decimal"'), "KOREAN_MONEY_INPUT_CONTRACT: qty inputmode");
check(!html.includes('type="number"') && !app.includes('type="number"'), "KOREAN_MONEY_INPUT_CONTRACT: no type=number inputs");
check(core.includes("function parseMoney(") && core.includes("function formatMoney(") && core.includes("function formatInputNumber("),
  "KOREAN_MONEY_INPUT_CONTRACT: parse/format separated in quote-core");
check(app.includes("Core.parseMoney"), "KOREAN_MONEY_INPUT_CONTRACT: app uses Core.parseMoney");

/* QUOTEDRAFT_SCHEMA_CONTRACT — QuoteDraft 스키마 계약 */
[
  "schemaVersion:",
  "quoteNo:", "issueDate:", "validDays:", "source:",
  "company:", "rep:", "bizNo:", "address:", "phone:", "email:", "presetId:",
  "person:",
  "items:",
  "tax:",
  "memo:"
].forEach((key) => check(core.includes(key), `QUOTEDRAFT_SCHEMA_CONTRACT missing in quote-core.js: ${key}`));
check(app.includes("Core.createDefaultDraft"), "QUOTEDRAFT_SCHEMA_CONTRACT: app default draft from core");

/* DRAFT_SAVE_CONTRACT — draft 자동 저장 계약 */
check(app.includes("localStorage.setItem(Core.DRAFT_STORAGE_KEY, JSON.stringify(draft))"),
  "DRAFT_SAVE_CONTRACT: autosave whole draft");
check(app.includes("saveDraft();"), "DRAFT_SAVE_CONTRACT: render triggers save");

/* DRAFT_RESTORE_CONTRACT — 복원 + 손상 fallback 계약 */
check(app.includes("Core.normalizeDraft(JSON.parse(localStorage.getItem(Core.DRAFT_STORAGE_KEY)"),
  "DRAFT_RESTORE_CONTRACT: restore via normalizeDraft");
check(app.includes("catch (err)"), "DRAFT_RESTORE_CONTRACT: corrupted storage fallback");
check(core.includes("if (raw.schemaVersion !== SCHEMA_VERSION) return null;"),
  "DRAFT_RESTORE_CONTRACT: schema version guard");

/* VAT_EXCLUSIVE_CONTRACT */
check(core.includes("vat = Math.round(subtotal * 0.10);"), "VAT_EXCLUSIVE_CONTRACT formula");
check(core.includes("grand = supply + vat;"), "VAT_EXCLUSIVE_CONTRACT grand");

/* VAT_INCLUSIVE_CONTRACT */
check(core.includes("supply = Math.round(grand / 1.10);"), "VAT_INCLUSIVE_CONTRACT supply");
check(core.includes("vat = grand - supply;"), "VAT_INCLUSIVE_CONTRACT vat");

/* VAT_EXEMPT_CONTRACT */
check(core.includes('EXEMPT: "EXEMPT"'), "VAT_EXEMPT_CONTRACT mode");
check(core.includes("vat = 0;"), "VAT_EXEMPT_CONTRACT vat");

/* VALID_UNTIL_CONTRACT — 유효일 파생 계약 */
check(core.includes("function computeValidUntil("), "VALID_UNTIL_CONTRACT: core function");
check(html.includes('id="pvValidUntil"'), "VALID_UNTIL_CONTRACT: preview element");
check(app.includes("유효일"), "VALID_UNTIL_CONTRACT: preview label");

/* ADDRESS_FIELDS_CONTRACT — 주소 필드 계약 */
check(html.includes('id="senderAddress"') && html.includes('id="recipientAddress"'),
  "ADDRESS_FIELDS_CONTRACT: input fields");
check(html.includes('id="pvSenderAddress"') && html.includes('id="pvRecipientAddress"'),
  "ADDRESS_FIELDS_CONTRACT: preview elements");

/* PRINT_LAYOUT_CONTRACT — 빈 페이지 없는 A4 인쇄 계약 */
check(css.includes("@page { size: A4"), "PRINT_LAYOUT_CONTRACT: A4 page rule");
check(css.includes("@media print"), "PRINT_LAYOUT_CONTRACT: print media");
check(css.includes(".topbar, .modebar, .future-note, .panel, .preview-toolbar, .toast { display: none !important; }"),
  "PRINT_LAYOUT_CONTRACT: non-print UI removed from layout");
check(css.includes(".grid { display: block; }"), "PRINT_LAYOUT_CONTRACT: paper in normal flow");
check(!css.includes("visibility: hidden"), "PRINT_LAYOUT_CONTRACT: visibility hack removed");

/* 결정론적 계산 잔여 계약 (원본에서 승계) */
check(core.includes("Math.round(qty * price)"), "deterministic item amount");
check(app.includes("window.print()"), "print action");
check(app.includes("localStorage"), "browser-local persistence");

/* UPLOAD_AI_LIVE=NO */
check(app.includes("이 데모에서는 파일을 외부로 전송하지 않습니다."),
  "UPLOAD_AI_LIVE=NO: upload is explicitly non-live");
check(html.includes("파일 올리기 · 다음 단계"), "UPLOAD_AI_LIVE=NO: future label");

/* CHAT_AI_LIVE=NO */
check(app.includes("자연어 채팅 → QuoteDraft 자동 입력은 다음 단계에서 연결합니다."),
  "CHAT_AI_LIVE=NO: chat is explicitly future");

/* EMAIL_SEND_LIVE=NO */
check(app.includes("이메일 전송은 다음 단계에서"), "EMAIL_SEND_LIVE=NO: email is future");
check(html.includes("이메일 보내기 · 다음 단계"), "EMAIL_SEND_LIVE=NO: future label");

console.log("B66_STATIC_CONTRACT=PASS");
console.log("KOREAN_MONEY_INPUT_CONTRACT=PASS");
console.log("QUOTEDRAFT_SCHEMA_CONTRACT=PASS");
console.log("DRAFT_SAVE_CONTRACT=PASS");
console.log("DRAFT_RESTORE_CONTRACT=PASS");
console.log("VAT_EXCLUSIVE_CONTRACT=PASS");
console.log("VAT_INCLUSIVE_CONTRACT=PASS");
console.log("VAT_EXEMPT_CONTRACT=PASS");
console.log("VALID_UNTIL_CONTRACT=PASS");
console.log("ADDRESS_FIELDS_CONTRACT=PASS");
console.log("PRINT_LAYOUT_CONTRACT=PASS");
console.log("UPLOAD_AI_LIVE=NO");
console.log("CHAT_AI_LIVE=NO");
console.log("EMAIL_SEND_LIVE=NO");
