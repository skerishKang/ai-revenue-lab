const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert");
const vm = require("node:vm");

const read = (name) => fs.readFileSync(path.join(__dirname, "..", name), "utf8");
const html = read("index.html");
const embed = read("embed.html");
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
const skill = read("quote-skill.js");
const skillStore = read("quote-skill-store.js");
const skillCandidate = read("quote-skill-candidate.js");
const skillRegistration = read("quote-skill-registration.js");
const templateRegistration = read("quote-template-registration.js");
const registrationSession = read("quote-registration-session.js");
const skillUi = read("quote-skill-ui.js");
const intake = read("file-intake.js");
const easy = read("easy-mode.js");
const worker = read("_worker.js");
const account = read("padiem-account.js");
const accountCss = read("padiem-account.css");

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
  'src="quote-skill.js"',
  'src="quote-skill-store.js"',
  'src="quote-skill-candidate.js"',
  'src="quote-skill-registration.js"',
  'src="quote-template-registration.js"',
  'src="quote-registration-session.js"',
  'src="quote-skill-ui.js"',
  'src="file-intake.js"',
  'src="app.js"',
  'src="easy-mode.js"',
  'src="padiem-account.js"',
  'href="padiem-account.css"',
  'id="padiemAccountButton"',
  'id="padiemAccountPanel"',
  'id="padiemSavedSkillSelect"',
  'id="easyComposer"',
  'id="easySend"',
  'id="padiemQuoteModelSelect"',
  'id="padiemAuthDialog"',
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
  'id="pvLogo"',
  'id="pvStamp"',
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
  'id="skillSection"',
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

