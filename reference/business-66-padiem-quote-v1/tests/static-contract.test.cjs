const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert");

const read = (name) => fs.readFileSync(path.join(__dirname, "..", name), "utf8");
const html = read("index.html");
const css = read("styles.css");
const app = read("app.js");
const core = read("quote-core.js");
const extraction = read("quote-extraction.js");
const history = read("quote-history.js");
const intake = read("file-intake.js");
const easy = read("easy-mode.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);

/* B66_STATIC_CONTRACT — 화면 구조/스크립트 계약 */
[
  "견적서 만들기",
  "샘플 공급사",
  'href="styles.css"',
  'src="quote-core.js"',
  'src="quote-extraction.js"',
  'src="quote-history.js"',
  'src="file-intake.js"',
  'src="app.js"',
  'src="easy-mode.js"',
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
  'id="pvTaxMode"',
  'id="easyModeButton"',
  'id="directModeButton"',
  'id="easyView"',
  'id="directView"',
  'id="guidedStarter"',
  'id="recentQuoteStarter"',
  'id="resumeDraftStarter"',
  'id="easyFileInput"',
  'id="fileStarter"',
  'id="saveHistory"',
  'id="resetLocalData"'
].forEach((marker) => check(html.includes(marker), `B66_STATIC_CONTRACT missing in index.html: ${marker}`));

/* NEUTRAL_PUBLIC_UI_CONTRACT — 외부 화면/상태에 내부 제품 브랜드를 노출하지 않음 */
check(!/(Padiem|파디엠|padiem)/.test(html + app + core + extraction + history + intake + easy),
  "NEUTRAL_PUBLIC_UI_CONTRACT: no Padiem branding in rendered/runtime source");
check(!html.includes("B66 DEMO"), "NEUTRAL_PUBLIC_UI_CONTRACT: no internal demo label");
check(html.includes("BETA · 입력 내용은 이 브라우저에만 저장"),
  "NEUTRAL_PUBLIC_UI_CONTRACT: truthful browser-local persistence label");

/* EXTRACTION_BOUNDARY_CONTRACT — 모델/프로바이더 비종속 추출 seam */
check(extraction.includes("function normalizeExtraction("),
  "EXTRACTION_BOUNDARY_CONTRACT: normalizer exists");
check(extraction.includes("function buildDraftCandidate("),
  "EXTRACTION_BOUNDARY_CONTRACT: draft candidate mapper exists");
check(app.includes("review_confirmation_required"),
  "EXTRACTION_BOUNDARY_CONTRACT: explicit confirmation required before apply");
check(app.includes("Extraction.buildDraftCandidate(draft, raw)"),
  "EXTRACTION_BOUNDARY_CONTRACT: app uses validated mapper");
check(app.includes("Core.normalizeDraft(candidate.value.draft)"),
  "EXTRACTION_BOUNDARY_CONTRACT: QuoteCore normalizes applied draft");
check(extraction.includes('candidate.meta.source = "extraction:" + extracted.source.kind'),
  "EXTRACTION_BOUNDARY_CONTRACT: extraction source provenance");
check(!/(kilo\/|sensenova\/|b-ai\/|gpt-5\.6-luna|space-bunny)/i.test(extraction + app),
  "EXTRACTION_BOUNDARY_CONTRACT: no provider/model ids in B66 seam");
check(!extraction.includes("grand =") && !extraction.includes("vat =") && !extraction.includes("supply ="),
  "EXTRACTION_BOUNDARY_CONTRACT: extraction layer owns no totals");

/* EASY_MODE_CONTRACT — 기존 직접입력 화면 앞에 deterministic chat UX */
check(html.includes("쉽게 만들기") && html.includes("직접 입력"),
  "EASY_MODE_CONTRACT: top-level easy/direct switch");
check(html.includes("질문받으며 새로 만들기") && html.includes("내용을 한번에 말하기"),
  "EASY_MODE_CONTRACT: easy entry choices");
check(easy.includes('App.createFreshDraft("guided")') &&
      app.includes('fresh.meta.source = source || "manual"'),
  "EASY_MODE_CONTRACT: deterministic guided draft uses shared fresh-draft allocator");
check(easy.includes("function processGuidedInput("),
  "EASY_MODE_CONTRACT: guided state machine");
check(easy.includes("Core.computeTotals(guided.draft.items, guided.draft.tax.mode)"),
  "EASY_MODE_CONTRACT: summary uses QuoteCore totals");
check(css.includes(".easy-chip {") && css.includes("min-height: 44px;"),
  "EASY_MODE_CONTRACT: quick chips meet 44px touch target");
check(!easy.includes("fetch(") && !easy.includes("XMLHttpRequest") &&
      !intake.includes("fetch(") && !intake.includes("XMLHttpRequest"),
  "EASY_MODE_CONTRACT: no network/model call in Easy/file intake mode");
check(easy.includes("아직 자동 해석 모델은 연결 전"),
  "EASY_MODE_CONTRACT: free-chat truthfulness");
check(easy.includes("자동 분석 서버는 아직 활성화 전") &&
      easy.includes("이 파일은 외부로 전송되지 않습니다."),
  "EASY_MODE_CONTRACT: selected file is truthful about non-live analysis");
check(app.includes("window.B66QuoteAppBridge"),
  "EASY_MODE_CONTRACT: reuses existing QuoteDraft renderer");
check(html.includes('id="directView"'),
  "EASY_MODE_CONTRACT: direct mode preserved");
check(easy.includes("function startGuided(referenceText)") &&
      easy.includes("startGuided(freeChatPending)") &&
      easy.includes("참고용으로 그대로 남겨둘게요"),
  "FREE_TEXT_CONTINUITY_CONTRACT: one-shot text remains visible when guided flow continues");
check(easy.includes("QuoteDraft에 자동 반영하지 않습니다."),
  "FREE_TEXT_CONTINUITY_CONTRACT: preserved reference is explicitly non-authoritative");

/* FILE_INTAKE_CONTRACT — local chooser/preflight live, upload/model still off */
check(html.includes('id="easyFileInput"') && html.includes('type="file"'),
  "FILE_INTAKE_CONTRACT: real browser file chooser exists");
check(html.includes(".pdf,.docx,.pptx,.xlsx,.hwpx,.jpg,.jpeg,.png,.webp"),
  "FILE_INTAKE_CONTRACT: bounded supported extensions");
check(intake.includes("MAX_DOCUMENT_BYTES = 2 * 1024 * 1024") &&
      intake.includes("MAX_IMAGE_BYTES = 4 * 1024 * 1024"),
  "FILE_INTAKE_CONTRACT: client file size bounds");
check(intake.includes('if (extension === ".hwp")'),
  "FILE_INTAKE_CONTRACT: legacy HWP explicitly unsupported");
check(easy.includes("function startFileIntake(") &&
      easy.includes("fileInput.click()") &&
      easy.includes("FileIntake.classifyFile(file)"),
  "FILE_INTAKE_CONTRACT: file chooser and preflight are wired");
check(app.includes('new CustomEvent("b66:open-file-intake")') &&
      easy.includes('"b66:open-file-intake"'),
  "FILE_INTAKE_CONTRACT: direct and Easy entry reuse one intake UX");
check(!intake.includes("localStorage") && !intake.includes("sessionStorage"),
  "FILE_INTAKE_CONTRACT: raw file preflight has no persistence");
check(!easy.includes("FileReader") && !intake.includes("FileReader"),
  "FILE_INTAKE_CONTRACT: browser does not materialize raw bytes yet");
check(!easy.includes("FormData") && !intake.includes("FormData"),
  "FILE_INTAKE_CONTRACT: browser has no upload transport");
check(easy.includes("업로드 0건") && easy.includes("파일 내용 저장 0건"),
  "FILE_INTAKE_CONTRACT: user-visible privacy truth");
check(intake.includes('declared === "application/octet-stream"') &&
      intake.includes('declared === "application/zip"') &&
      intake.includes('declared === "application/x-zip-compressed"'),
  "FILE_INTAKE_CONTRACT: generic browser MIME fallbacks are explicit");
check(intake.includes("isGenericMedia(extension, declared) ? spec.media[0] : declared"),
  "FILE_INTAKE_CONTRACT: generic MIME canonicalizes to expected media type");

/* RECENT_HISTORY_CONTRACT — active autosave와 최근 견적 snapshot 분리 */
check(history.includes('HISTORY_STORAGE_KEY = "quoteBeta.history.v1"'),
  "RECENT_HISTORY_CONTRACT: dedicated storage key");
check(history.includes("MAX_HISTORY = 20"),
  "RECENT_HISTORY_CONTRACT: bounded history");
check(history.includes('SEQUENCE_STORAGE_KEY = "quoteBeta.quoteNoSequence.v1"'),
  "RECENT_HISTORY_CONTRACT: dedicated browser-local quote number sequence");
check(history.includes("function allocateQuoteNo(") && history.includes("function copyAsNew("),
  "RECENT_HISTORY_CONTRACT: copy/new quotes use readable daily allocation");
check(app.includes("function createFreshDraft(") && app.includes("function copyHistoryAsNew("),
  "RECENT_HISTORY_CONTRACT: direct and Easy flows share allocator");
check(easy.includes('App.createFreshDraft("guided")') && easy.includes("App.copyHistoryAsNew(entry)"),
  "RECENT_HISTORY_CONTRACT: guided/copy paths use shared allocation");
check(history.includes("Core.computeTotals(entry.draft.items, entry.draft.tax.mode)"),
  "RECENT_HISTORY_CONTRACT: displayed totals are derived");
check(easy.includes("window.confirm(\"이 최근 견적을 이 브라우저에서 삭제할까요?\")"),
  "RECENT_HISTORY_CONTRACT: delete confirmation");
check(easy.includes("window.confirm(\"현재 작성 중인 견적을 바꾸고 이 견적을 불러올까요?\")"),
  "RECENT_HISTORY_CONTRACT: load overwrite confirmation");
check(app.includes("saveCurrentToHistory"),
  "RECENT_HISTORY_CONTRACT: direct mode can save current quote");
check(history.includes("function upsertEntryByQuoteNo(") &&
      app.includes("History.upsertEntryByQuoteNo(before, draft)"),
  "RECENT_HISTORY_CONTRACT: repeated save updates same quote number instead of duplicating");

/* KOREAN_MONEY_INPUT_CONTRACT — 한국식 콤마 단가 입력 계약
   (품목 행의 단가/수량 입력은 app.js 템플릿에서 생성되므로 app.js를 검사) */
check(app.includes('inputmode="numeric"'), "KOREAN_MONEY_INPUT_CONTRACT: price inputmode");
check(app.includes('inputmode="decimal"'), "KOREAN_MONEY_INPUT_CONTRACT: qty inputmode");
check(!html.includes('type="number"') && !app.includes('type="number"'), "KOREAN_MONEY_INPUT_CONTRACT: no type=number inputs");
check(core.includes("function parseMoney(") && core.includes("function formatMoney(") && core.includes("function formatInputNumber("),
  "KOREAN_MONEY_INPUT_CONTRACT: parse/format separated in quote-core");
check(app.includes("Core.parseMoney"), "KOREAN_MONEY_INPUT_CONTRACT: app uses Core.parseMoney");
check(core.includes("function parseKoreanMoney(") &&
      easy.includes("Core.parseKoreanMoney(text)"),
  "KOREAN_INPUT_POLISH_CONTRACT: Easy price uses deterministic Korean money parser");
check(easy.includes("150만원") && easy.includes("복합 단위는 추측하지 않습니다."),
  "KOREAN_INPUT_POLISH_CONTRACT: Korean shorthand is discoverable and ambiguous forms fail safe");

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

/* NEW_QUOTE_SAFETY_CONTRACT — public beta 새 견적은 다음 고객용 빈 상태 */
check(core.includes("function createBlankQuoteDraft("),
  "NEW_QUOTE_SAFETY_CONTRACT: domain helper exists");
check(app.includes("function createBlankNextDraft(") &&
      app.includes("draft = next;"),
  "NEW_QUOTE_SAFETY_CONTRACT: direct new quote uses blank-next helper");
check(core.includes('recipient: { company: "", person: "", address: "", email: "" }') &&
      core.includes('items: [{ id: "item-1", name: "", qty: 1, unitPrice: 0 }]'),
  "NEW_QUOTE_SAFETY_CONTRACT: next customer fields are blank");
check(app.includes("보내는 사람 정보는 유지하고 새 고객 견적을 시작합니다."),
  "NEW_QUOTE_SAFETY_CONTRACT: user-visible sender preservation");

/* UNKNOWN_VAT_REVIEW_CONTRACT — 미확정 세금은 확정 합계처럼 보이지 않음 */
check(html.includes('id="taxReviewNote"') && html.includes('id="taxRow"'),
  "UNKNOWN_VAT_REVIEW_CONTRACT: direct review surface exists");
check(css.includes(".tax-row.tax-review-required"),
  "UNKNOWN_VAT_REVIEW_CONTRACT: direct review highlight exists");
check(easy.includes('"품목 합계(세금 확인 전): "') &&
      easy.includes("최종 합계는 부가세 방식을 선택한 뒤 확정됩니다."),
  "UNKNOWN_VAT_REVIEW_CONTRACT: unknown VAT summary is explicitly provisional");
check(easy.includes("requireTaxReview: guided.taxUnknown") &&
      easy.includes("App.focusTaxReview()"),
  "UNKNOWN_VAT_REVIEW_CONTRACT: direct mode review is required and focused");
check(app.includes("taxReviewRequired = false;") &&
      app.includes('$("taxMode").addEventListener("change"'),
  "UNKNOWN_VAT_REVIEW_CONTRACT: choosing VAT clears review state");

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
check(css.includes(".topbar, .workspace-modebar, .easy-view, .modebar, .future-note, .panel, .preview-toolbar, .toast { display: none !important; }"),
  "PRINT_LAYOUT_CONTRACT: all non-print Easy/Direct UI removed from layout");
check(css.includes(".direct-view[hidden] { display: block !important; }"),
  "PRINT_LAYOUT_CONTRACT: hidden Direct view is restored for printing from Easy Mode");
check(css.includes(".grid { display: block; }"), "PRINT_LAYOUT_CONTRACT: paper in normal flow");
check(!css.includes("visibility: hidden"), "PRINT_LAYOUT_CONTRACT: visibility hack removed");
check(core.includes("function printReadiness(") &&
      app.includes("function printReadinessFailure("),
  "PRINT_READINESS_CONTRACT: deterministic readiness helper is wired before print");
check(app.includes("const failure = printReadinessFailure();") &&
      app.includes("if (failure)") &&
      app.includes("focusReadinessTarget(failure.code)") &&
      app.includes("return;"),
  "PRINT_READINESS_CONTRACT: incomplete quote exits before print and focuses the first missing field");
check(app.includes('code: "tax_review"') &&
      app.includes("if (failure.code === \"tax_review\") focusTaxReview();"),
  "PRINT_READINESS_CONTRACT: unresolved VAT blocks print and focuses VAT control");
check(app.includes('data-tax-review-placeholder="true"') &&
      app.includes('placeholder.textContent = "부가세 방식을 선택해 주세요"') &&
      app.includes('select.value = ""'),
  "PRINT_READINESS_CONTRACT: unresolved VAT requires an explicit select choice");

/* BETA_POLISH_CONTRACT — repeated-use/accessibility/privacy */
check(css.includes(".workspace-mode {") && css.includes("min-height: 44px;"),
  "BETA_POLISH_CONTRACT: workspace controls meet 44px target");
check(css.includes(".mode { min-height: 44px;") &&
      css.includes(".btn { min-height: 44px;") &&
      css.includes(".icon-btn { width: 44px; height: 44px;") &&
      css.includes(".easy-history-actions button {\n  min-height: 44px;"),
  "BETA_POLISH_CONTRACT: visible action controls use 44px minimum");
check(html.includes("저장 데이터 초기화") && app.includes("function resetBrowserLocalData("),
  "BETA_POLISH_CONTRACT: first-party browser reset exists");
check(app.includes("Core.DRAFT_STORAGE_KEY") &&
      app.includes("Core.SENDER_STORAGE_KEY") &&
      app.includes("History.HISTORY_STORAGE_KEY") &&
      app.includes("History.SEQUENCE_STORAGE_KEY"),
  "BETA_POLISH_CONTRACT: reset enumerates B66-owned keys");
check(app.includes("localStorage.removeItem(key)") &&
      !app.includes("localStorage.clear("),
  "BETA_POLISH_CONTRACT: reset never clears unrelated origin storage");
check(easy.includes('"b66:local-data-reset"') &&
      easy.includes('fileInput.value = ""'),
  "BETA_POLISH_CONTRACT: reset clears ephemeral selected-file state");

/* 결정론적 계산 잔여 계약 (원본에서 승계) */
check(core.includes("Math.round(qty * price)"), "deterministic item amount");
check(app.includes("window.print()"), "print action");
check(app.includes("localStorage"), "browser-local persistence");

/* FILE_CHOOSER_LIVE=YES / UPLOAD_AI_LIVE=NO */
check(html.includes("파일 불러오기") && html.includes('id="easyFileInput"'),
  "FILE_CHOOSER_LIVE=YES: file selection surface is live");
check(easy.includes("파일 선택과 안전 검증은 완료됐습니다.") &&
      easy.includes("업로드·OCR·AI 처리는 시작하지 않았습니다."),
  "UPLOAD_AI_LIVE=NO: analysis remains explicitly non-live");
check(!easy.includes("fetch(") && !intake.includes("fetch("),
  "UPLOAD_AI_LIVE=NO: no browser upload request");

/* CHAT_AI_LIVE=NO */
check(app.includes("자연어 채팅 → QuoteDraft 자동 입력은 다음 단계에서 연결합니다."),
  "CHAT_AI_LIVE=NO: chat is explicitly future");

/* EMAIL_SEND_LIVE=NO */
check(app.includes("이메일 전송은 다음 단계에서"), "EMAIL_SEND_LIVE=NO: email is future");
check(html.includes("이메일 보내기 · 다음 단계"), "EMAIL_SEND_LIVE=NO: future label");

console.log("B66_STATIC_CONTRACT=PASS");
console.log("NEUTRAL_PUBLIC_UI_CONTRACT=PASS");
console.log("EXTRACTION_BOUNDARY_CONTRACT=PASS");
console.log("EASY_MODE_CONTRACT=PASS");
console.log("FILE_INTAKE_CONTRACT=PASS");
console.log("FILE_CHOOSER_LIVE=YES");
console.log("BROWSER_UPLOAD_NETWORK=0");
console.log("RECENT_HISTORY_CONTRACT=PASS");
console.log("HISTORY_SAVE_UPSERT_CONTRACT=PASS");
console.log("BETA_POLISH_CONTRACT=PASS");
console.log("VISIBLE_ACTION_MIN_HEIGHT_44PX=YES");
console.log("B66_LOCAL_RESET_CONTRACT=PASS");
console.log("HUMAN_READABLE_QUOTE_NO_CONTRACT=PASS");
console.log("KOREAN_MONEY_INPUT_CONTRACT=PASS");
console.log("KOREAN_INPUT_POLISH_CONTRACT=PASS");
console.log("FREE_TEXT_CONTINUITY_CONTRACT=PASS");
console.log("QUOTEDRAFT_SCHEMA_CONTRACT=PASS");
console.log("NEW_QUOTE_SAFETY_CONTRACT=PASS");
console.log("UNKNOWN_VAT_REVIEW_CONTRACT=PASS");
console.log("DRAFT_SAVE_CONTRACT=PASS");
console.log("DRAFT_RESTORE_CONTRACT=PASS");
console.log("VAT_EXCLUSIVE_CONTRACT=PASS");
console.log("VAT_INCLUSIVE_CONTRACT=PASS");
console.log("VAT_EXEMPT_CONTRACT=PASS");
console.log("VALID_UNTIL_CONTRACT=PASS");
console.log("ADDRESS_FIELDS_CONTRACT=PASS");
console.log("PRINT_LAYOUT_CONTRACT=PASS");
console.log("PRINT_READINESS_CONTRACT=PASS");
console.log("UPLOAD_AI_LIVE=NO");
console.log("CHAT_AI_LIVE=NO");
console.log("EMAIL_SEND_LIVE=NO");
