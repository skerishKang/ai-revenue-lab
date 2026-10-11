/* B66 · Quote Beta — quote-registration-session.js
   하나의 등록 사용자 흐름을 묶는 세션 상태 기계.

     [내가 쓰던 견적서 등록]
     1. 견적서 선택 (source metadata, 원본 바이트 저장 없음)
     2. 회사정보/업무값 분석 (extraction → skill candidate, 별도 단계)
     3. 견적서 모양 확인 (template candidate → 보정 → preview)
     4. 필요한 부분 수정 (template/skill correction)
     5. 최종 확인 (review 모델)
     6. "내 견적서" 저장 (template approval + skill approval, 분리된 명시 승인)

   분리 원칙:
   - template approval 과 skill approval 은 서로 다른 명시적 승인이다. 합치지 않는다.
   - 두 승인 모두 fingerprint-bound 다. 내용이 바뀌면 과거 승인은 재사용 불가다.
   - 저장은 commit 단계에서만 일어나고, 중간 preview/correction/approval 은
     storage 를 건드리지 않는다. commit 은 template+skill 두 키를 함께 쓰고,
     부분 실패 시 스냅샷으로 rollback 한다.

   (DOM 없음 · 브라우저/Node 양쪽에서 실행) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(
      require("./quote-template.js"),
      require("./quote-template-registration.js"),
      require("./quote-template-candidate.js"),
      require("./quote-template-store.js"),
      require("./quote-template-renderer.js"),
      require("./quote-skill.js"),
      require("./quote-skill-candidate.js"),
      require("./quote-skill-registration.js"),
      require("./quote-skill-store.js")
    );
  } else {
    root.QuoteRegistrationSession = factory(
      root.QuoteTemplate,
      root.QuoteTemplateRegistration,
      root.QuoteTemplateCandidate,
      root.QuoteTemplateStore,
      root.QuoteTemplateRenderer,
      root.SavedQuoteSkill,
      root.SavedQuoteSkillCandidate,
      root.SavedQuoteSkillRegistration,
      root.SavedQuoteSkillStore
    );
  }
})(typeof self !== "undefined" ? self : this, function (
  Template, TemplateRegistration, TemplateCandidate, TemplateStore, Renderer,
  Skill, SkillCandidate, SkillRegistration, SkillStore
) {
  "use strict";

  if (!Template) throw new Error("QuoteTemplate is required");
  if (!TemplateRegistration) throw new Error("QuoteTemplateRegistration is required");
  if (!TemplateCandidate) throw new Error("QuoteTemplateCandidate is required");
  if (!TemplateStore) throw new Error("QuoteTemplateStore is required");
  if (!Renderer) throw new Error("QuoteTemplateRenderer is required");
  if (!Skill) throw new Error("SavedQuoteSkill is required");
  if (!SkillCandidate) throw new Error("SavedQuoteSkillCandidate is required");
  if (!SkillRegistration) throw new Error("SavedQuoteSkillRegistration is required");
  if (!SkillStore) throw new Error("SavedQuoteSkillStore is required");

  var STATUS_IDLE = "idle";
  var STATUS_TEMPLATE_REVIEW = "template_review";
  var STATUS_TEMPLATE_APPROVED = "template_approved";
  var STATUS_SKILL_REVIEW = "skill_review";
  var STATUS_SKILL_APPROVED = "skill_approved";
  var STATUS_COMMITTED = "committed";
  var STATUS_CANCELLED = "cancelled";
  var STATUS_FAILED = "failed";

  /* 등록 wizard 단계 라벨. 자동 학습 과장 표현을 쓰지 않는다. */
  var STEP_LABELS = [
    "견적서 선택",
    "회사정보/업무값 분석",
    "견적서 모양 확인",
    "필요한 부분 수정",
    "최종 확인",
    "내 견적서 저장"
  ];

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function fail(code, session) {
    return { ok: false, code: code, message: null, session: session || null };
  }

  function ok(code, session, extra) {
    return Object.assign({ ok: true, code: code, message: null, session: session }, extra || {});
  }

  function stampOf(options) {
    var opts = options || {};
    return typeof opts.now === "string" && opts.now
      ? opts.now.slice(0, 40)
      : new Date().toISOString();
  }

  function freshSession() {
    return {
      status: STATUS_IDLE,
      steps: STEP_LABELS.slice(),
      templateCandidate: null,
      templateReview: null,
      approvedTemplate: null,
      templateEvidence: null,
      templateId: null,
      skillCandidate: null,
      skillReview: null,
      correctionsApplied: [],
      approvedSkill: null,
      error: null
    };
  }

  function requireStatus(session, status) {
    return Boolean(session) && session.status === status;
  }

  /* ── 1-2. 시작: source metadata → template 초안 candidate ── */

  function start(sourceInfo, options) {
    var session = freshSession();
    var built = TemplateRegistration.buildTemplateCandidateFromSource(sourceInfo, options);
    if (!built.ok) {
      session.status = STATUS_FAILED;
      session.error = built.code;
      return fail(built.code || "registration_start_failed", session);
    }
    session.status = STATUS_TEMPLATE_REVIEW;
    session.templateCandidate = built.candidate;
    session.templateReview = built.review;
    return ok("registration_started", session, { draftNote: built.draftNote });
  }

  /* ── 3-4. 모양 보정/preview (storage 접근 없음) ── */

  function correctTemplate(session, patch, options) {
    if (!requireStatus(session, STATUS_TEMPLATE_REVIEW)) return fail("template_not_reviewable", session);
    var next = TemplateRegistration.correctTemplateCandidate(session.templateCandidate, patch, options);
    if (!next.ok) return fail(next.code || "template_correction_failed", session);
    var copy = cloneJson(session);
    copy.templateCandidate = next.candidate;
    copy.templateReview = next.review;
    return ok("template_corrected", copy, { review: next.review });
  }

  function previewTemplate(session, draft, options) {
    if (!requireStatus(session, STATUS_TEMPLATE_REVIEW)) {
      return { ok: false, code: "template_not_previewable", message: null, renderModel: null };
    }
    return TemplateRegistration.previewTemplateCandidate(session.templateCandidate, draft, options);
  }

  /* ── template 명시 승인 (메모리 내 approved profile, 저장 없음) ── */

  function approveTemplate(session, evidenceMeta, options) {
    var opts = options || {};
    if (!requireStatus(session, STATUS_TEMPLATE_REVIEW)) return fail("template_not_approvable", session);
    var candidate = session.templateCandidate;
    var meta = isPlainObject(evidenceMeta) ? evidenceMeta : {};
    var approvedAt = typeof meta.approvedAt === "string" && meta.approvedAt
      ? meta.approvedAt.slice(0, 40)
      : stampOf(opts);
    var id = typeof meta.id === "string" && Template.normalizeTemplateId(meta.id)
      ? meta.id
      : ("tpl-reg-" + approvedAt.replace(/[^0-9]/g, "").slice(0, 14));
    var evidence = {
      schemaVersion: Template.APPROVAL_SCHEMA_VERSION,
      status: "approved",
      contentFingerprint: candidate.contentFingerprint,
      approvedBy: meta.approvedBy,
      approvedAt: approvedAt,
      approvalRef: typeof meta.approvalRef === "string" ? meta.approvalRef : ""
    };
    var profile = Template.buildProfile({
      id: id,
      name: candidate.name,
      builtin: false,
      isDefault: false,
      approval: evidence,
      createdAt: approvedAt,
      updatedAt: approvedAt,
      content: candidate.content
    });
    if (!profile || !Template.isApprovedProfile(profile) ||
        profile.fingerprint !== candidate.contentFingerprint) {
      return fail("template_approval_failed", session);
    }
    var copy = cloneJson(session);
    copy.status = STATUS_TEMPLATE_APPROVED;
    copy.approvedTemplate = Template.serializeTemplate(profile);
    copy.templateEvidence = evidence;
    copy.templateId = id;
    return ok("template_approved", copy);
  }

  /* ── 2/5. 방금 승인한 profile 을 skill 등록에 연결 ── */

  function buildSkillCandidate(session, registrationInput, options) {
    if (!requireStatus(session, STATUS_TEMPLATE_APPROVED)) return fail("template_not_approved_for_skill", session);
    var input = isPlainObject(registrationInput) ? cloneJson(registrationInput) : {};
    input.templateDecision = { mode: "approved-template", template: session.approvedTemplate };
    var built = SkillRegistration.buildRegistrationCandidate(input, options);
    if (!built.ok) return fail(built.code || "skill_candidate_failed", session);
    var copy = cloneJson(session);
    copy.status = STATUS_SKILL_REVIEW;
    copy.skillCandidate = built.candidate;
    copy.skillReview = built.review;
    copy.correctionsApplied = built.correctionsApplied.slice();
    return ok("skill_candidate_ready", copy, { review: built.review });
  }

  function correctSkill(session, patch, options) {
    if (!requireStatus(session, STATUS_SKILL_REVIEW)) return fail("skill_not_reviewable", session);
    var edited = SkillCandidate.editCandidate(session.skillCandidate, patch, options);
    if (!edited.ok) return fail(edited.code || "skill_correction_failed", session);
    var copy = cloneJson(session);
    copy.skillCandidate = edited.candidate;
    copy.skillReview = SkillCandidate.buildReviewModel(edited.candidate);
    return ok("skill_corrected", copy, { review: copy.skillReview });
  }

  /* skill preview: 승인 위조 없이 transient compiled 로 동일 renderer. 저장 없음. */

  function previewSkill(session, input, options) {
    if (!requireStatus(session, STATUS_SKILL_REVIEW)) {
      return { ok: false, code: "skill_not_previewable", message: null, draft: null, renderModel: null };
    }
    var profile = Template.normalizeTemplate(session.approvedTemplate);
    if (!profile || !Template.isApprovedProfile(profile)) {
      return { ok: false, code: "approved_template_invalid", message: null, draft: null, renderModel: null };
    }
    var provisional = Skill.buildSkill({
      id: "preview-unapproved-skill",
      name: session.skillCandidate.name,
      fixedDefaults: session.skillCandidate.fixedDefaults,
      variableSchema: session.skillCandidate.variableSchema,
      internalTemplate: session.skillCandidate.internalTemplate,
      provenance: session.skillCandidate.provenance,
      approval: null,
      createdAt: "",
      updatedAt: ""
    });
    if (!provisional) {
      return { ok: false, code: "skill_preview_build_failed", message: null, draft: null, renderModel: null };
    }
    var compiled = {
      skill: provisional,
      skillFingerprint: session.skillCandidate.skillFingerprint,
      templateProfile: profile,
      templateFingerprint: profile.fingerprint
    };
    var built = Skill.buildDraftFromCompiled(compiled, input);
    if (!built.ok) {
      return { ok: false, code: built.code || "skill_preview_failed", message: null, draft: null, renderModel: null };
    }
    var renderModel = Renderer.buildRenderModel(built.draft,
      Template.serializeTemplate(profile), { taxReviewRequired: false });
    if (!renderModel) {
      return { ok: false, code: "skill_preview_failed", message: null, draft: null, renderModel: null };
    }
    return { ok: true, code: "skill_preview_ready", message: null, draft: built.draft, renderModel: renderModel, preview: true };
  }

  function approveSkill(session, skillApprovalMeta, options) {
    if (!requireStatus(session, STATUS_SKILL_REVIEW)) return fail("skill_not_approvable", session);
    var approved = SkillCandidate.approveCandidate(session.skillCandidate, skillApprovalMeta, options);
    if (!approved.ok) return fail(approved.code || "skill_approval_failed", session);
    var copy = cloneJson(session);
    copy.status = STATUS_SKILL_APPROVED;
    copy.approvedSkill = approved.skill;
    return ok("skill_approved", copy);
  }

  /* ── 6. atomic commit: template store + skill store 를 함께 쓰고 부분 실패 시 rollback ── */

  function snapshotKey(storage, key) {
    try {
      if (!storage || typeof storage.getItem !== "function") return { readable: false, value: null };
      var value = storage.getItem(key);
      return { readable: true, value: value === undefined ? null : value };
    } catch (err) {
      return { readable: false, value: null };
    }
  }

  function restoreKey(storage, key, snapshot) {
    if (!snapshot.readable) return false;
    try {
      if (snapshot.value === null || snapshot.value === undefined) {
        if (typeof storage.removeItem === "function") storage.removeItem(key);
      } else if (typeof storage.setItem === "function") {
        storage.setItem(key, snapshot.value);
      } else {
        return false;
      }
      return true;
    } catch (err) {
      return false;
    }
  }

  function commit(session, stores, storage, options) {
    var opts = options || {};
    if (!requireStatus(session, STATUS_SKILL_APPROVED)) return fail("skill_not_committable", session);
    if (!isPlainObject(stores) || !storage) return fail("commit_context_invalid", session);
    if (!session.approvedTemplate || !session.approvedSkill || !session.templateEvidence) {
      return fail("commit_context_invalid", session);
    }

    var templateSnap = snapshotKey(storage, TemplateStore.TEMPLATE_STORAGE_KEY);
    var skillSnap = snapshotKey(storage, SkillStore.STORAGE_KEY);

    var created = TemplateStore.createTemplate(stores.templateStore, {
      name: session.approvedTemplate.name,
      content: session.approvedTemplate.content
    }, {
      id: session.templateId,
      approval: session.templateEvidence,
      isDefault: false,
      now: stampOf(opts)
    });
    if (!created.ok || !created.template ||
        created.template.fingerprint !== session.approvedTemplate.fingerprint) {
      return fail(created.ok ? "template_commit_mismatch" : created.code, session);
    }

    var saved = SkillStore.saveApprovedSkill(stores.skillStore, session.approvedSkill);
    if (!saved.ok) return fail(saved.code || "skill_commit_failed", session);

    var templateWritten = false;
    try {
      if (!TemplateStore.writeStore(storage, created.store)) {
        throw new Error("template_store_write_failed");
      }
      templateWritten = true;
      if (!SkillStore.writeStore(storage, saved.store)) {
        throw new Error("skill_store_write_failed");
      }
    } catch (err) {
      var templateRestored = true;
      var skillRestored = true;
      if (templateWritten) templateRestored = restoreKey(storage, TemplateStore.TEMPLATE_STORAGE_KEY, templateSnap);
      skillRestored = restoreKey(storage, SkillStore.STORAGE_KEY, skillSnap);
      var rolledBack = templateRestored && skillRestored;
      var copy = cloneJson(session);
      copy.status = STATUS_FAILED;
      copy.error = "commit_write_failed";
      var result = fail("commit_write_failed", copy);
      result.rolledBack = rolledBack;
      result.templateRestored = templateRestored;
      result.skillRestored = skillRestored;
      return result;
    }

    var done = cloneJson(session);
    done.status = STATUS_COMMITTED;
    return ok("registration_committed", done, {
      templateStore: created.store,
      skillStore: saved.store,
      template: created.template,
      skill: saved.skill
    });
  }

  function cancel(session) {
    void session;
    var next = freshSession();
    next.status = STATUS_CANCELLED;
    return ok("registration_cancelled", next);
  }

  return {
    STATUS_IDLE: STATUS_IDLE,
    STATUS_TEMPLATE_REVIEW: STATUS_TEMPLATE_REVIEW,
    STATUS_TEMPLATE_APPROVED: STATUS_TEMPLATE_APPROVED,
    STATUS_SKILL_REVIEW: STATUS_SKILL_REVIEW,
    STATUS_SKILL_APPROVED: STATUS_SKILL_APPROVED,
    STATUS_COMMITTED: STATUS_COMMITTED,
    STATUS_CANCELLED: STATUS_CANCELLED,
    STATUS_FAILED: STATUS_FAILED,
    STEP_LABELS: STEP_LABELS.slice(),
    start: start,
    correctTemplate: correctTemplate,
    previewTemplate: previewTemplate,
    approveTemplate: approveTemplate,
    buildSkillCandidate: buildSkillCandidate,
    correctSkill: correctSkill,
    previewSkill: previewSkill,
    approveSkill: approveSkill,
    commit: commit,
    cancel: cancel
  };
});