/* PADIEM_ACCOUNT_BRIDGE_CONTRACT — 공개 견적 UI는 유지하되 계정 authority만 Padiem을 재사용 */
check(!/(Padiem|파디엠|padiem)/.test(app + core + extraction + history + template + templateStore + templateRenderer + templateSelection + templateUi + candidate + cloner + skill + skillStore + skillCandidate + skillRegistration + skillUi + intake + easy),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: quote domain logic stays product-neutral");
check(!html.includes("B66 DEMO"), "PADIEM_ACCOUNT_BRIDGE_CONTRACT: no internal demo label");
check(account.includes("function declaredAssetRefs(") &&
      account.includes("function readPrivateAsset(") &&
      account.includes('API + "/b66/assets/" + encodeURIComponent(assetId)') &&
      account.includes("MAX_PRIVATE_ASSET_BYTES = 256 * 1024"),
  "PRIVATE_ACCOUNT_ASSET_LOAD=PASS: standalone account bridge resolves only bounded private quote assets");
check(app.includes("serverSlotSources") &&
      app.includes("const cgiProfile = ownerCgi ? activeSkillProfile() : null;") &&
      app.includes("slotSources: serverSkillActive ? skillUiState.serverSlotSources : {}"),
  "PRIVATE_ACCOUNT_ASSET_RENDER=PASS: only active server-assigned Skill gets transient private assets");
check(templateStore.includes('return "private_asset_requires_account_skill"'),
  "PRIVATE_BROWSER_TEMPLATE_ASSET_AUTHORITY=0: browser-local template store stays fail-closed");

check(worker.includes("B66_ASSET_ROW") &&
      worker.includes('const assetPrefix = "/api/padiem/b66/assets/"') &&
      worker.includes('return "/api/b66/assets/" + id;'),
  "PRIVATE_QUOTE_ASSET_BRIDGE=PASS: Quick Quote proxies only bounded asset ids");

check(html.includes('id="settingsPanel"') &&
      html.includes("작성 중 견적은 이 브라우저에 저장"),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: truthful local draft persistence lives in personal settings");
check(html.includes(">로그인</button>") && html.includes('id="googleSigninButton"') &&
      html.includes("Google로 로그인") &&
      !html.includes("Padiem") && !html.includes("파디엠") &&
      !account.includes("Padiem 계정") && !account.includes("Padiem 로그인"),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: standalone surface keeps neutral login branding");
check(html.includes('id="padiemLoginForm" hidden') &&
      html.includes('id="padiemAuthDivider" hidden') &&
      html.includes('id="padiemLoginIdentifier"') &&
      html.includes('id="padiemLoginPassword"') &&
      html.includes('id="padiemLoginSubmit"') &&
      account.includes('methods.password === true') &&
      account.includes('form.hidden = !state.methods.password') &&
      account.includes('divider.hidden = !state.methods.password') &&
      account.includes('submit.disabled = !state.methods.password') &&
      account.includes('if (!passwordLoginAvailable())') &&
      account.includes('api("/auth/password/login"') &&
      account.includes('loginForm.addEventListener("submit", passwordSignIn)'),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: standalone password login is status-gated and reuses the shared route");
check(html.includes('id="padiemLoginForm" hidden') &&
      html.includes('id="padiemAuthDivider" hidden') &&
      accountCss.includes(".padiem-auth-form[hidden]") &&
      accountCss.includes(".padiem-auth-divider[hidden]") &&
      /\[hidden\][^{]*\{[^}]*display:\s*none/.test(accountCss),
  "PADIEM_PASSWORD_METHOD_GATE: password form ships hidden and the class display rule cannot re-expose it");
check(account.includes('result = await api("/auth/status")') &&
      account.includes("applyAuthMethods(result.response.ok ? result.data : null)") &&
      account.includes("applyAuthMethods(null)"),
  "PADIEM_PASSWORD_METHOD_GATE: bounded boolean method flag is sourced only from canonical /auth/status");
check(!/state\.user\s*\?\s*\{\s*password/.test(account) &&
      !/password\s*:\s*state\.(user|authenticated)/.test(account) &&
      !/methods\.password\s*\)?\s*===?\s*state\./.test(account),
  "PADIEM_PASSWORD_METHOD_GATE: no non-canonical derivation of the password method flag");
check(!account.includes("submit.disabled = false") &&
      account.includes("submit.disabled = !passwordLoginAvailable()"),
  "PADIEM_PASSWORD_METHOD_GATE: submit button is never re-enabled outside the canonical gate");
check(account.includes("/api/padiem/auth/google/start") &&
      worker.includes('"/api/padiem/auth/google/start"') &&
      worker.includes('"/api/padiem/auth/google/callback"') &&
      worker.includes('upstream.headers.get("location")') &&
      worker.includes('headers.set("X-B66-Origin", url.origin)'),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: google oauth is proxied through the B66 worker");
check(!html.includes('class="badge"') && !html.includes("Padiem 로그인") &&
      !account.includes("Padiem 로그인") && account.includes('button.textContent = "로그인"'),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: topbar carries no stale badge or vendor-branded login label");
check(worker.includes('PADIEM_CHAT_ORIGIN = "https://chat.padiem.net"'),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: canonical Padiem upstream fixed");
check(worker.includes('bridgeMutationOriginAllowed(request, url)') &&
      worker.includes('request.headers.get("origin") === url.origin') &&
      worker.includes('jsonError("padiem_origin_rejected", 403)'),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: cookie-authenticated mutations fail closed on cross-origin callers");
check(worker.includes('headers.set("Origin", PADIEM_CHAT_ORIGIN)'),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: guarded mutations stamp the canonical Padiem Chat Origin upstream");
[
  "/api/padiem/auth/status",
  "/api/padiem/auth/password/login",
  "/api/padiem/auth/password/register",
  "/api/padiem/auth/logout",
  "/api/padiem/b66/quote/interpret",
  "/api/padiem/b66/saved-skills"
].forEach((route) => check(worker.includes(route),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: bounded route " + route));
check(worker.includes("padiem_route_not_allowed") && worker.includes("SAVED_SKILL_ROW"),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: arbitrary upstream path denied");
check(worker.includes('request.headers.get("cookie")') &&
      !worker.includes('request.headers.get("authorization")'),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: opaque session forwarded without browser Authorization authority");
check(worker.includes("PADIEM_CHAT_SERVICE") && worker.includes("else {\n      upstream = await fetch(target, init);"),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: optional same-account service binding with HTTPS fallback");
check(!account.includes("localStorage") && !account.includes("sessionStorage"),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: server-assigned skill is memory-only cache");
check(account.includes("{ companyProfile: profile }") &&
      account.includes("{ companyProfile: state.companyProfile }") &&
      account.includes("bridge.setServerSkill(skill, slotSources, savedSkillId)") &&
      account.includes("row.saved_skill_id !== savedSkillId") &&
      account.includes("B66QuoteRuntimeBridge"),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: server skill + authorized private assets feed canonical browser QuoteCore/renderer path");
check(app.includes("function setServerSkill(skill, slotSources, savedSkillId)") &&
      app.includes("serverSavedSkillId") &&
      app.includes("function clearServerSkill()") &&
      app.includes("serverSlotSources"),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: app exposes non-persistent server skill + transient private asset seam");
check(accountCss.includes(".padiem-account-panel") && accountCss.includes("@media print"),
  "PADIEM_ACCOUNT_BRIDGE_CONTRACT: account UI has bounded screen/print styling");
new vm.Script(account, { filename: "padiem-account.js" });

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
check(extraction.includes("normalizeDetailGroups(") &&
      extraction.includes('"summaryItemId": "extracted-item-"') === false &&
      extraction.includes('"extracted-item-" + group.summaryIndex'),
  "DETAIL_GROUP_EXTRACTION_CONTRACT: summaryIndex is mapped to canonical summary ids without model-owned ids");

/* EASY_MODE_CONTRACT — 기존 직접입력 화면 앞에 deterministic chat UX */
check(html.includes('id="easyModeButton"') && html.includes('id="directModeButton"') &&
      html.includes(">채팅</button>") && html.includes("직접 입력"),
  "EASY_MODE_CONTRACT: top-level chat/direct switch");
check(html.includes("질문받으며 새로 만들기") && html.includes("내용을 한번에 말하기"),
  "EASY_MODE_CONTRACT: easy entry choices");
check(easy.includes('App.createFreshDraft("guided")') &&
      app.includes('fresh.meta.source = source || "manual"'),
  "EASY_MODE_CONTRACT: deterministic guided draft uses shared fresh-draft allocator");
check(easy.includes("function processGuidedInput("),
  "EASY_MODE_CONTRACT: guided state machine");
check(easy.includes("Core.computeDraftTotals(guided.draft)") &&
      easy.includes("if (current.calculationPolicy) fresh.calculationPolicy = clone(current.calculationPolicy);"),
  "EASY_MODE_CONTRACT: guided summary uses draft-level QuoteCore detail/family authority");
check(css.includes(".easy-chip {") && css.includes("min-height: 44px;"),
  "EASY_MODE_CONTRACT: quick chips meet 44px touch target");
check(!easy.includes("fetch(") && !easy.includes("XMLHttpRequest") &&
      !intake.includes("fetch(") && !intake.includes("XMLHttpRequest"),
  "EASY_MODE_CONTRACT: no network/model call in Easy/file intake mode");
check(!easy.includes("아직 자동 해석 모델은 연결 전") &&
      easy.includes("CGI 기본 견적서 양식과 회사 정보가 자동으로 적용됩니다"),
  "EASY_MODE_CONTRACT: free-form runs the live assigned-skill runtime (placeholder removed)");
check(easy.includes("자동 분석 서버는 아직 활성화 전") &&
      easy.includes("이 파일은 외부로 전송되지 않습니다."),
  "EASY_MODE_CONTRACT: selected file is truthful about non-live analysis");
check(app.includes("window.B66QuoteAppBridge"),
  "EASY_MODE_CONTRACT: reuses existing QuoteDraft renderer");
check(html.includes('id="directView"'),
  "EASY_MODE_CONTRACT: direct mode preserved");
check(easy.includes("function startGuided(referenceText, options)") &&
      easy.includes("참고용으로 그대로 남겨둘게요"),
  "FREE_TEXT_CONTINUITY_CONTRACT: guided reference text stays visible and non-authoritative");
check(easy.includes("inputHandler = (text) => startHomeInterpretation(text);") &&
      easy.includes("보내면 CGI 기본 견적서로 바로 만들어 드립니다") &&
      !easy.includes("문장을 알아듣는 기능은 준비 중이라"),
  "EASY_MODE_CONTRACT: home composer submit runs the real free-form runtime");
check(easy.includes("QuoteDraft에 자동 반영하지 않습니다."),
  "FREE_TEXT_CONTINUITY_CONTRACT: preserved reference is explicitly non-authoritative");
check(easy.includes('const PRODUCT_HISTORY_KEY = "b66View"') &&
      easy.includes('"pushState"') &&
      easy.includes('"replaceState"') &&
      easy.includes('window.history.back') &&
      easy.includes('window.addEventListener("popstate"') &&
      easy.includes('restoreProductState(view)'),
  "B66_BROWSER_HISTORY_CONTRACT: product states are browser-history aware");
check(easy.includes('recordProductState(easy ? lastEasyView : "direct")') &&
      easy.includes('recordProductState("guided")') &&
      easy.includes('recordProductState("file")') &&
      easy.includes('recordProductState("free-form")') &&
      easy.includes('recordProductState("recent")'),
  "B66_BROWSER_HISTORY_CONTRACT: direct/guided/file/free-form/recent share the Quote Home boundary");

/* B66_MVP_RUNTIME_CONTRACT (#3478) — Guided/Free-form 이 하나의 runtime authority 로 수렴한다 */
check(worker.includes('"/api/padiem/b66/company-profile"') &&
      worker.includes('"/api/b66/company-profile"') &&
      worker.includes('intake_disabled'),
  "B66_MVP_RUNTIME_CONTRACT: company-profile GET bridge exists and intake relay stays fail-closed");
check(easy.includes("window.B66QuoteRuntimeBridge") &&
      easy.includes("runPrimaryInterpretation") &&
      easy.includes("buildFromFacts") &&
      easy.includes('{ label: "견적서 만들기", action: finishGuidedWithRuntime }') &&
      easy.includes('label: "견적서 확인하기"') &&
      easy.includes('setWorkspaceMode("direct")'),
  "B66_MVP_RUNTIME_CONTRACT: primary input converges on one runtime; direct entry is an explicit review action");
check(account.includes("state.companyProfileLoaded") &&
      account.includes('"/b66/company-profile"') &&
      account.includes("{ companyProfile: profile }") &&
      account.includes("{ companyProfile: state.companyProfile }") &&
      account.includes("B66QuoteRuntimeBridge"),
  "B66_MVP_RUNTIME_CONTRACT: standalone runtime builds drafts with the authenticated CompanyProfile");
check(account.includes("runtimeReadiness()") &&
      account.includes("notReadyCode(readiness)") &&
      account.includes("interpretRequest"),
  "B66_MVP_RUNTIME_CONTRACT: primary actions are gated on auth/skill/profile readiness without demo fallback");

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
check(history.includes("Core.computeDraftTotals(entry.draft)") &&
      history.includes("if (source.calculationPolicy) fresh.calculationPolicy = clone(source.calculationPolicy);") &&
      history.includes("if (Array.isArray(source.detailGroups) && source.detailGroups.length)"),
  "RECENT_HISTORY_CONTRACT: displayed/copied totals preserve QuoteCore family/detail authority");
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
check(app.includes("Core.createProductionDraft") && app.includes("Core.createDefaultDraft"),
  "QUOTEDRAFT_SCHEMA_CONTRACT: app keeps the demo fixture only for legacy-state detection while startup/reset use the Production authority");
check(!app.includes("draft = Core.createDefaultDraft();") && app.includes("draft = Core.createProductionDraft();"),
  "QUOTEDRAFT_SCHEMA_CONTRACT: app never assigns the demo fixture as a live draft");

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
check(core.includes("if (current.calculationPolicy) next.calculationPolicy = current.calculationPolicy;"),
  "NEW_QUOTE_SAFETY_CONTRACT: reviewed family calculation policy survives new quote normalization");

/* UNKNOWN_VAT_REVIEW_CONTRACT — 미확정 세금은 확정 합계처럼 보이지 않음 */
check(html.includes('id="taxReviewNote"') && html.includes('id="taxRow"'),
  "UNKNOWN_VAT_REVIEW_CONTRACT: direct review surface exists");
check(css.includes(".tax-row.tax-review-required"),
  "UNKNOWN_VAT_REVIEW_CONTRACT: direct review highlight exists");
check(easy.includes('"품목 합계(세금 확인 전): "') &&
      easy.includes("최종 합계는 부가세 방식을 선택한 뒤 확정됩니다."),
  "UNKNOWN_VAT_REVIEW_CONTRACT: unknown VAT summary is explicitly provisional");
check(easy.includes("requireTaxReview: taxUnknown") &&
      easy.includes("App.focusTaxReview()"),
  "UNKNOWN_VAT_REVIEW_CONTRACT: review stays required and is focused when the user opens the result");
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
      app.includes("removePrivateItem(TAX_REVIEW_STORAGE_KEY)"),
  "VAT_REVIEW_PERSISTENCE_CONTRACT: tax review state is independently removable");

/* DRAFT_SAVE_CONTRACT — draft 자동 저장 계약 (#3480: owner 게이트 경유) */
check(app.includes("writePrivateItem(Core.DRAFT_STORAGE_KEY, JSON.stringify(draft))"),
  "DRAFT_SAVE_CONTRACT: autosave whole draft");
check(app.includes("saveDraft();"), "DRAFT_SAVE_CONTRACT: render triggers save");

/* DRAFT_RESTORE_CONTRACT — 복원 + 손상 fallback 계약 */
check(/Core\.normalizeDraft\(JSON\.parse\(readPrivateItem\(Core\.DRAFT_STORAGE_KEY\)/.test(app),
  "DRAFT_RESTORE_CONTRACT: restore via normalizeDraft behind the owner gate");
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
check(css.includes("width: var(--quote-page-width, 210mm)") &&
      css.includes("min-height: var(--quote-page-height, 297mm)") &&
      css.includes("padding: var(--quote-page-margin, 10mm)"),
  "SCREEN_PDF_WYSIWYG_GEOMETRY: screen paper uses template page dimensions and margin");
check(css.includes(".quote-paper { width: auto; min-height: 0; margin: 0; padding: 0; }"),
  "SCREEN_PDF_WYSIWYG_GEOMETRY: print transfers the same margin to @page");
check(css.includes("@page { size: A4"), "PRINT_LAYOUT_CONTRACT: A4 page rule");
check(css.includes("@media print"), "PRINT_LAYOUT_CONTRACT: print media");
check(css.includes(".topbar, .workspace-modebar, .easy-view, .modebar, .future-note, .panel, .preview-toolbar, .toast { display: none !important; }"),
  "PRINT_LAYOUT_CONTRACT: all non-print Easy/Direct UI removed from layout");
check(css.includes(".direct-view[hidden] { display: block !important; }"),
  "PRINT_LAYOUT_CONTRACT: hidden Direct view is restored for printing from Easy Mode");
check(css.includes(".grid { display: block; }"), "PRINT_LAYOUT_CONTRACT: paper in normal flow");
check(css.includes('.quote-paper[data-layout-variant="formal-grid-v1"] .demo-mark { display: block; }'),
  "PRINT_LAYOUT_CONTRACT: formal printed mark remains visible without exposing the built-in demo mark");
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
check(templateRenderer.includes("provisional ? content.totals.provisional.subtotalLabel : supplyLabel") &&
      templateRenderer.includes("var supplyLabel = content.totals.supplyLabel") &&
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
check(html.includes('id="settingsButton"') && html.includes('id="settingsClose"') &&
      html.includes('class="settings-reset" id="resetLocalData"') &&
      app.includes('$("settingsButton")') && app.includes('$("settingsClose")') &&
      css.includes(".settings-panel {"),
  "BETA_POLISH_CONTRACT: personal settings owns the destructive reset");
check(app.includes("Core.DRAFT_STORAGE_KEY") &&
      app.includes("Core.SENDER_STORAGE_KEY") &&
      app.includes("History.HISTORY_STORAGE_KEY") &&
      app.includes("History.SEQUENCE_STORAGE_KEY") &&
      app.includes("TAX_REVIEW_STORAGE_KEY"),
  "BETA_POLISH_CONTRACT: reset enumerates B66-owned keys including VAT review state");
check(app.includes("AccountScope.removePrivateKeys(storage, PRIVATE_STORAGE_KEYS)") &&
      !app.includes("localStorage.clear("),
  "BETA_POLISH_CONTRACT: reset removes only enumerated B66-owned keys, never the whole origin");
check(account.includes("settingsButton.hidden = true") &&
      account.includes("settingsButton.hidden = false"),
  "BETA_POLISH_CONTRACT: personal settings appears only after sign-in");
check(easy.includes('addEventListener("b66:auth-changed"') &&
      account.includes('b66:auth-changed", { detail: { authenticated: true } }') &&
      easy.includes("로그인하면 견적을 이어서 진행할 수 있습니다.") &&
      easy.includes("이전에 작성하던 견적이 있습니다"),
  "EASY_MODE_CONTRACT: resume hint follows sign-in state");
check(easy.includes('"b66:local-data-reset"') &&
      easy.includes('fileInput.value = ""'),
  "BETA_POLISH_CONTRACT: reset clears ephemeral selected-file state");

/* 결정론적 계산 잔여 계약 (원본에서 승계) */
check(core.includes("Math.round(qty * price)"), "deterministic item amount");
check(!app.includes("window.print()") && app.includes("bridge.downloadPdf(model, previewModel)") &&
      html.includes('src="quote-browser-pdf.js"') &&
      account.includes("browserPdf.makePdf(renderModel, previewModel)"),
  "certified PDF download replaces the final browser print action");
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
check(!easy.includes("문장을 알아듣는 기능은 준비 중이라") &&
      !easy.includes("아직 자동 해석 모델은 연결 전") &&
      easy.includes("CGI 기본 견적서로 작성하고 있습니다") &&
      easy.includes("window.B66QuoteRuntimeBridge"),
  "CHAT_AI_LIVE=NO: easy mode performs no local interpretation; it routes to the authenticated runtime");
check(easy.includes('addEventListener("b66:open-easy-chat"') &&
      app.includes('new CustomEvent("b66:open-easy-chat")') &&
      html.includes('data-mode="chat"'),
  "EASY_MODE_CONTRACT: direct-modebar chat button opens the easy workspace");

/* EMAIL_SEND_LIVE=NO */
check(app.includes("이메일 전송은 다음 단계에서"), "EMAIL_SEND_LIVE=NO: email is future");
check(html.includes("이메일 보내기 · 다음 단계"), "EMAIL_SEND_LIVE=NO: future label");

/* The source-only template and Skill contracts are now independently run
   by tests/static-template-contract.test.cjs and
   tests/static-skill-contract.test.cjs through the canonical B66 runner. */

/* Password method's real VM/DOM behavioral regression lives in the
   auto-discovered tests/auth-password-method-gate.test.cjs suite. */

/* SERVER_HISTORY_CONTRACT (#3405 Slice B) — signed-in server quote-history authority.
   Structural wiring only. Behavioral contracts (DELETE_CONFIRM,
   NO_OPTIMISTIC_DELETE, COPY_AS_NEW, QUOTECORE_RECALCULATION,
   NO_SILENT_LOCAL_FALLBACK, FOREIGN_ACCOUNT_ACCESS) are owned by
   tests/history-server-behavior.test.cjs, which drives the real app.js /
   easy-mode.js and clicks the real buttons; this file must not print them. */
check(require("fs").existsSync(path.join(__dirname, "..", "quote-history-server.js")),
  "SERVER_HISTORY_CONTRACT: quote-history-server.js ships in the reference app");
check(html.includes('src="quote-history-server.js"'),
  "SERVER_HISTORY_CONTRACT: index.html includes the server history client");
check(worker.includes("/api/padiem/b66/quotes"),
  "SERVER_HISTORY_CONTRACT: B66 Pages worker proxies the canonical quote-history API");
check(worker.includes("B66_QUOTE_ROW") && worker.includes('"/api/padiem/b66/quotes/"'),
  "SERVER_HISTORY_CONTRACT: worker bounds quote-history row ids before upstream");
check(app.includes("ServerHistory.draftToHistorySnapshot") && app.includes("ServerHistory.historySnapshotToDraft"),
  "SERVER_HISTORY_CONTRACT: app converts drafts through the server snapshot boundary");
check(app.includes("serverHistoryActive()") && app.includes("serverHistorySignedIn"),
  "SERVER_HISTORY_CONTRACT: server authority is active only while signed in");
check(app.includes('authority: "server"') && app.includes("history_read_failed") && app.includes("history_save_failed"),
  "SERVER_HISTORY_CONTRACT: server errors stay on the server authority path");
check(easy.includes("readRecentHistory()") && easy.includes("App.listRecentQuotes"),
  "SERVER_HISTORY_CONTRACT: Easy history surface reads through the server-aware bridge");
check(easy.includes("renderHistoryPending()") && easy.includes("renderHistoryError"),
  "SERVER_HISTORY_CONTRACT: history renderer distinguishes pending and bounded-error states");
check(!app.includes("localStorage.setItem(" + JSON.stringify("quoteBeta.history.v1")) ||
      app.includes('authority: "server"'),
  "SERVER_HISTORY_CONTRACT: server success may update the local cache, but failure does not silently use it as authority");
check(!app.includes("History.copyAsNew(entry, { now: new Date() })") ||
      app.includes("ServerHistory.draftToHistorySnapshot"),
  "SERVER_HISTORY_CONTRACT: copy/new authority stays QuoteCore + server snapshot, not persisted totals");
/* the behavioral probe must not regress into a bridge stub */
const behaviorProbe = fs.readFileSync(path.join(__dirname, "history-server-behavior.test.cjs"), "utf8");
check(!/B66QuoteAppBridge:\s*\{/.test(behaviorProbe),
  "SERVER_HISTORY_CONTRACT: the behavioral probe never substitutes its own B66QuoteAppBridge stub");
check(/INDEX_HTML[\s\S]{0,400}SCRIPT_TAGS/.test(behaviorProbe) &&
      /recentQuoteStarter/.test(behaviorProbe),
  "SERVER_HISTORY_CONTRACT: the behavioral probe boots the real scripts and opens the real recent view");
check(!/\|\|\s*true\b/.test(behaviorProbe) && !/\|\|\s*===\s*/.test(behaviorProbe) &&
      !/!==[^;()]*\|\|\s*===/.test(behaviorProbe),
  "SERVER_HISTORY_CONTRACT: the behavioral probe has no tautological assertion");

/* WORK 7: the behavioral probes must actually run in CI, not merely exist */
const workflowPath = path.join(__dirname, "..", "..", "..", ".github", "workflows", "b66-neutral-pages-beta.yml");
const workflowText = fs.readFileSync(workflowPath, "utf8");
const TestRunner = require("./run-b66-contracts.cjs");
const discovered = TestRunner.discoverTestFiles();
check(discovered.includes("history-behavior.test.cjs"),
  "CI_WIRING: canonical runner discovers browser-history behavioral probe");
check(discovered.includes("history-server-behavior.test.cjs"),
  "CI_WIRING: canonical runner discovers server-history behavioral probe");
check(discovered.includes("auth-password-method-gate.test.cjs"),
  "CI_WIRING: canonical runner discovers the real password-gate behavioral probe");
check(discovered.includes("static-template-contract.test.cjs"),
  "CI_WIRING: canonical runner includes complete template structural contracts");
check(discovered.includes("static-skill-contract.test.cjs"),
  "CI_WIRING: canonical runner includes complete Skill structural contracts");
check(workflowText.includes("node tests/run-b66-contracts.cjs --tests"),
  "CI_WIRING: b66-neutral-pages-beta.yml executes all auto-discovered B66 tests");

console.log("SERVER_HISTORY_CONTRACT=PASS");
console.log("SERVER_HISTORY_STRUCTURAL_CONTRACT=PASS");
console.log("BEHAVIOR_CONTRACTS_OWNED_BY=tests/history-server-behavior.test.cjs");
console.log("CI_WIRING=PASS");
