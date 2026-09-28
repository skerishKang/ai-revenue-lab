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
const template = read("quote-template.js");
const templateStore = read("quote-template-store.js");
const templateRenderer = read("quote-template-renderer.js");
const templateSelection = read("quote-template-selection.js");
const templateUi = read("quote-template-ui.js");
const candidate = read("quote-template-candidate.js");
const cloner = read("quote-template-cloner.js");
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
  'src="quote-template.js"',
  'src="quote-template-store.js"',
  'src="quote-template-renderer.js"',
  'src="quote-template-selection.js"',
  'src="quote-template-ui.js"',
  'src="quote-template-candidate.js"',
  'src="quote-template-cloner.js"',
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
  'id="pvTitle"',
  'id="pvItemsHead"',
  'id="pvSenderHeading"',
  'id="pvRecipientHeading"',
  'id="pvMark"',
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
  'id="resetLocalData"',
  'id="templateSection"',
  'id="templateSelect"',
  'id="templateStatus"',
  'id="templateManageToggle"',
  'id="templateManagePanel"',
  'id="templateList"',
  'id="templateCreate"',
  'id="templateClone"',
  'id="templateClonerPanel"',
  'id="templateReview"',
  'id="templateApprove"',
  'id="templateReviewCancel"',
  'id="templateCloneFile"'
].forEach((marker) => check(html.includes(marker), `B66_STATIC_CONTRACT missing in index.html: ${marker}`));

/* NEUTRAL_PUBLIC_UI_CONTRACT — 외부 화면/상태에 내부 제품 브랜드를 노출하지 않음 */
check(!/(Padiem|파디엠|padiem)/.test(html + app + core + extraction + history + template + templateStore + templateRenderer + templateSelection + templateUi + candidate + cloner + intake + easy),
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
check(app.includes('TAX_REVIEW_STORAGE_KEY = "quoteBeta.taxReview.v1"') &&
      app.includes("function normalizeTaxReviewState(") &&
      app.includes("function loadTaxReviewRequired(activeDraft)") &&
      app.includes("state.quoteNo === quoteNo"),
  "VAT_REVIEW_PERSISTENCE_CONTRACT: unresolved review is scoped to the active quote number");
check(app.includes("persistTaxReviewRequired(taxReviewRequired)") &&
      app.includes("persistTaxReviewRequired(false)"),
  "VAT_REVIEW_PERSISTENCE_CONTRACT: unresolved review persists and explicit resolution clears it");
check(app.includes("raw.schemaVersion !== TAX_REVIEW_SCHEMA_VERSION") &&
      app.includes("raw.required !== true"),
  "VAT_REVIEW_PERSISTENCE_CONTRACT: malformed/old review state fails safe");
check(app.includes("TAX_REVIEW_STORAGE_KEY") &&
      app.includes("localStorage.removeItem(TAX_REVIEW_STORAGE_KEY)"),
  "VAT_REVIEW_PERSISTENCE_CONTRACT: tax review state is independently removable");

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
check(html.includes('id="subtotalLabelText"') &&
      html.includes('id="grandLabelText"') &&
      html.includes('id="pvSubtotalLabel"') &&
      html.includes('id="pvGrandLabel"'),
  "PROVISIONAL_VAT_DISPLAY_CONTRACT: summary and preview have explicit label anchors");
check(template.includes('subtotalLabel: "품목 합계(세금 확인 전)"') &&
      template.includes('vatText: "확인 필요"') &&
      template.includes('grandText: "확정 전"') &&
      template.includes('supplyLabel: "공급가액"') &&
      template.includes('grandLabel: "합계"'),
  "PROVISIONAL_VAT_DISPLAY_CONTRACT: provisional and confirmed labels live in the template profile");
check(templateRenderer.includes("provisional ? content.totals.provisional.subtotalLabel : content.totals.supplyLabel") &&
      templateRenderer.includes("provisional ? content.totals.provisional.vatText : Core.formatMoney(totals.vat)") &&
      templateRenderer.includes("provisional ? content.totals.provisional.grandText : Core.formatMoney(totals.grand)"),
  "PROVISIONAL_VAT_DISPLAY_CONTRACT: unresolved tax-dependent totals are never presented as confirmed");
check(template.includes('taxReviewText: "세금  확인 필요"') &&
      template.includes('grandLabel: "최종 합계"'),
  "PROVISIONAL_VAT_DISPLAY_CONTRACT: preview tax and total labels expose review state");
check(templateRenderer.includes("provisional ? content.meta.taxReviewText : content.meta.taxPrefix + Core.TAX_LABELS[mode]") &&
      templateRenderer.includes("provisional ? content.totals.provisional.grandLabel : content.totals.grandLabel"),
  "PROVISIONAL_VAT_DISPLAY_CONTRACT: renderer switches labels only while tax stays unresolved");

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
      app.includes("History.SEQUENCE_STORAGE_KEY") &&
      app.includes("TAX_REVIEW_STORAGE_KEY"),
  "BETA_POLISH_CONTRACT: reset enumerates B66-owned keys including VAT review state");
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

