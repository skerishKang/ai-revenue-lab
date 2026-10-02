/* B66 · Quote Beta — quote-skill.js
   Saved Quote Skill("내 견적서") 계약.

   승인된 Skill 은 한 번 검토된 업무 기본값 + 내부 QuoteTemplateProfile 을 컴파일해
   반복 생성에서 모델/원본 재분석 없이 구조화 입력만 주입한다.

   authority:
   - fixed/default business facts: Saved Quote Skill
   - per-quote business facts: structured input -> QuoteDraft
   - calculations: quote-core.js only
   - rendering: quote-template-renderer.js only

   (DOM 없음 · 브라우저/Node 양쪽에서 실행) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(
      require("./quote-core.js"),
      require("./quote-template.js"),
      require("./quote-template-renderer.js")
    );
  } else {
    root.SavedQuoteSkill = factory(root.QuoteCore, root.QuoteTemplate, root.QuoteTemplateRenderer);
  }
})(typeof self !== "undefined" ? self : this, function (Core, Template, Renderer) {
  "use strict";

  if (!Core) throw new Error("QuoteCore is required");
  if (!Template) throw new Error("QuoteTemplate is required");
  if (!Renderer) throw new Error("QuoteTemplateRenderer is required");

  var SKILL_SCHEMA_VERSION = 1;
  var SKILL_APPROVAL_SCHEMA_VERSION = 1;
  var MAX_SKILL_ID_CHARS = 64;
  var MAX_SKILL_NAME_CHARS = 80;
  var MAX_STRING_CHARS = 512;
  var MAX_MEMO_CHARS = 4000;
  var MAX_SOURCE_NAME_CHARS = 160;
  var MAX_SOURCE_REF_CHARS = 256;
  var MAX_NOTE_ITEMS = 8;
  var MAX_NOTE_CHARS = 240;
  var MAX_EVIDENCE_ITEMS = 12;
  var MAX_EVIDENCE_LABEL_CHARS = 80;
  var MAX_EVIDENCE_VALUE_CHARS = 240;
  var MAX_ITEMS = 100;
  var MAX_ITEM_NAME_CHARS = 240;
  var MAX_APPROVER_REF_CHARS = 128;

  var CALCULATION_AUTHORITY = "quote-core";
  var RENDERER_CONTRACT = "quote-template-renderer.v1";

  var EXECUTION_CONTRACT = Object.freeze({
    approvedSkillCompiledForReuse: true,
    structuredRepeatGenerationModelCalls: 0,
    sourceDocumentReanalysisPerRepeat: 0,
    fullDocumentAiRegenerationPerRepeat: 0,
    quoteCoreRecalculationModelCalls: 0,
    rendererModelCalls: 0,
    sameStructuredInputSameRender: true
  });

  var ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/;
  var APPROVER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,127}$/;
  var ISO_UTC_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/;
  var ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
  var TAX_MODES = ["EXCLUSIVE", "INCLUSIVE", "EXEMPT"];
  var SOURCE_KINDS = ["file", "manual", "sample"];

  var FIXED_DEFAULT_KEYS = ["sender", "validDays", "taxMode", "memo"];
  var VARIABLE_SCHEMA_KEYS = ["recipient", "quoteNo", "issueDate", "items", "memo", "taxMode"];
  var REQUIRED_VARIABLE_KEYS = ["recipient", "quoteNo", "issueDate", "items"];
  var PROVENANCE_KEYS = ["sourceKind", "sourceName", "sourceRef", "capturedAt", "warnings", "unknowns", "evidence"];
  var SKILL_KEYS = [
    "schemaVersion", "id", "name", "fixedDefaults", "variableSchema", "internalTemplate",
    "provenance", "approval", "fingerprint", "rendererContract", "calculationAuthority",
    "createdAt", "updatedAt"
  ];

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function unknownKeys(source, allowed) {
    return Object.keys(source).filter(function (key) { return allowed.indexOf(key) === -1; });
  }

  function boundedString(value, max, fallback) {
    if (typeof value !== "string") return fallback;
    return value.slice(0, max);
  }

  function normalizeSkillId(value) {
    if (typeof value !== "string") return null;
    var id = value.trim();
    if (!ID_PATTERN.test(id)) return null;
    return id.slice(0, MAX_SKILL_ID_CHARS);
  }

  function normalizeSkillName(value, fallback) {
    if (typeof value !== "string") return fallback;
    var name = value.trim();
    if (!name) return fallback;
    return name.slice(0, MAX_SKILL_NAME_CHARS);
  }

  function normalizeSender(raw) {
    if (!isPlainObject(raw)) return null;
    var allowed = ["company", "rep", "bizNo", "address", "phone", "email", "presetId"];
    if (unknownKeys(raw, allowed).length > 0) return null;
    var company = boundedString(raw.company, MAX_STRING_CHARS, "").trim();
    if (!company) return null;
    return {
      company: company,
      rep: boundedString(raw.rep, MAX_STRING_CHARS, "").trim(),
      bizNo: boundedString(raw.bizNo, MAX_STRING_CHARS, "").trim(),
      address: boundedString(raw.address, MAX_STRING_CHARS, "").trim(),
      phone: boundedString(raw.phone, MAX_STRING_CHARS, "").trim(),
      email: boundedString(raw.email, MAX_STRING_CHARS, "").trim(),
      presetId: boundedString(raw.presetId, 80, "saved-skill").trim() || "saved-skill"
    };
  }

  function normalizeFixedDefaults(raw) {
    if (!isPlainObject(raw)) return null;
    if (unknownKeys(raw, FIXED_DEFAULT_KEYS).length > 0) return null;
    var sender = normalizeSender(raw.sender);
    if (!sender) return null;

    if (raw.validDays === null || raw.validDays === undefined || raw.validDays === "") return null;
    var validDays = Number(raw.validDays);
    if (!Number.isFinite(validDays) || validDays < 0 || validDays > 3650) return null;
    validDays = Math.round(validDays);

    var taxMode = typeof raw.taxMode === "string" ? raw.taxMode.trim() : "";
    if (TAX_MODES.indexOf(taxMode) === -1) return null;

    var memo = boundedString(raw.memo, MAX_MEMO_CHARS, "");
    return { sender: sender, validDays: validDays, taxMode: taxMode, memo: memo };
  }

  function normalizeVariableSchema(raw) {
    var source = raw === undefined || raw === null ? {} : raw;
    if (!isPlainObject(source)) return null;
    if (unknownKeys(source, VARIABLE_SCHEMA_KEYS).length > 0) return null;

    var normalized = {
      recipient: source.recipient === undefined ? true : source.recipient === true,
      quoteNo: source.quoteNo === undefined ? true : source.quoteNo === true,
      issueDate: source.issueDate === undefined ? true : source.issueDate === true,
      items: source.items === undefined ? true : source.items === true,
      memo: source.memo === undefined ? true : source.memo === true,
      taxMode: source.taxMode === undefined ? true : source.taxMode === true
    };

    for (var i = 0; i < REQUIRED_VARIABLE_KEYS.length; i += 1) {
      if (normalized[REQUIRED_VARIABLE_KEYS[i]] !== true) return null;
    }
    return normalized;
  }

  function normalizeNotes(raw) {
    if (raw === undefined || raw === null) return [];
    if (!Array.isArray(raw) || raw.length > MAX_NOTE_ITEMS) return null;
    var notes = [];
    for (var i = 0; i < raw.length; i += 1) {
      if (typeof raw[i] !== "string") return null;
      notes.push(raw[i].slice(0, MAX_NOTE_CHARS));
    }
    return notes;
  }

  function normalizeEvidence(raw) {
    if (raw === undefined || raw === null) return [];
    if (!Array.isArray(raw) || raw.length > MAX_EVIDENCE_ITEMS) return null;
    var evidence = [];
    for (var i = 0; i < raw.length; i += 1) {
      var entry = raw[i];
      if (!isPlainObject(entry) || unknownKeys(entry, ["label", "value"]).length > 0) return null;
      var label = boundedString(entry.label, MAX_EVIDENCE_LABEL_CHARS, "").trim();
      if (!label) return null;
      evidence.push({
        label: label,
        value: boundedString(entry.value, MAX_EVIDENCE_VALUE_CHARS, "")
      });
    }
    return evidence;
  }

  function normalizeProvenance(raw) {
    if (!isPlainObject(raw)) return null;
    if (unknownKeys(raw, PROVENANCE_KEYS).length > 0) return null;
    if (SOURCE_KINDS.indexOf(raw.sourceKind) === -1) return null;
    var capturedAt = typeof raw.capturedAt === "string" ? raw.capturedAt.trim() : "";
    if (capturedAt && !ISO_UTC_PATTERN.test(capturedAt)) return null;
    var warnings = normalizeNotes(raw.warnings);
    var unknowns = normalizeNotes(raw.unknowns);
    var evidence = normalizeEvidence(raw.evidence);
    if (!warnings || !unknowns || !evidence) return null;
    return {
      sourceKind: raw.sourceKind,
      sourceName: boundedString(raw.sourceName, MAX_SOURCE_NAME_CHARS, "").trim(),
      sourceRef: boundedString(raw.sourceRef, MAX_SOURCE_REF_CHARS, "").trim(),
      capturedAt: capturedAt,
      warnings: warnings,
      unknowns: unknowns,
      evidence: evidence
    };
  }

  function normalizeInternalTemplate(raw) {
    var profile = Template.normalizeTemplate(raw);
    if (!profile || !Template.isApprovedProfile(profile)) return null;
    return Template.serializeTemplate(profile);
  }

  function compilationBasis(source) {
    return {
      fixedDefaults: source.fixedDefaults,
      variableSchema: source.variableSchema,
      internalTemplateFingerprint: source.internalTemplate.fingerprint,
      provenance: source.provenance,
      rendererContract: RENDERER_CONTRACT,
      calculationAuthority: CALCULATION_AUTHORITY
    };
  }

  function skillFingerprint(source) {
    try {
      return Template.sha256Hex(Template.canonicalJson(compilationBasis(source)));
    } catch (err) {
      return null;
    }
  }

  function normalizeApproval(raw, fingerprint) {
    if (!isPlainObject(raw)) return null;
    if (unknownKeys(raw, ["schemaVersion", "status", "skillFingerprint", "approvedBy", "approvedAt", "approvalRef"]).length > 0) return null;
    if (raw.schemaVersion !== SKILL_APPROVAL_SCHEMA_VERSION || raw.status !== "approved") return null;
    if (typeof fingerprint !== "string" || raw.skillFingerprint !== fingerprint) return null;
    var approvedBy = typeof raw.approvedBy === "string" ? raw.approvedBy.trim() : "";
    if (!APPROVER_PATTERN.test(approvedBy)) return null;
    var approvedAt = typeof raw.approvedAt === "string" ? raw.approvedAt.trim() : "";
    if (!ISO_UTC_PATTERN.test(approvedAt)) return null;
    var approvalRef = typeof raw.approvalRef === "string" ? raw.approvalRef.trim() : "";
    if (approvalRef && !APPROVER_PATTERN.test(approvalRef)) return null;
    return {
      schemaVersion: SKILL_APPROVAL_SCHEMA_VERSION,
      status: "approved",
      skillFingerprint: fingerprint,
      approvedBy: approvedBy.slice(0, MAX_APPROVER_REF_CHARS),
      approvedAt: approvedAt,
      approvalRef: approvalRef.slice(0, MAX_APPROVER_REF_CHARS)
    };
  }

  function buildSkill(source) {
    if (!isPlainObject(source)) return null;
    var id = normalizeSkillId(source.id);
    if (!id) return null;
    var fixedDefaults = normalizeFixedDefaults(source.fixedDefaults);
    var variableSchema = normalizeVariableSchema(source.variableSchema);
    var internalTemplate = normalizeInternalTemplate(source.internalTemplate);
    var provenance = normalizeProvenance(source.provenance);
    if (!fixedDefaults || !variableSchema || !internalTemplate || !provenance) return null;

    var basis = {
      fixedDefaults: fixedDefaults,
      variableSchema: variableSchema,
      internalTemplate: internalTemplate,
      provenance: provenance
    };
    var fingerprint = skillFingerprint(basis);
    if (!fingerprint) return null;
    var approval = normalizeApproval(source.approval, fingerprint);

    return {
      schemaVersion: SKILL_SCHEMA_VERSION,
      id: id,
      name: normalizeSkillName(source.name, id),
      fixedDefaults: fixedDefaults,
      variableSchema: variableSchema,
      internalTemplate: internalTemplate,
      provenance: provenance,
      approval: approval,
      approved: approval !== null,
      fingerprint: fingerprint,
      rendererContract: RENDERER_CONTRACT,
      calculationAuthority: CALCULATION_AUTHORITY,
      createdAt: typeof source.createdAt === "string" ? source.createdAt.slice(0, 40) : "",
      updatedAt: typeof source.updatedAt === "string" ? source.updatedAt.slice(0, 40) : ""
    };
  }

  function normalizeSkill(raw) {
    if (!isPlainObject(raw) || raw.schemaVersion !== SKILL_SCHEMA_VERSION) return null;
    if (unknownKeys(raw, SKILL_KEYS.concat(["approved"])).length > 0) return null;
    if (Template.findForbiddenKeys(raw).length > 0) return null;
    var skill = buildSkill(raw);
    if (!skill) return null;
    if (typeof raw.fingerprint === "string" && raw.fingerprint !== skill.fingerprint) return null;
    if (raw.rendererContract !== undefined && raw.rendererContract !== RENDERER_CONTRACT) return null;
    if (raw.calculationAuthority !== undefined && raw.calculationAuthority !== CALCULATION_AUTHORITY) return null;
    return skill;
  }

  function serializeSkill(skill) {
    var normalized = normalizeSkill(skill);
    if (!normalized) return null;
    return {
      schemaVersion: SKILL_SCHEMA_VERSION,
      id: normalized.id,
      name: normalized.name,
      fixedDefaults: cloneJson(normalized.fixedDefaults),
      variableSchema: cloneJson(normalized.variableSchema),
      internalTemplate: cloneJson(normalized.internalTemplate),
      provenance: cloneJson(normalized.provenance),
      approval: normalized.approval ? cloneJson(normalized.approval) : null,
      fingerprint: normalized.fingerprint,
      rendererContract: RENDERER_CONTRACT,
      calculationAuthority: CALCULATION_AUTHORITY,
      createdAt: normalized.createdAt,
      updatedAt: normalized.updatedAt
    };
  }

  function compileSkill(rawSkill) {
    var skill = normalizeSkill(rawSkill);
    if (!skill || skill.approved !== true) {
      return { ok: false, code: "skill_not_approved", compiled: null };
    }
    var templateProfile = Template.normalizeTemplate(skill.internalTemplate);
    if (!templateProfile || !Template.isApprovedProfile(templateProfile)) {
      return { ok: false, code: "internal_template_not_approved", compiled: null };
    }
    return {
      ok: true,
      code: "compiled",
      compiled: {
        skill: skill,
        skillFingerprint: skill.fingerprint,
        templateProfile: templateProfile,
        templateFingerprint: templateProfile.fingerprint,
        executionContract: EXECUTION_CONTRACT
      }
    };
  }

  function normalizeRecipient(raw) {
    if (!isPlainObject(raw)) return null;
    if (unknownKeys(raw, ["company", "person", "address", "email"]).length > 0) return null;
    var recipient = {
      company: boundedString(raw.company, MAX_STRING_CHARS, "").trim(),
      person: boundedString(raw.person, MAX_STRING_CHARS, "").trim(),
      address: boundedString(raw.address, MAX_STRING_CHARS, "").trim(),
      email: boundedString(raw.email, MAX_STRING_CHARS, "").trim()
    };
    if (!recipient.company && !recipient.person) return null;
    return recipient;
  }

  function normalizeItems(raw) {
    if (!Array.isArray(raw) || raw.length < 1 || raw.length > MAX_ITEMS) return null;
    var items = [];
    for (var i = 0; i < raw.length; i += 1) {
      var entry = raw[i];
      if (!isPlainObject(entry) || unknownKeys(entry, ["id", "name", "qty", "unitPrice"]).length > 0) return null;
      var name = boundedString(entry.name, MAX_ITEM_NAME_CHARS, "").trim();
      var qty = Number(entry.qty);
      var unitPrice = Number(entry.unitPrice);
      if (!name || !Number.isFinite(qty) || qty <= 0 || !Number.isFinite(unitPrice) || unitPrice < 0) return null;
      items.push({
        id: typeof entry.id === "string" && entry.id.trim() ? entry.id.trim().slice(0, 80) : "item-" + (i + 1),
        name: name,
        qty: qty,
        unitPrice: unitPrice
      });
    }
    return items;
  }

  function buildDraftFromCompiled(compiled, input) {
    if (!compiled || !compiled.skill || !isPlainObject(input)) {
      return { ok: false, code: "invalid_structured_input", draft: null };
    }
    var skill = compiled.skill;
    var quoteNo = typeof input.quoteNo === "string" ? input.quoteNo.trim() : "";
    var issueDate = typeof input.issueDate === "string" ? input.issueDate.trim() : "";
    var recipient = normalizeRecipient(input.recipient);
    var items = normalizeItems(input.items);
    if (!quoteNo || quoteNo.length > 120 || !ISO_DATE_PATTERN.test(issueDate) || !Core.parseISODate(issueDate) || !recipient || !items) {
      return { ok: false, code: "invalid_structured_input", draft: null };
    }

    var taxMode = skill.fixedDefaults.taxMode;
    if (skill.variableSchema.taxMode && input.taxMode !== undefined) {
      if (TAX_MODES.indexOf(input.taxMode) === -1) return { ok: false, code: "invalid_tax_mode", draft: null };
      taxMode = input.taxMode;
    }

    var memo = skill.fixedDefaults.memo;
    if (skill.variableSchema.memo && input.memo !== undefined) {
      if (typeof input.memo !== "string") return { ok: false, code: "invalid_memo", draft: null };
      memo = input.memo.slice(0, MAX_MEMO_CHARS);
    }

    var draft = Core.normalizeDraft({
      schemaVersion: Core.SCHEMA_VERSION,
      meta: {
        quoteNo: quoteNo,
        issueDate: issueDate,
        validDays: skill.fixedDefaults.validDays,
        source: "saved-quote-skill"
      },
      sender: cloneJson(skill.fixedDefaults.sender),
      recipient: recipient,
      items: items,
      tax: { mode: taxMode, rate: Core.VAT_RATE },
      memo: memo
    });
    if (!draft) return { ok: false, code: "invalid_quote_draft", draft: null };
    return { ok: true, code: "draft_ready", draft: draft };
  }

  function buildDraft(rawSkill, input) {
    var compiled = compileSkill(rawSkill);
    if (!compiled.ok) return { ok: false, code: compiled.code, draft: null, compiled: null };
    var built = buildDraftFromCompiled(compiled.compiled, input);
    return Object.assign({}, built, { compiled: compiled.compiled });
  }

  function buildRenderModel(rawSkill, input) {
    var built = buildDraft(rawSkill, input);
    if (!built.ok) return { ok: false, code: built.code, draft: null, renderModel: null, compiled: built.compiled };
    /* Keep the repeat-generation public arity at (skill, input). #3402 may
       supply one transient third argument for already-authorized private asset
       render sources; it is neither source-document input nor model authority. */
    var options = arguments.length > 2 ? arguments[2] : null;
    var opts = isPlainObject(options) ? options : {};
    var renderModel = Renderer.buildRenderModel(built.draft, built.compiled.templateProfile, {
      taxReviewRequired: false,
      slotSources: isPlainObject(opts.slotSources) ? opts.slotSources : {}
    });
    if (!renderModel) return { ok: false, code: "render_model_failed", draft: built.draft, renderModel: null, compiled: built.compiled };
    return {
      ok: true,
      code: "render_ready",
      draft: built.draft,
      renderModel: renderModel,
      compiled: built.compiled
    };
  }

  return {
    SKILL_SCHEMA_VERSION: SKILL_SCHEMA_VERSION,
    SKILL_APPROVAL_SCHEMA_VERSION: SKILL_APPROVAL_SCHEMA_VERSION,
    MAX_SKILL_ID_CHARS: MAX_SKILL_ID_CHARS,
    MAX_SKILL_NAME_CHARS: MAX_SKILL_NAME_CHARS,
    CALCULATION_AUTHORITY: CALCULATION_AUTHORITY,
    RENDERER_CONTRACT: RENDERER_CONTRACT,
    EXECUTION_CONTRACT: EXECUTION_CONTRACT,
    FIXED_DEFAULT_KEYS: FIXED_DEFAULT_KEYS.slice(),
    VARIABLE_SCHEMA_KEYS: VARIABLE_SCHEMA_KEYS.slice(),
    REQUIRED_VARIABLE_KEYS: REQUIRED_VARIABLE_KEYS.slice(),
    normalizeSkillId: normalizeSkillId,
    normalizeSkillName: normalizeSkillName,
    normalizeFixedDefaults: normalizeFixedDefaults,
    normalizeVariableSchema: normalizeVariableSchema,
    normalizeProvenance: normalizeProvenance,
    normalizeApproval: normalizeApproval,
    skillFingerprint: skillFingerprint,
    buildSkill: buildSkill,
    normalizeSkill: normalizeSkill,
    serializeSkill: serializeSkill,
    compileSkill: compileSkill,
    buildDraftFromCompiled: buildDraftFromCompiled,
    buildDraft: buildDraft,
    buildRenderModel: buildRenderModel
  };
});