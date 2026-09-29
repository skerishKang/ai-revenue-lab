/* B66 · Quote Beta — quote-skill-registration.js
   기존 견적서 등록 seam: #3212 extraction + 문서/서식 판단(명시적 template 결정·manual correction)
   → SavedQuoteSkillCandidate → review/correction → explicit approval → Saved Quote Skill.

   흐름:
     raw model output
     → QuoteExtraction.normalizeExtraction (malformed fail-closed, 계산값 진입 불가)
     → fixed/default (발주처 기본값) vs per-quote variable (거래처/번호/날짜/품목) 분리
     → internalTemplate: builtin 또는 이미 승인된 profile 만 허용
     → SavedQuoteSkillCandidate.normalizeCandidate (검토 대상)
     → (review → correction → approve는 candidate/store 계약 사용)

   정직한 범위:
   - 자동 layout 학습기는 없다. 문서/서식 behavior는 명시적 template 결정
     (내장 기본 또는 기존 승인 profile) + 사용자 manual correction 으로만 들어온다.
   - 반복 생성은 compiled Skill + QuoteDraft + QuoteCore + 기존 renderer 만 사용하고
     원본 재분석·전체 AI 재생성을 하지 않는다. 이 모듈은 network/model 호출이 없다.

   (DOM 없음 · 브라우저/Node 양쪽에서 실행) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(
      require("./quote-extraction.js"),
      require("./quote-skill.js"),
      require("./quote-skill-candidate.js"),
      require("./quote-template.js")
    );
  } else {
    root.SavedQuoteSkillRegistration = factory(
      root.QuoteExtraction,
      root.SavedQuoteSkill,
      root.SavedQuoteSkillCandidate,
      root.QuoteTemplate
    );
  }
})(typeof self !== "undefined" ? self : this, function (Extraction, Skill, Candidate, Template) {
  "use strict";

  if (!Extraction) throw new Error("QuoteExtraction is required");
  if (!Skill) throw new Error("SavedQuoteSkill is required");
  if (!Candidate) throw new Error("SavedQuoteSkillCandidate is required");
  if (!Template) throw new Error("QuoteTemplate is required");

  /* Skill.normalizeProvenance bounds (quote-skill.js). 초과분은 버리지 않고
     well-known 접미 항목으로 접어서 검토 화면에 남긴다. */
  var SKILL_EVIDENCE_KEEP = 12;
  var SKILL_NOTE_KEEP = 8;

  var SENDER_FIELDS = ["company", "rep", "bizNo", "address", "phone", "email"];
  var SKILL_SOURCE_KINDS = ["file", "manual", "sample"];
  var TAX_MODES = ["EXCLUSIVE", "INCLUSIVE", "EXEMPT"];

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function fail(code, message) {
    return { ok: false, code: code, message: message || null, candidate: null, review: null, correctionsApplied: [] };
  }

  function noteCorrection(list, field) {
    list.push("manual_correction:" + field);
  }

  /* ── fixed/default 병합: 추출값 위에 명시적 보정을 덮어쓴다 ── */

  function mergeSender(extracted, correction, correctionsApplied, correctionNotes) {
    var base = isPlainObject(extracted) ? extracted : {};
    var overlay = isPlainObject(correction) ? correction : null;
    if (overlay && Object.keys(overlay).some(function (key) { return SENDER_FIELDS.indexOf(key) === -1; })) {
      return null;
    }
    var merged = {};
    SENDER_FIELDS.forEach(function (field) {
      if (overlay && Object.prototype.hasOwnProperty.call(overlay, field) && overlay[field] !== undefined) {
        merged[field] = overlay[field];
        noteCorrection(correctionNotes, "sender." + field);
        if (correctionsApplied.indexOf("sender." + field) === -1) correctionsApplied.push("sender." + field);
      } else {
        merged[field] = base[field] === undefined ? null : base[field];
      }
    });
    return merged;
  }

  function mergeScalar(extractedValue, correctionValue, field, correctionsApplied, correctionNotes) {
    if (correctionValue !== undefined) {
      noteCorrection(correctionNotes, field);
      if (correctionsApplied.indexOf(field) === -1) correctionsApplied.push(field);
      return correctionValue;
    }
    return extractedValue === undefined ? null : extractedValue;
  }

  function coerceValidDays(value) {
    if (value === null || value === undefined || value === "") return null;
    var number = Number(value);
    if (!Number.isFinite(number)) return null;
    return Math.round(number);
  }

  /* ── provenance 조립: 증거/경고/미확인 항목은 잘라내지 않고 보존 ── */

  function mapEvidence(extractedEvidence) {
    return (extractedEvidence || []).map(function (entry) {
      var label = typeof entry.field === "string" ? entry.field.trim().slice(0, 80) : "";
      var value = "";
      if (typeof entry.snippet === "string" && entry.snippet.trim()) {
        value = entry.snippet.trim().slice(0, 240);
      } else if (entry.page !== null && entry.page !== undefined) {
        value = ("page " + entry.page).slice(0, 240);
      } else if (entry.confidence !== null && entry.confidence !== undefined) {
        value = ("confidence " + entry.confidence).slice(0, 240);
      }
      return { label: label, value: value };
    });
  }

  function deriveUnknowns(normalized) {
    var unknowns = [];
    SENDER_FIELDS.forEach(function (field) {
      if (field !== "company" && normalized.sender[field] === null) unknowns.push("sender." + field);
    });
    ["company", "person", "address", "email"].forEach(function (field) {
      if (normalized.recipient[field] === null) unknowns.push("recipient." + field);
    });
    if (normalized.quote.quoteNo === null) unknowns.push("quote.quoteNo");
    if (normalized.quote.issueDate === null) unknowns.push("quote.issueDate");
    if (normalized.quote.validDays === null) unknowns.push("quote.validDays");
    if (normalized.tax.mode === null) unknowns.push("tax.mode");
    if (normalized.memo === null) unknowns.push("memo");
    if (normalized.items.length === 0) unknowns.push("items");
    return unknowns;
  }

  function foldNotes(primary, overflowKind, overflowCount) {
    var kept = primary.slice(0, SKILL_NOTE_KEEP);
    if (primary.length > SKILL_NOTE_KEEP) {
      kept.push(overflowKind + ":" + overflowCount);
    }
    return kept.slice(0, SKILL_NOTE_KEEP);
  }

  /* ── 본 작업: extraction + 판단/보정 → SavedQuoteSkillCandidate ── */

  function buildRegistrationCandidate(input, options) {
    var opts = options || {};
    var correctionsApplied = [];
    var correctionNotes = [];
    if (!isPlainObject(input)) return fail("invalid_registration_input");

    var corrections = isPlainObject(input.corrections) ? input.corrections : {};

    /* 1. #3212 extraction 경계 재사용: malformed model output fail-closed. */
    var normalized = Extraction.normalizeExtraction(input.modelOutput);
    if (!normalized.ok) return fail(normalized.error || "invalid_extraction");
    var extracted = normalized.value;

    /* 2. fixed/default 병합. */
    var sender = mergeSender(extracted.sender, corrections.sender, correctionsApplied, correctionNotes);
    if (!sender) return fail("invalid_sender_correction");
    if (typeof sender.company !== "string" || !sender.company.trim()) {
      return fail("sender_company_requires_correction");
    }

    var validDays = mergeScalar(extracted.quote.validDays, corrections.validDays, "validDays", correctionsApplied, correctionNotes);
    validDays = coerceValidDays(validDays);
    if (validDays === null || validDays < 0 || validDays > 3650) {
      return fail("valid_days_requires_correction");
    }

    var taxMode = mergeScalar(
      extracted.tax.mode, corrections.taxMode, "taxMode", correctionsApplied, correctionNotes
    );
    if (typeof taxMode !== "string" || TAX_MODES.indexOf(taxMode) === -1) {
      return fail("tax_mode_requires_correction");
    }

    var memo = mergeScalar(extracted.memo, corrections.memo, "memo", correctionsApplied, correctionNotes);
    if (memo === null || memo === undefined) memo = "";
    if (typeof memo !== "string") return fail("invalid_memo_correction");

    var flags = isPlainObject(corrections.variableFlags) ? corrections.variableFlags : {};
    if ((flags.memo !== undefined && typeof flags.memo !== "boolean") ||
        (flags.taxMode !== undefined && typeof flags.taxMode !== "boolean")) {
      return fail("invalid_variable_flags_correction");
    }
    if (flags.memo !== undefined || flags.taxMode !== undefined) {
      if (correctionsApplied.indexOf("variableFlags") === -1) correctionsApplied.push("variableFlags");
      noteCorrection(correctionNotes, "variableFlags");
    }
    var variableSchema = {
      recipient: true,
      quoteNo: true,
      issueDate: true,
      items: true,
      memo: flags.memo === undefined ? true : flags.memo,
      taxMode: flags.taxMode === undefined ? true : flags.taxMode
    };

    /* 3. internalTemplate: builtin 또는 이미 승인된 profile 만. 자동 학습 없음. */
    var decision = isPlainObject(input.templateDecision) ? input.templateDecision : { mode: "builtin" };
    var internalTemplate = null;
    if (decision.mode === "builtin" || decision.mode === undefined) {
      internalTemplate = Template.serializeTemplate(Template.builtInTemplate());
    } else if (decision.mode === "approved-template") {
      var profile = Template.normalizeTemplate(decision.template);
      if (!profile || !Template.isApprovedProfile(profile)) {
        return fail("template_not_approved");
      }
      internalTemplate = Template.serializeTemplate(profile);
    } else {
      return fail("unsupported_template_decision");
    }

    /* 4. provenance: 원본 바이트 저장 없이 메타데이터만. */
    var sourceMeta = isPlainObject(input.sourceMeta) ? input.sourceMeta : {};
    var sourceKind = sourceMeta.sourceKind === undefined ? "file" : sourceMeta.sourceKind;
    if (SKILL_SOURCE_KINDS.indexOf(sourceKind) === -1) return fail("invalid_source_kind");
    var capturedAt = typeof sourceMeta.capturedAt === "string" ? sourceMeta.capturedAt
      : (typeof opts.now === "string" ? opts.now : "");
    var evidence = mapEvidence(extracted.evidence);
    var systemWarnings = correctionNotes.slice();
    if (evidence.length > SKILL_EVIDENCE_KEEP) {
      systemWarnings.push("evidence_truncated_for_skill_review:" + evidence.length);
      evidence = evidence.slice(0, SKILL_EVIDENCE_KEEP);
    }
    var modelWarnings = Array.isArray(extracted.warnings) ? extracted.warnings.slice() : [];
    var warnings = systemWarnings.concat(modelWarnings);
    var unknowns = deriveUnknowns(extracted);
    if (warnings.length > SKILL_NOTE_KEEP) {
      var dropped = warnings.length - SKILL_NOTE_KEEP;
      warnings = warnings.slice(0, SKILL_NOTE_KEEP);
      unknowns.push("additional_model_warnings:" + dropped);
    }
    unknowns = foldNotes(unknowns, "additional_unknowns", Math.max(0, unknowns.length - SKILL_NOTE_KEEP));

    var skillName = corrections.skillName !== undefined ? corrections.skillName
      : (input.skillName !== undefined ? input.skillName : undefined);
    if (skillName !== undefined && corrections.skillName !== undefined &&
        correctionsApplied.indexOf("skillName") === -1) {
      correctionsApplied.push("skillName");
    }

    /* 5. candidate 경계가 최종 검증 authority: 내부 승인 template·지문 기반. */
    var built = Candidate.normalizeCandidate({
      schemaVersion: 1,
      candidateId: input.candidateId,
      name: skillName,
      fixedDefaults: { sender: sender, validDays: validDays, taxMode: taxMode, memo: memo },
      variableSchema: variableSchema,
      internalTemplate: internalTemplate,
      provenance: {
        sourceKind: sourceKind,
        sourceName: typeof sourceMeta.filename === "string" ? sourceMeta.filename
          : (typeof extracted.source.filename === "string" ? extracted.source.filename : ""),
        sourceRef: typeof sourceMeta.sourceRef === "string" ? sourceMeta.sourceRef : "",
        capturedAt: capturedAt,
        warnings: warnings,
        unknowns: unknowns,
        evidence: evidence
      }
    }, opts);
    if (!built.ok) return fail(built.code || "invalid_skill_candidate");
    return {
      ok: true,
      code: "registration_candidate_ready",
      message: null,
      candidate: built.candidate,
      review: Candidate.buildReviewModel(built.candidate),
      correctionsApplied: correctionsApplied
    };
  }

  return {
    SKILL_EVIDENCE_KEEP: SKILL_EVIDENCE_KEEP,
    SKILL_NOTE_KEEP: SKILL_NOTE_KEEP,
    buildRegistrationCandidate: buildRegistrationCandidate
  };
});