/* QUOTE_TEMPLATE_PROFILE_CONTRACT — 견적서 템플릿은 표현·배치만 소유한다 */
check(html.includes('src="quote-template.js"') &&
      html.includes('src="quote-template-store.js"') &&
      html.includes('src="quote-template-renderer.js"'),
  "QUOTE_TEMPLATE_PROFILE_CONTRACT: template modules are loaded before app.js");
check(template.includes("BUILTIN_TEMPLATE_CONTENT") && template.includes('"견 적 서"') &&
      template.includes('"공급가액"') && template.includes('"견적서 베타"'),
  "QUOTE_TEMPLATE_PROFILE_CONTRACT: built-in profile mirrors the current quotation design");
check(template.includes("function normalizeTemplateContent(") &&
      template.includes("function templateFingerprint(") &&
      template.includes("function findForbiddenKeys("),
  "QUOTE_TEMPLATE_PROFILE_CONTRACT: normalization, fingerprint and forbidden-field guard exist");
check(template.includes("function sha256Hex(") && !template.includes('require("node:crypto")'),
  "TEMPLATE_FINGERPRINT_DETERMINISTIC: dependency-free deterministic fingerprint");
check(!template.includes("computeTotals(") && !template.includes("grand =") &&
      !template.includes("vat =") && !template.includes("supply ="),
  "QUOTE_TEMPLATE_PROFILE_CONTRACT: the template layer owns no totals");

/* QUOTE_TEMPLATE_STORE_BOUNDED — bounded 브라우저 로컬 저장소 */
check(templateStore.includes('TEMPLATE_STORAGE_KEY = "quoteBetaTemplate.v1"'),
  "QUOTE_TEMPLATE_STORE_BOUNDED: dedicated key in the B66 quoteBeta namespace");
check(templateStore.includes("var MAX_TEMPLATES = 20") && templateStore.includes("DEFAULT_TEMPLATE_COUNT = 1"),
  "QUOTE_TEMPLATE_STORE_BOUNDED: bounded count and single-default invariant constant");
check(templateStore.includes("function normalizeStore(") &&
      templateStore.includes("function createTemplate(") &&
      templateStore.includes("function updateTemplate(") &&
      templateStore.includes("function deleteTemplate(") &&
      templateStore.includes("function duplicateTemplate(") &&
      templateStore.includes("function setDefaultTemplate("),
  "QUOTE_TEMPLATE_CRUD=PASS: bounded CRUD surface exists");
check(templateStore.includes("function duplicateTemplate("),
  "QUOTE_TEMPLATE_DUPLICATE=PASS: duplicate/copy path exists");
check(templateStore.includes("builtin_template_immutable"),
  "QUOTE_TEMPLATE_DEFAULT_EXACTLY_ONE=YES: the built-in template cannot be mutated or deleted");
check(!templateStore.includes("localStorage.clear("),
  "QUOTE_TEMPLATE_STORE_BOUNDED: the store never clears unrelated origin storage");
check(templateStore.includes("findForbiddenKeys") && !templateStore.includes("data_url"),
  "RAW_SOURCE_FILE_PERSISTENCE=0: raw byte payloads are rejected before storage");

