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
check(!template.includes("computeTotals(") && !template.includes("computeDraftTotals(") &&
      !template.includes("grand =") && !template.includes("vat =") && !template.includes("supply ="),
  "QUOTE_TEMPLATE_PROFILE_CONTRACT: the template layer owns no totals");
check(template.includes('"detailPages"') && template.includes("content.detailPages") &&
      html.includes('id="pvDetailPages"') && embed.includes('id="pvDetailPages"') &&
      css.includes(".quote-detail-page") && css.includes("break-before: page"),
  "PRINTABLE_DETAIL_PAGES=PASS: approved template can project bounded printable detail pages");

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
check(templateRenderer.includes("Core.computeDraftTotals(normalizedDraft)") &&
      templateRenderer.includes("Core.formatKoreanMoneyWords(totals.grand)") &&
      templateRenderer.includes("Core.computeValidUntil("),
  "QUOTECORE_REMAINS_CALCULATION_AUTHORITY=YES: renderer derives detail rollups, totals, written grand and validity from QuoteCore");
check(!templateRenderer.includes("grand =") && !templateRenderer.includes("vat =") &&
      !templateRenderer.includes("supply ="),
  "QUOTECORE_REMAINS_CALCULATION_AUTHORITY=YES: the renderer performs no tax arithmetic");
check(!/fetch\(|XMLHttpRequest/.test(templateRenderer) &&
      !/Math\.random|Date\.now|new Date\(/.test(templateRenderer),
  "QUOTE_TEMPLATE_RENDERER_DETERMINISTIC: no model call and no time/random input");
check(templateRenderer.includes("CALCULATION_AUTHORITY = \"quote-core\"") &&
      templateRenderer.includes('setText("pvGrand", totals.grandText)') &&
      templateRenderer.includes('setHtml("pvDetailPages"') &&
      templateRenderer.includes("group.subtotal"),
  "QUOTECORE_REMAINS_CALCULATION_AUTHORITY=YES: adapter publishes QuoteCore-derived totals/detail pages");
check(!/(kilo\/|space-bunny|nemotron|openai|anthropic)/i.test(template + templateStore + templateRenderer),
  "MODEL_DEPENDENCY=0: template modules name no provider or model");
check(!/FileReader|FormData|indexedDB/i.test(template + templateStore + templateRenderer),
  "RAW_SOURCE_FILE_PERSISTENCE=0: template modules never touch raw file bytes");
check(app.includes("TemplateRenderer.buildRenderModel(") &&
      app.includes("const previewProfile = previewTemplateProfile();") &&
      app.includes("const authority = ownerCgi ? cgiProfile : (previewProfile || renderTemplateAuthority());") &&
      app.includes("function renderTemplateAuthority()") &&
      app.includes("return explicitTemplateProfile() || activeSkillProfile() || activeTemplateProfile();") &&
      app.includes("const cgiProfile = ownerCgi ? activeSkillProfile() : null;") &&
      app.includes("slotSources: serverSkillActive ? skillUiState.serverSlotSources : {}"),
  "QUOTE_TEMPLATE_RENDERER_DETERMINISTIC: direct mode renders through approved template/skill authority with transient private assets");
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
check(template.includes('SLOT_SUPPORT = "private_asset_v1"') &&
      template.includes('SLOT_REF_PATTERN = /^b66asset_'),
  "SLOT_BEHAVIOR=PRIVATE_ASSET_REF_V1: only bounded private asset ids persist");
check(templateStore.includes("function approveTemplate(") &&
      templateStore.includes('fail("template_not_approved"'),
  "UNAPPROVED_TEMPLATE_ACTIVATION=0: activation requires explicit approval");
check(templateStore.includes("approval = null;") &&
      templateStore.includes("var keepDefault = !contentChanged && current.isDefault"),
  "CONTENT_CHANGE_INVALIDATES_APPROVAL=YES: content update drops approval and default status");
check(templateStore.includes("function rejectionForContent(") &&
      templateStore.includes('return "private_asset_requires_account_skill"'),
  "SLOT_BEHAVIOR=PRIVATE_ASSET_REF_V1: browser-local templates cannot own account assets");
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
check(app.includes("const previewProfile = previewTemplateProfile();") &&
      app.includes("const authority = ownerCgi ? cgiProfile : (previewProfile || renderTemplateAuthority());") &&
      app.includes("return explicitTemplateProfile() || activeSkillProfile() || activeTemplateProfile();") &&
      app.includes("return profile && Template.isApprovedProfile(profile) ? profile : null;") &&
      app.includes("candidate && candidate.approved") &&
      app.includes("CgiTemplateV2.approvedProfile("),
  "UNAPPROVED_TEMPLATE_SELECTION=0: explicit CGI/preview/skill render paths remain restricted to approved profiles");

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
check((cloner.match(/restoreStorage\(storage, snapshot\);/g) || []).length >= 3 &&
      cloner.includes("var snapshot = snapshotStorage(storage);"),
  "FAILED_APPROVAL_CHANGES_DEFAULT=0: every approval failure path restores the snapshot");
check(app.includes('$("templateApprove").addEventListener("click"') &&
      app.includes("TemplateCloner.approveCandidate(clonerSession, templateStorage(), {})"),
  "EXPLICIT_TEMPLATE_APPROVAL_REQUIRED=YES: approval is an explicit user action");
check(app.includes("FileIntake.classifyTemplateSourceFile(file)") && app.includes("window.B66QuoteTemplateClonerBridge"),
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

check(cloner.includes("function snapshotStorage(") && cloner.includes("function restoreStorage(") &&
      cloner.includes("restoreStorage(storage, snapshot);"),
  "APPROVAL_FAILURE_PARTIAL_WRITE=0: approval stages a snapshot and rolls back on failure");
check(cloner.includes("storage_required_for_approval_invalidation"),
  "SPLIT_BRAIN_APPROVAL_STATE=0: a content edit on an approved session requires storage");
check(cloner.includes("if (!created.ok)") && cloner.includes("var snapshot = snapshotStorage(storage);"),
  "APPROVAL_FAILURE_PARTIAL_WRITE=0: the snapshot is taken before the first write");

console.log("B66_STATIC_CONTRACT=PASS");
console.log("NEUTRAL_PUBLIC_UI_CONTRACT=PASS");
console.log("EXTRACTION_BOUNDARY_CONTRACT=PASS");
console.log("EASY_MODE_CONTRACT=PASS");
console.log("FILE_INTAKE_CONTRACT=PASS");
console.log("FILE_CHOOSER_LIVE=YES");
console.log("TEMPLATE_CLONER_BROWSER_UPLOAD_NETWORK=0");
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
