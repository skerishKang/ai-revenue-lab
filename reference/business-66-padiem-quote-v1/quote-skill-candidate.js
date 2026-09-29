/* B66 · Quote Beta — quote-skill-candidate.js
   Saved Quote Skill 후보/검토/명시 승인 계약.

   source values are not silently frozen. The candidate only permits business defaults
   through the bounded fixedDefaults contract; recipient/quote number/date/items stay
   mandatory per-quotation variables. Calculated fields are locked to QuoteCore.

   (DOM 없음 · 브라우저/Node 양쪽에서 실행) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./quote-skill.js"));
  } else {
    root.SavedQuoteSkillCandidate = factory(root.SavedQuoteSkill);
  }
})(typeof self !== "undefined" ? self : this, function (Skill) {
  "use strict";

  if (!Skill) throw new Error("SavedQuoteSkill is required");

  var CANDIDATE_SCHEMA_VERSION = 1;
  var STATUS_CANDIDATE = "candidate";
  var DEFAULT_APPROVER = "local-owner";
  var CALCULATED_FIELDS = ["lineAmounts", "supplyTotal", "vatAmount", "grandTotal", "validUntil"];
  var CANDIDATE_KEYS = [
    "schemaVersion", "candidateId", "name", "fixedDefaults", "variableSchema",
    "internalTemplate", "provenance"
  ];
  var ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/;
  var APPROVER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,127}$/;

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function unknownKeys(source, allowed) {
    return Object.keys(source).filter(function (key) { return allowed.indexOf(key) === -1; });
  }

  function fail(code, message, candidate) {
    return { ok: false, code: code, message: message || null, candidate: candidate || null };
  }

  function candidateId(value, seed) {
    if (typeof value === "string" && ID_PATTERN.test(value.trim())) return value.trim();
    var stamp = String(seed == null ? "" : seed).replace(/[^0-9]/g, "").slice(0, 17) || "0";
    return ("skill-candidate-" + stamp).slice(0, 64);
  }

  function skillId(value, seed) {
    var explicit = Skill.normalizeSkillId(value);
    if (explicit) return explicit;
    var stamp = String(seed == null ? "" : seed).replace(/[^0-9]/g, "").slice(0, 17) || "0";
    return ("saved-quote-" + stamp).slice(0, Skill.MAX_SKILL_ID_CHARS);
  }

  function normalizeCandidate(raw, options) {
    var opts = options || {};
    if (!isPlainObject(raw)) return fail("invalid_skill_candidate");
    if (raw.schemaVersion !== CANDIDATE_SCHEMA_VERSION) return fail("invalid_skill_candidate_schema");
    if (unknownKeys(raw, CANDIDATE_KEYS).length > 0) return fail("unsupported_skill_candidate_field");

    var fixedDefaults = Skill.normalizeFixedDefaults(raw.fixedDefaults);
    if (!fixedDefaults) return fail("invalid_fixed_defaults");
    var variableSchema = Skill.normalizeVariableSchema(raw.variableSchema);
    if (!variableSchema) return fail("invalid_variable_schema");
    var provenance = Skill.normalizeProvenance(raw.provenance);
    if (!provenance) return fail("invalid_skill_provenance");

    /* buildSkill is reused as the final authority for the internal approved template and fingerprint basis. */
    var provisional = Skill.buildSkill({
      id: "candidate-probe",
      name: Skill.normalizeSkillName(raw.name, "내 견적서 후보"),
      fixedDefaults: fixedDefaults,
      variableSchema: variableSchema,
      internalTemplate: raw.internalTemplate,
      provenance: provenance,
      approval: null,
      createdAt: "",
      updatedAt: ""
    });
    if (!provisional) return fail("invalid_internal_template");

    return {
      ok: true,
      code: "candidate_ready",
      candidate: {
        schemaVersion: CANDIDATE_SCHEMA_VERSION,
        candidateId: candidateId(raw.candidateId, opts.now),
        name: provisional.name,
        fixedDefaults: provisional.fixedDefaults,
        variableSchema: provisional.variableSchema,
        internalTemplate: provisional.internalTemplate,
        provenance: provisional.provenance,
        skillFingerprint: provisional.fingerprint,
        status: STATUS_CANDIDATE
      }
    };
  }

  function editCandidate(candidate, patch, options) {
    if (!candidate || candidate.status !== STATUS_CANDIDATE || !isPlainObject(patch)) {
      return fail("candidate_not_editable", null, candidate || null);
    }
    if (unknownKeys(patch, ["name", "fixedDefaults", "variableSchema"]).length > 0) {
      return fail("unsupported_skill_candidate_edit", null, candidate);
    }
    return normalizeCandidate({
      schemaVersion: CANDIDATE_SCHEMA_VERSION,
      candidateId: candidate.candidateId,
      name: patch.name === undefined ? candidate.name : patch.name,
      fixedDefaults: patch.fixedDefaults === undefined ? candidate.fixedDefaults : patch.fixedDefaults,
      variableSchema: patch.variableSchema === undefined ? candidate.variableSchema : patch.variableSchema,
      internalTemplate: candidate.internalTemplate,
      provenance: candidate.provenance
    }, options);
  }

  function buildReviewModel(candidate) {
    if (!candidate || candidate.status !== STATUS_CANDIDATE) return null;
    var sender = candidate.fixedDefaults.sender;
    return {
      candidateId: candidate.candidateId,
      name: candidate.name,
      status: candidate.status,
      source: {
        kind: candidate.provenance.sourceKind,
        name: candidate.provenance.sourceName,
        capturedAt: candidate.provenance.capturedAt,
        warnings: candidate.provenance.warnings.slice(),
        unknowns: candidate.provenance.unknowns.slice(),
        evidence: candidate.provenance.evidence.slice()
      },
      alwaysReusedOrDefault: [
        { key: "sender.company", label: "회사명", value: sender.company },
        { key: "sender.rep", label: "대표자", value: sender.rep },
        { key: "sender.bizNo", label: "사업자번호", value: sender.bizNo },
        { key: "sender.address", label: "주소", value: sender.address },
        { key: "sender.phone", label: "연락처", value: sender.phone },
        { key: "sender.email", label: "이메일", value: sender.email },
        { key: "validDays", label: "기본 유효기간", value: candidate.fixedDefaults.validDays },
        { key: "taxMode", label: "기본 세금 방식", value: candidate.fixedDefaults.taxMode },
        { key: "memo", label: "기본 비고", value: candidate.fixedDefaults.memo }
      ],
      changesEachQuote: [
        { key: "recipient", label: "받는 사람/거래처", required: true },
        { key: "quoteNo", label: "견적번호", required: true },
        { key: "issueDate", label: "작성일", required: true },
        { key: "items", label: "품목·수량·단가", required: true },
        { key: "memo", label: "건별 비고", required: candidate.variableSchema.memo === true },
        { key: "taxMode", label: "건별 세금 방식", required: candidate.variableSchema.taxMode === true }
      ],
      calculatedByCore: CALCULATED_FIELDS.map(function (key) { return { key: key, authority: Skill.CALCULATION_AUTHORITY }; }),
      internalTemplate: {
        id: candidate.internalTemplate.id,
        name: candidate.internalTemplate.name,
        fingerprint: candidate.internalTemplate.fingerprint
      },
      skillFingerprint: candidate.skillFingerprint
    };
  }

  function approveCandidate(candidate, options) {
    var opts = options || {};
    if (!candidate || candidate.status !== STATUS_CANDIDATE) return fail("candidate_not_reviewable", null, candidate || null);

    var rebuilt = normalizeCandidate({
      schemaVersion: CANDIDATE_SCHEMA_VERSION,
      candidateId: candidate.candidateId,
      name: candidate.name,
      fixedDefaults: candidate.fixedDefaults,
      variableSchema: candidate.variableSchema,
      internalTemplate: candidate.internalTemplate,
      provenance: candidate.provenance
    }, opts);
    if (!rebuilt.ok || rebuilt.candidate.skillFingerprint !== candidate.skillFingerprint) {
      return fail("candidate_changed_after_review", null, candidate);
    }

    var approvedAt = typeof opts.now === "string" && opts.now ? opts.now.slice(0, 40) : new Date().toISOString();
    var approvedBy = typeof opts.approvedBy === "string" && APPROVER_PATTERN.test(opts.approvedBy.trim())
      ? opts.approvedBy.trim()
      : DEFAULT_APPROVER;
    var id = skillId(opts.id, approvedAt);

    var approval = {
      schemaVersion: Skill.SKILL_APPROVAL_SCHEMA_VERSION,
      status: "approved",
      skillFingerprint: candidate.skillFingerprint,
      approvedBy: approvedBy,
      approvedAt: approvedAt,
      approvalRef: typeof opts.approvalRef === "string" ? opts.approvalRef : ""
    };

    var skill = Skill.buildSkill({
      id: id,
      name: candidate.name,
      fixedDefaults: candidate.fixedDefaults,
      variableSchema: candidate.variableSchema,
      internalTemplate: candidate.internalTemplate,
      provenance: candidate.provenance,
      approval: approval,
      createdAt: approvedAt,
      updatedAt: approvedAt
    });
    if (!skill || skill.approved !== true) return fail("skill_approval_failed", null, candidate);
    return { ok: true, code: "approved", message: null, candidate: candidate, skill: skill };
  }

  function isApprovedCandidate() {
    return false;
  }

  return {
    CANDIDATE_SCHEMA_VERSION: CANDIDATE_SCHEMA_VERSION,
    STATUS_CANDIDATE: STATUS_CANDIDATE,
    DEFAULT_APPROVER: DEFAULT_APPROVER,
    CALCULATED_FIELDS: CALCULATED_FIELDS.slice(),
    normalizeCandidate: normalizeCandidate,
    editCandidate: editCandidate,
    buildReviewModel: buildReviewModel,
    approveCandidate: approveCandidate,
    isApprovedCandidate: isApprovedCandidate
  };
});