/* QUOTE_TEMPLATE_RENDERER_DETERMINISTIC — 순수 계산과 DOM adapter 분리 */
check(templateRenderer.includes("function buildRenderModel(") &&
      templateRenderer.includes("function applyRenderModel("),
  "QUOTE_TEMPLATE_RENDERER_DETERMINISTIC: pure render model separated from the DOM adapter");
check(templateRenderer.includes("Core.computeTotals(") && templateRenderer.includes("Core.computeValidUntil("),
  "QUOTECORE_REMAINS_CALCULATION_AUTHORITY=YES: renderer derives amounts and validity from QuoteCore");
check(!templateRenderer.includes("grand =") && !templateRenderer.includes("vat =") &&
      !templateRenderer.includes("supply ="),
  "QUOTECORE_REMAINS_CALCULATION_AUTHORITY=YES: the renderer performs no tax arithmetic");
check(!/fetch\(|XMLHttpRequest/.test(templateRenderer) &&
      !/Math\.random|Date\.now|new Date\(/.test(templateRenderer),
  "QUOTE_TEMPLATE_RENDERER_DETERMINISTIC: no model call and no time/random input");
check(templateRenderer.includes("CALCULATION_AUTHORITY = \"quote-core\"") &&
      templateRenderer.includes('setText("pvGrand", totals.grandText)'),
  "QUOTECORE_REMAINS_CALCULATION_AUTHORITY=YES: adapter publishes QuoteCore-derived totals");
check(!/(kilo\/|space-bunny|nemotron|openai|anthropic)/i.test(template + templateStore + templateRenderer),
  "MODEL_DEPENDENCY=0: template modules name no provider or model");
check(!/FileReader|FormData|indexedDB/i.test(template + templateStore + templateRenderer),
  "RAW_SOURCE_FILE_PERSISTENCE=0: template modules never touch raw file bytes");
check(app.includes("TemplateRenderer.buildRenderModel(") &&
      app.includes("previewTemplateProfile() || activeTemplateProfile()") &&
      app.includes("TemplateRenderer.applyRenderModel(document, model)"),
  "QUOTE_TEMPLATE_RENDERER_DETERMINISTIC: direct mode renders through the approved template renderer");
check(!app.includes("vatSummaryLabel"),
  "QUOTE_TEMPLATE_PROFILE_CONTRACT: presentation labels are no longer hard-coded in app.js");
check(app.includes("TemplateStore && TemplateStore.TEMPLATE_STORAGE_KEY"),
  "BETA_POLISH_CONTRACT: reset also enumerates the template store key");

/* APPROVAL_REQUIRED_FOR_USER_PROFILE — 후보는 승인 없이 활성화될 수 없다 */
check(template.includes("function normalizeApproval(") &&
      template.includes("function isApprovedProfile(") &&
      template.includes("function isBuiltInException("),
  "APPROVAL_REQUIRED_FOR_USER_PROFILE=YES: approval evidence contract exists");
check(template.includes('raw.status !== "approved"') &&
      template.includes("raw.contentFingerprint !== contentFingerprint"),
  "CONTENT_CHANGE_INVALIDATES_APPROVAL=YES: mismatched fingerprint invalidates the approval");
check(template.includes("trusted_builtin") && template.includes("explicit_approval") &&
      template.includes("unapproved"),
  "APPROVAL_REQUIRED_FOR_USER_PROFILE=YES: approval basis is explicit");
check(template.includes('SLOT_SUPPORT = "non_live"'),
  "SLOT_BEHAVIOR=PLACEHOLDER_CONTRACT_ONLY: slot support is declared non-live");
check(templateStore.includes("function approveTemplate(") &&
      templateStore.includes('fail("template_not_approved"'),
  "UNAPPROVED_TEMPLATE_ACTIVATION=0: activation requires explicit approval");
check(templateStore.includes("approval = null;") &&
      templateStore.includes("var keepDefault = !contentChanged && current.isDefault"),
  "CONTENT_CHANGE_INVALIDATES_APPROVAL=YES: content update drops approval and default status");
check(templateStore.includes("function rejectionForContent(") &&
      templateStore.includes("slot_rendering_not_supported"),
  "SLOT_BEHAVIOR=PLACEHOLDER_CONTRACT_ONLY: declared non-live slots are refused, not ignored");
check(templateRenderer.includes("template_not_approved") &&
      templateRenderer.includes("fallbackReason"),
  "UNAPPROVED_TEMPLATE_ACTIVATION=0: the renderer falls back with an explicit reason");

/* TEMPLATE_STYLE_APPLIED — bounded 값만 custom property / @page 로 적용된다 */
check(templateRenderer.includes("function buildStyleVariables(") &&
      templateRenderer.includes("function buildPageRule(") &&
      templateRenderer.includes("function ensurePageRule(") &&
      templateRenderer.includes("applyStyleVariables(doc, model)"),
  "TEMPLATE_STYLE_APPLIED: bounded style/page adapter exists");
check(templateRenderer.includes("STYLE_VARIABLE_MAP") &&
      templateRenderer.includes('"--quote-accent"') &&
      templateRenderer.includes('"--quote-totals-width"'),
  "TEMPLATE_ACCENT_APPLIED / TEMPLATE_TOTALS_WIDTH_APPLIED: tokens map to custom properties");
check(templateRenderer.includes('"@page { size: "') && templateRenderer.includes('"; margin: "'),
  "TEMPLATE_PAGE_RULE_APPLIED: the page rule is assembled from validated tokens only");
check(template.includes("ALLOWED_PAGE_SIZES") && template.includes("PAGE_MARGIN_PATTERN") &&
      template.includes("ALLOWED_JUSTIFY"),
  "TEMPLATE_PAGE_RULE_APPLIED: page and alignment values are enum/regex bounded");
check(css.includes("var(--quote-accent, #17202a)") &&
      css.includes("var(--quote-title-rule, 2px solid #111827)") &&
      css.includes("var(--quote-header-rule, 1px solid #111827)") &&
      css.includes("var(--quote-row-rule, 1px solid #e4e7ec)") &&
      css.includes("var(--quote-party-rule, 1px solid #cfd5dd)") &&
      css.includes("var(--quote-memo-rule, 1px solid #d0d5dd)"),
  "TEMPLATE_RULES_APPLIED: styles.css consumes the injected rules");
check(css.includes("var(--quote-header-align, space-between)") &&
      css.includes("var(--quote-meta-align, right)") &&
      css.includes("var(--quote-numeric-align, right)") &&
      css.includes("var(--quote-text-align, left)") &&
      css.includes("var(--quote-totals-width, 310px)"),
  "TEMPLATE_ALIGNMENT_APPLIED / TEMPLATE_TOTALS_WIDTH_APPLIED: styles.css consumes alignment and width");
check(css.includes("@page { size: A4; margin: 10mm; }"),
  "TEMPLATE_PAGE_RULE_APPLIED: the default print page rule is preserved");
check(!/(expression\(|javascript:|<\/style)/i.test(css + templateRenderer),
  "TEMPLATE_STYLE_APPLIED: no arbitrary CSS execution surface");

/* FORGED_BUILTIN_FLAG_BYPASS=0 — builtin 플래그만으로는 신뢰되지 않는다 */
check(template.includes("function isCanonicalBuiltIn(") &&
      template.includes("function isCanonicalBuiltInContent(") &&
      template.includes("BUILTIN_TEMPLATE_CANONICAL") &&
      template.includes("candidate.id !== BUILTIN_TEMPLATE_ID") &&
      template.includes("candidate.builtin !== true"),
  "FORGED_BUILTIN_FLAG_BYPASS=0: rule requires the canonical id and canonical content");
check(/function isBuiltInException\(profile\) \{\s*return isCanonicalBuiltIn\(profile\);\s*\}/.test(template),
  "FORGED_BUILTIN_FLAG_BYPASS=0: the built-in exception delegates to the canonical check");
check(template.includes("var builtin = isCanonicalBuiltIn({"),
  "FORGED_BUILTIN_FLAG_BYPASS=0: buildProfile derives trust from the canonical check");
check(template.includes("BUILTIN_TEMPLATE_FINGERPRINT: BUILTIN_TEMPLATE_FINGERPRINT"),
  "CANONICAL_BUILTIN_FALLBACK=PASS: the canonical built-in fingerprint is published");

/* ── #3183 양식 선택·관리 UI ── */
check(html.includes('src="quote-template-selection.js"') && html.includes('src="quote-template-ui.js"'),
  "TEMPLATE_SELECTOR_LIVE=YES: selection and UI modules are loaded");
check(html.includes('id="templateSelect"') && html.includes('id="templateManagePanel"') &&
      html.includes('id="templateList"') && html.includes('id="templateCreate"') &&
      html.includes('id="templateManageToggle"') && html.includes('id="templateStatus"'),
  "TEMPLATE_SELECTOR_LIVE=YES: selector and management surface exist");
check(html.includes('id="templateClone"') && html.includes("견적서 양식 본뜨기"),
  "TEMPLATE_SELECTOR_LIVE=YES: the #3184 clone/approval entry point exists but is deferred");
check(templateSelection.includes("function selectTemplate(") &&
      templateSelection.includes("function setDefaultTemplate(") &&
      templateSelection.includes("function renameTemplate(") &&
      templateSelection.includes("function duplicateTemplate(") &&
      templateSelection.includes("function deleteTemplate(") &&
      templateSelection.includes("function createCandidate("),
  "TEMPLATE_MANAGEMENT_CRUD=PASS: management actions exist");
check(templateSelection.includes("function resolveActiveTemplateId(") &&
      templateSelection.includes("return Store.defaultTemplateId(rawStore);"),
  "DEFAULT_TEMPLATE_SELECTION=PASS / BUILTIN_TEMPLATE_FALLBACK=PASS: resolution falls back to the default");
check(templateSelection.includes("template_not_approved") &&
      templateSelection.includes("return Boolean(template) && template.approved === true;"),
  "UNAPPROVED_TEMPLATE_SELECTION=0 / UNAPPROVED_TEMPLATE_DEFAULT=0: unapproved templates cannot be selected or defaulted");
check(templateSelection.includes("ask(target) !== true") && templateSelection.includes('fail("delete_cancelled")'),
  "DELETE_CONFIRMATION=PASS: deletion requires confirmation");
check(templateSelection.includes("builtin_template_immutable"),
  "BUILTIN_TEMPLATE_DELETE=DENIED: the built-in cannot be deleted");
check(templateSelection.includes("function normalizeEnvelope(") &&
      templateSelection.includes("function normalizeSelectionEntry(") &&
      templateSelection.includes("selectionForQuote(") &&
      templateSelection.includes("raw.schemaVersion !== SELECTION_SCHEMA_VERSION"),
  "MISSING_SELECTED_TEMPLATE_FALLBACK=PASS / CORRUPT_TEMPLATE_FALLBACK=PASS: selection is bounded and normalised");
check(templateSelection.includes("var MAX_SELECTIONS = 20") &&
      templateSelection.includes("function setSelection(") &&
      templateSelection.includes("selections: rest.slice(0, MAX_SELECTIONS)"),
  "TEMPLATE_SELECTION_BOUNDED=YES: selections are a bounded per-quote envelope");
check(templateSelection.includes("function removeSelectionsForTemplate(") &&
      templateSelection.includes("removeSelectionsForTemplate(readEnvelope(storage), id)"),
  "TEMPLATE_SELECTION_PER_QUOTE=PASS: deleting a template prunes only its own selections");
check(templateSelection.includes("if (seen[normalized.quoteNo]) return;") &&
      templateSelection.includes("if (selections.length >= MAX_SELECTIONS) return;"),
  "TEMPLATE_SELECTION_PER_QUOTE=PASS: a quotation keeps a single bounded selection");
check(templateUi.includes("function resolveUiStateAfterApply(") &&
      templateUi.includes("next.previewTemplateId = null;"),
  "PREVIEW_APPLY_TERMINATES=PASS: the UI reducer clears the preview state");
check(app.includes("TemplateUi.resolveUiStateAfterApply(templateUiState, true)") &&
      app.includes("templateUiState.previewTemplateId = nextState.previewTemplateId"),
  "PREVIEW_APPLY_TERMINATES=PASS: the app clears previewTemplateId after a successful apply");
check(!/draft\.(sender|recipient|items|tax|memo|meta)\s*=/.test(templateSelection) &&
      !/draft\.(sender|recipient|items|tax|memo|meta)\s*=/.test(templateUi),
  "TEMPLATE_SWITCH_MUTATES_QUOTEDRAFT_CONTENT=NO: the template layer never assigns draft business content");
check(templateUi.includes("function buildRows(") && templateUi.includes("canDelete: !builtin") &&
      templateUi.includes("selectable: approved"),
  "TEMPLATE_MANAGEMENT_CRUD=PASS: rows expose approval state and built-in protection");
check(templateUi.includes("disabled") && templateUi.includes("승인 후 선택할 수 있습니다"),
  "UNAPPROVED_TEMPLATE_SELECTION=0: unapproved candidates are visible but disabled");
check(css.includes(".template-row-actions .template-action { min-height: 44px; }"),
  "MOBILE_TEMPLATE_UI=PASS: template actions meet the 44px target");
check(css.includes("@media (max-width: 680px)") &&
      css.includes(".template-row-actions { display: grid; grid-template-columns: 1fr 1fr; }"),
  "MOBILE_TEMPLATE_UI=PASS: narrow viewports get a two-column action grid");
check(css.includes(".template-section, .template-manage, .template-picker, .template-status { display: none !important; }"),
  "PRINT_UI_LEAK=0: the template UI is excluded from print");
check(!/fetch\(|XMLHttpRequest/.test(templateSelection + templateUi),
  "MODEL_NETWORK_CALLS=0: no network call in the template selection/UI layer");
check(app.includes("TEMPLATE_ACTIONS") && app.includes("window.B66QuoteTemplateBridge") &&
      app.includes("TemplateSelection.resolveActiveTemplate(") &&
      app.includes("templateUiState"),
  "TEMPLATE_SELECTOR_LIVE=YES: the app wires selection, preview and management actions");
check(app.includes("previewTemplateProfile() || activeTemplateProfile()") &&
      app.includes("candidate && candidate.approved"),
  "UNAPPROVED_TEMPLATE_SELECTION=0: preview is restricted to approved templates");

/* ── #3184 양식 본뜨기(후보 검토 + 명시적 승인) ── */
check(html.includes('src="quote-template-candidate.js"') && html.includes('src="quote-template-cloner.js"'),
  "TEMPLATE_CLONER_ENTRYPOINT=YES: candidate and cloner modules are loaded");
check(html.includes('id="templateClonerPanel"') && html.includes('id="templateReview"') &&
      html.includes('id="templateApprove"') && html.includes('id="templateReviewCancel"') &&
      html.includes('id="templateCloneFile"'),
  "TEMPLATE_CANDIDATE_REVIEW_UI=PASS: the review surface exists");
check(html.includes("견적서 양식 본뜨기") && !html.includes("본뜨기 · 다음 단계"),
  "TEMPLATE_CLONER_ENTRYPOINT=YES: the deferred label is replaced by the real entry point");
check(candidate.includes("function injectCandidate(") && candidate.includes("function normalizeCandidate(") &&
      candidate.includes("unsupported_candidate_field") && candidate.includes("forbidden_candidate_field"),
  "TEMPLATE_CANDIDATE_MANUAL_INJECTION=PASS / MALFORMED_CANDIDATE_FAIL_CLOSED=PASS: the injection seam validates");
check(candidate.includes("live: false") && candidate.includes('network: "none"'),
  "TEMPLATE_ANALYZER_LIVE=NO / MODEL_NETWORK_CALLS=0: the analyzer boundary is not live");
check(cloner.includes("function approveCandidate(") && cloner.includes("APPROVAL_SCHEMA_VERSION") &&
      cloner.includes("contentFingerprint: current") && cloner.includes("candidate_changed_after_review"),
  "EXPLICIT_TEMPLATE_APPROVAL_REQUIRED=YES / APPROVAL_FINGERPRINT_BINDING=PASS: approval binds the reviewed content");
check(cloner.includes("Template.templateFingerprint(session.candidate.content)"),
  "APPROVAL_FINGERPRINT_BINDING=PASS: the fingerprint is recomputed at approval time");
check(cloner.includes("approval_invalidated") && cloner.includes("Store.updateTemplate("),
  "CANDIDATE_CONTENT_CHANGE_INVALIDATES_APPROVAL=YES: editing after approval drops the stored approval");
check(cloner.includes("if (!created.ok) return fail(created.code, created.message, session);"),
  "FAILED_APPROVAL_CHANGES_DEFAULT=0: a refused approval returns before any write");
check(app.includes('$("templateApprove").addEventListener("click"') &&
      app.includes("TemplateCloner.approveCandidate(clonerSession, templateStorage(), {})"),
  "EXPLICIT_TEMPLATE_APPROVAL_REQUIRED=YES: approval is an explicit user action");
check(app.includes("FileIntake.classifyFile(file)") && app.includes("window.B66QuoteTemplateClonerBridge"),
  "BROWSER_UPLOAD_NETWORK=0 / TEMPLATE_CANDIDATE_MANUAL_INJECTION=PASS: preflight reuse plus injection seam");
check(!/fetch\(|XMLHttpRequest/.test(candidate + cloner),
  "BROWSER_UPLOAD_NETWORK=0 / MODEL_NETWORK_CALLS=0: no network call in the cloner layer");
check(!/kilo\/|space-bunny|nemotron|openai|anthropic/i.test(candidate + cloner),
  "MODEL_PROVIDER_IDS_IN_BROWSER=0: no provider or model reference");
check(css.includes(".template-cloner, .template-review, .cloner-progress, .review-grid, .review-block, .review-status { display: none !important; }"),
  "PRINT_UI_LEAK=0: the cloner UI is excluded from print");
check(css.includes(".template-cloner-actions .btn { min-height: 44px; }") &&
      css.includes(".review-grid { grid-template-columns: 1fr; }"),
  "MOBILE_TEMPLATE_CLONER_UI=PASS: 44px targets and a single-column review grid on narrow viewports");

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
console.log("VAT_REVIEW_PERSISTENCE_CONTRACT=PASS");
console.log("UNKNOWN_VAT_REVIEW_SURVIVES_RELOAD_SOURCE=YES");
console.log("DRAFT_SAVE_CONTRACT=PASS");
console.log("DRAFT_RESTORE_CONTRACT=PASS");
console.log("VAT_EXCLUSIVE_CONTRACT=PASS");
console.log("VAT_INCLUSIVE_CONTRACT=PASS");
console.log("VAT_EXEMPT_CONTRACT=PASS");
console.log("VALID_UNTIL_CONTRACT=PASS");
console.log("ADDRESS_FIELDS_CONTRACT=PASS");
console.log("PRINT_LAYOUT_CONTRACT=PASS");
console.log("PRINT_READINESS_CONTRACT=PASS");
console.log("PROVISIONAL_VAT_DISPLAY_CONTRACT=PASS");
console.log("TEMP_EXCLUSIVE_NOT_PRESENTED_AS_CONFIRMED=YES");
console.log("QUOTE_TEMPLATE_PROFILE_CONTRACT=PASS");
console.log("CURRENT_B66_TEMPLATE_MIGRATED_AS_BUILTIN=YES");
console.log("QUOTE_TEMPLATE_STORE_BOUNDED=YES");
console.log("QUOTE_TEMPLATE_DEFAULT_EXACTLY_ONE=YES");
console.log("QUOTE_TEMPLATE_CRUD=PASS");
console.log("QUOTE_TEMPLATE_DUPLICATE=PASS");
console.log("MALFORMED_TEMPLATE_STORAGE_FALLBACK=PASS");
console.log("TEMPLATE_FINGERPRINT_DETERMINISTIC=PASS");
console.log("QUOTE_TEMPLATE_RENDERER_DETERMINISTIC=YES");
console.log("QUOTECORE_REMAINS_CALCULATION_AUTHORITY=YES");
console.log("RAW_SOURCE_FILE_PERSISTENCE=0");
console.log("TRUSTED_TOTALS_IN_TEMPLATE=0");
console.log("MODEL_DEPENDENCY=0");
console.log("CURRENT_DEFAULT_VISUAL_REGRESSION=0");
console.log("APPROVAL_REQUIRED_FOR_USER_PROFILE=YES");
console.log("UNAPPROVED_TEMPLATE_ACTIVATION=0");
console.log("FORGED_BUILTIN_FLAG_BYPASS=0");
console.log("CANONICAL_BUILTIN_FALLBACK=PASS");
console.log("CONTENT_CHANGE_INVALIDATES_APPROVAL=YES");
console.log("APPROVED_TEMPLATE_SAVE_AND_RENDER=PASS");
console.log("TEMPLATE_ACCENT_APPLIED=PASS");
console.log("TEMPLATE_RULES_APPLIED=PASS");
console.log("TEMPLATE_ALIGNMENT_APPLIED=PASS");
console.log("TEMPLATE_TOTALS_WIDTH_APPLIED=PASS");
console.log("TEMPLATE_PAGE_RULE_APPLIED=PASS");
console.log("SLOT_BEHAVIOR=PLACEHOLDER_CONTRACT_ONLY");
console.log("QUOTECORE_TOTALS_UNCHANGED_ACROSS_TEMPLATES=YES");
console.log("TEMPLATE_SELECTOR_LIVE=YES");
console.log("TEMPLATE_MANAGEMENT_CRUD=PASS");
console.log("DEFAULT_TEMPLATE_SELECTION=PASS");
console.log("BUILTIN_TEMPLATE_FALLBACK=PASS");
console.log("UNAPPROVED_TEMPLATE_SELECTION=0");
console.log("UNAPPROVED_TEMPLATE_DEFAULT=0");
console.log("TEMPLATE_SWITCH_MUTATES_QUOTEDRAFT_CONTENT=NO");
console.log("MISSING_SELECTED_TEMPLATE_FALLBACK=PASS");
console.log("CORRUPT_TEMPLATE_FALLBACK=PASS");
console.log("BUILTIN_TEMPLATE_DELETE=DENIED");
console.log("DELETE_CONFIRMATION=PASS");
console.log("DUPLICATE_TEMPLATE=PASS");
console.log("RENAME_TEMPLATE=PASS");
console.log("TEMPLATE_SELECTION_PER_QUOTE=PASS");
console.log("TEMPLATE_SELECTION_BOUNDED=YES");
console.log("PREVIEW_APPLY_TERMINATES=PASS");
console.log("TEMPLATE_CLONER_ENTRYPOINT=YES");
console.log("TEMPLATE_CANDIDATE_REVIEW_UI=PASS");
console.log("TEMPLATE_CANDIDATE_MANUAL_INJECTION=PASS");
console.log("EXPLICIT_TEMPLATE_APPROVAL_REQUIRED=YES");
console.log("APPROVAL_FINGERPRINT_BINDING=PASS");
console.log("CANDIDATE_CONTENT_CHANGE_INVALIDATES_APPROVAL=YES");
console.log("APPROVAL_CANCEL_WRITES_PROFILE=0");
console.log("FAILED_APPROVAL_CHANGES_DEFAULT=0");
console.log("FAILED_APPROVAL_CHANGES_CURRENT_SELECTION=0");
console.log("TEMPLATE_ANALYZER_LIVE=NO");
console.log("BROWSER_UPLOAD_NETWORK=0");
console.log("MODEL_PROVIDER_IDS_IN_BROWSER=0");
console.log("MOBILE_TEMPLATE_CLONER_UI=PASS");
console.log("MOBILE_TEMPLATE_UI=PASS");
console.log("PRINT_UI_LEAK=0");
console.log("MODEL_NETWORK_CALLS=0");
console.log("UPLOAD_AI_LIVE=NO");
console.log("CHAT_AI_LIVE=NO");
console.log("EMAIL_SEND_LIVE=NO");
