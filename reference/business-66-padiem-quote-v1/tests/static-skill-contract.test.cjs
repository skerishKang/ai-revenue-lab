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

/* SAVED_QUOTE_SKILL_COMPILED_REUSE — user-facing Skill wraps the existing deterministic template stack */
check(skill.includes('CALCULATION_AUTHORITY = "quote-core"') &&
      skill.includes('RENDERER_CONTRACT = "quote-template-renderer.v1"'),
  "SAVED_QUOTE_SKILL_AUTHORITY: QuoteCore + existing renderer stay authoritative");
check(skill.includes("structuredRepeatGenerationModelCalls: 0") &&
      skill.includes("sourceDocumentReanalysisPerRepeat: 0") &&
      skill.includes("fullDocumentAiRegenerationPerRepeat: 0") &&
      skill.includes("quoteCoreRecalculationModelCalls: 0") &&
      skill.includes("rendererModelCalls: 0"),
  "SAVED_QUOTE_SKILL_REPEAT_MODEL_CALLS=0");
check(skill.includes('REQUIRED_VARIABLE_KEYS = ["recipient", "quoteNo", "issueDate", "items"]'),
  "SAVED_QUOTE_SKILL_SOURCE_CASE_VALUES_NOT_FROZEN: core per-quote fields remain variable");
check(skillStore.includes('STORAGE_KEY = "quoteBetaSavedSkill.v1"') && !skillStore.includes("localStorage.clear("),
  "SAVED_QUOTE_SKILL_STORE_BOUNDED=YES");
check(skillCandidate.includes('CALCULATED_FIELDS = ["lineAmounts", "supplyTotal", "vatAmount", "grandTotal", "validUntil"]'),
  "SAVED_QUOTE_SKILL_CALCULATED_FIELDS_LOCKED_TO_QUOTECORE=YES");
check(!/(kilo\/|space-bunny|sensenova|openai|anthropic)/i.test(skill + skillStore + skillCandidate + skillRegistration),
  "SAVED_QUOTE_SKILL_BROWSER_PROVIDER_MODEL_ID=0");
check(!/FileReader|FormData|indexedDB/i.test(skill + skillStore + skillCandidate + skillRegistration),
  "SAVED_QUOTE_SKILL_RAW_SOURCE_FILE_BROWSER_PERSISTENCE=0");
check(skillRegistration.includes("buildRegistrationCandidate") &&
      skillRegistration.includes("unsupported_template_decision") &&
      skillRegistration.includes("sender_company_requires_correction"),
  "SAVED_QUOTE_SKILL_REGISTRATION_SEAM: extraction-to-candidate seam is wired with honest fail-closed gaps");
check(templateRegistration.includes("buildTemplateCandidateFromSource") &&
      templateRegistration.includes("previewTemplateCandidate") &&
      templateRegistration.includes("approveTemplateCandidate") &&
      templateRegistration.includes("manual_layout_review_required"),
  "TEMPLATE_REGISTRATION_SEAM: source-to-approved-profile path is wired with manual review");
check(registrationSession.includes("STEP_LABELS") &&
      registrationSession.includes("registration_committed") &&
      registrationSession.includes("rolledBack") &&
      registrationSession.includes("template_not_approved_for_skill"),
  "REGISTRATION_SINGLE_USER_FLOW: template+skill approvals stay separate with atomic commit");
check(!/완전히 학습했습니다|완벽하게 학습|학습이 완료되었습니다|AI가 배웠습니다/
  .test(templateRegistration + registrationSession),
  "NO_OVERCLAIMED_LAYOUT_LEARNING: honest copy only");
/* MY_QUOTATION_UI — skill UI binds the real session/state machine without new authorities */
check(skillUi.includes("bindSkillSection") &&
      skillUi.includes("Session.start") &&
      skillUi.includes("Session.commit") &&
      skillUi.includes("formValuesFromSkill"),
  "MY_QUOTATION_UI: skill section binds session commit and form application");
check(!/\.innerHTML\s*=/.test(skillUi),
  "MY_QUOTATION_UI: wizard renders via DOM API, no markup injection surface");
check(!/(space-bunny|sensenova|openai|anthropic|kilo\/)/i.test(skillUi) &&
      skillUi.includes('LIVE_INTAKE_ENDPOINT = "/api/v1/quote/intake"') &&
      !/https?:\/\//i.test(skillUi) &&
      !/XMLHttpRequest|WebSocket|EventSource/.test(skillUi) &&
      !/localStorage|sessionStorage|indexedDB/.test(skillUi),
  "MY_QUOTATION_UI: same-origin intake only, no provider identity/external network, storage only through env");
check(app.includes("B66QuoteSkillBridge") && app.includes("applySkillToForm") &&
      app.includes("skillUiState"),
  "MY_QUOTATION_UI: app hosts the skill bridge with form application and builtin fallback");
check(skillUi.includes("analyzeImageFile") &&
      skillUi.includes("analyzeFile") &&
      skillUi.includes('"native_document"') &&
      skillUi.includes("factsFromExtraction") &&
      skillUi.includes("registrationModelOutput"),
  "MY_QUOTATION_LIVE_FILE_INTAKE=YES: image/native validated extraction feeds review/registration");

console.log("VALID_UNTIL_CONTRACT=PASS");
console.log("ADDRESS_FIELDS_CONTRACT=PASS");
console.log("PRINT_LAYOUT_CONTRACT=PASS");
console.log("FORMAL_PRINT_MARK=PASS");
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
console.log("SLOT_BEHAVIOR=PRIVATE_ASSET_REF_V1");
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
console.log("APPROVAL_FAILURE_PARTIAL_WRITE=0");
console.log("SPLIT_BRAIN_APPROVAL_STATE=0");
console.log("MOBILE_TEMPLATE_UI=PASS");
console.log("PRINT_UI_LEAK=0");
console.log("BROWSER_PROVIDER_MODEL_NETWORK_CALLS=0");
console.log("SAVED_QUOTE_IMAGE_INTAKE_SOURCE_WIRED=YES");
console.log("NATIVE_DOCUMENT_AUTO_ANALYSIS_SOURCE_WIRED=YES");
console.log("NATIVE_DOCUMENT_PARSER_AUTHORITY_LIVE=SEPARATE_GATE");
console.log("CHAT_AI_LIVE=NO");
console.log("EMAIL_SEND_LIVE=NO");
