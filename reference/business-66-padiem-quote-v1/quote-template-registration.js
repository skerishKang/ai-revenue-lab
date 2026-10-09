/* B66 · Quote Beta — quote-template-registration.js
   업로드된 기존 견적서의 문서/레이아웃을 Approved QuoteTemplateProfile 로 만드는 등록 경로.

   정직한 전제:
   - 브라우저에는 live layout analyzer 가 없다(quote-template-candidate analyzerBoundary 참조).
     파일 intake 가 주는 bounded metadata(이름/형식/크기)만으로 초안 candidate 를 만들고,
     레이아웃은 사용자가 직접 보정한다. FIRST_REGISTRATION_MAY_BE_SLOW=YES.
   - 보정 가능 항목은 renderer 가 실제 지원하는 schema 로만 한정한다.
     렌더러가 지원하지 않는 값(예: live 로고/도장 슬롯)은 NOT_SUPPORTED 로 거부한다.
   - preview 는 저장소 변경 없이 동일 renderer 로만 수행하고, 미승인 preview 임을
     renderModel 에 명시한다.

   (DOM 없음 · 브라우저/Node 양쪽에서 실행) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(
      require("./quote-template.js"),
      require("./quote-template-candidate.js"),
      require("./quote-template-store.js"),
      require("./quote-template-renderer.js"),
      require("./quote-core.js"),
      require("./file-intake.js")
    );
  } else {
    root.QuoteTemplateRegistration = factory(
      root.QuoteTemplate,
      root.QuoteTemplateCandidate,
      root.QuoteTemplateStore,
      root.QuoteTemplateRenderer,
      root.QuoteCore,
      root.B66FileIntake
    );
  }
})(typeof self !== "undefined" ? self : this, function (Template, Candidate, Store, Renderer, Core, FileIntake) {
  "use strict";

  if (!Template) throw new Error("QuoteTemplate is required");
  if (!Candidate) throw new Error("QuoteTemplateCandidate is required");
  if (!Store) throw new Error("QuoteTemplateStore is required");
  if (!Renderer) throw new Error("QuoteTemplateRenderer is required");
  if (!Core) throw new Error("QuoteCore is required");
  if (!FileIntake) throw new Error("B66FileIntake is required");

  var MAX_SOURCE_NAME_CHARS = 160;
  var MAX_FILENAME_CHARS = 255;

  /* 등록 화면에 내보내는 정직한 문구. 자동 학습 완료 취지의 과장 표현을 금지한다. */
  var DRAFT_NOTE = "기본 견적서 초안을 준비했습니다. 현재는 원본 견적서의 모양을 자동으로 분석하지 않으므로, 실제 사용 중인 견적서와 비교해 필요한 부분을 수정해 주세요.";
  var SEED_WARNING = "manual_layout_review_required";
  var SEED_UNKNOWN = "layout";

  var CORRECTION_KEYS = ["name", "content", "warnings", "unknowns", "evidence"];

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function fail(code, message) {
    return { ok: false, code: code, message: message || null, candidate: null, review: null };
  }

  function stampOf(options) {
    var opts = options || {};
    return typeof opts.now === "string" && opts.now
      ? opts.now.slice(0, 40)
      : new Date().toISOString();
  }

  function sanitizeFileBase(filename) {
    if (typeof filename !== "string") return "";
    var base = filename.split(/[\/\\]/).pop().trim();
    base = base.replace(/\.[A-Za-z0-9]{1,8}$/, "").trim();
    return base.slice(0, 60);
  }

  function normalizeSourceInfo(raw) {
    if (!isPlainObject(raw)) return null;
    if (typeof raw.filename !== "string" || !raw.filename.trim()) return null;
    var filename = raw.filename.trim().slice(0, MAX_FILENAME_CHARS);
    var mediaType = typeof raw.mediaType === "string" ? raw.mediaType.trim().slice(0, 120) : "";
    var byteSize = raw.byteSize === undefined || raw.byteSize === null ? null : Number(raw.byteSize);
    if (byteSize !== null && (!Number.isFinite(byteSize) || byteSize < 0)) return null;
    return { filename: filename, mediaType: mediaType, byteSize: byteSize };
  }

  /* ── 1. source metadata → 초안 candidate (builtin 복제 + 파일명, 원본 바이트 없음) ── */

  function buildTemplateCandidateFromSource(sourceInfo, options) {
    var opts = options || {};
    var source = normalizeSourceInfo(sourceInfo);
    if (!source) return fail("invalid_source_info");
    /* Saved Quote Skill fact-extraction wizard accepts reference documents
       (PDF, DOCX, image, etc.) but seeds the built-in/manual-review layout.
       It must not be mistaken for approved source-faithful template cloning.
       Source-template registration itself remains XLSX only. */
    var accepted = opts.sourceMode === "fact_reference"
      ? FileIntake.classifyFile({
          name: source.filename, type: source.mediaType, size: source.byteSize
        })
      : FileIntake.validateTemplateSourcePreflight({
          ok: true, filename: source.filename, mediaType: source.mediaType, byteSize: source.byteSize
        });
    if (!accepted.ok) return fail(accepted.error || "template_source_format_not_allowed");
    var base = sanitizeFileBase(source.filename);
    var content = cloneJson(Template.builtInTemplate().content);
    var injected = Candidate.injectCandidate({
      schemaVersion: 1,
      candidateId: opts.candidateId,
      name: base || "내 견적서 양식",
      content: content,
      provenance: {
        sourceKind: "file",
        sourceName: source.filename.slice(0, MAX_SOURCE_NAME_CHARS),
        sourceRef: source.mediaType ? ("media:" + source.mediaType).slice(0, 256) : "",
        capturedAt: stampOf(opts)
      },
      review: {
        warnings: [{ code: SEED_WARNING, message: DRAFT_NOTE.slice(0, 200) }],
        unknowns: [{ code: SEED_UNKNOWN, message: "columns, labels, page rules need review" }],
        confidence: null,
        evidence: []
      }
    }, opts);
    if (!injected.ok) return fail(injected.code || "invalid_template_candidate");
    return {
      ok: true,
      code: "template_candidate_ready",
      message: null,
      candidate: injected.candidate,
      review: Candidate.buildReviewModel(injected.candidate),
      draftNote: DRAFT_NOTE
    };
  }

  /* ── 2. manual correction: 전체 content 교체 + 이름/검토메모 (지원 schema 로만 검증) ── */

  function correctTemplateCandidate(candidate, patch, options) {
    var opts = options || {};
    if (!candidate || candidate.status !== Candidate.STATUS_CANDIDATE || !isPlainObject(patch)) {
      return fail("candidate_not_editable");
    }
    var extra = Object.keys(patch).filter(function (key) { return CORRECTION_KEYS.indexOf(key) === -1; });
    if (extra.length > 0) return fail("unsupported_template_correction");
    var rebuilt = Candidate.injectCandidate({
      schemaVersion: 1,
      candidateId: candidate.candidateId,
      name: patch.name === undefined ? candidate.name : patch.name,
      content: patch.content === undefined ? candidate.content : patch.content,
      provenance: candidate.provenance,
      review: {
        warnings: patch.warnings === undefined ? candidate.review.warnings : patch.warnings,
        unknowns: patch.unknowns === undefined ? candidate.review.unknowns : patch.unknowns,
        confidence: candidate.review.confidence,
        evidence: patch.evidence === undefined ? candidate.review.evidence : patch.evidence
      }
    }, opts);
    if (!rebuilt.ok) return fail(rebuilt.code || "invalid_template_correction");
    return {
      ok: true,
      code: "template_candidate_corrected",
      message: null,
      candidate: rebuilt.candidate,
      review: Candidate.buildReviewModel(rebuilt.candidate)
    };
  }

  /* ── 3. preview: 저장소 변경 없이 동일 renderer. 미승인 preview 임을 모델에 명시 ── */

  function previewTemplateCandidate(candidate, draft, options) {
    var opts = options || {};
    if (!candidate || candidate.status !== Candidate.STATUS_CANDIDATE || !isPlainObject(candidate.content)) {
      return { ok: false, code: "candidate_not_previewable", message: null, renderModel: null };
    }
    var profile = Template.buildProfile({
      id: "preview-unapproved-candidate",
      name: candidate.name,
      builtin: false,
      isDefault: false,
      approval: null,
      createdAt: "",
      updatedAt: "",
      content: candidate.content
    });
    var renderModel = Renderer.buildRenderModel(draft, Template.serializeTemplate(profile),
      { previewUnapprovedCandidate: true, taxReviewRequired: opts.taxReviewRequired === true });
    if (!renderModel) return { ok: false, code: "preview_render_failed", message: null, renderModel: null };
    if (renderModel.template.fallbackReason !== "preview_unapproved_candidate") {
      return { ok: false, code: "preview_not_marked", message: null, renderModel: null };
    }
    return {
      ok: true,
      code: "preview_ready",
      message: null,
      renderModel: renderModel,
      contentFingerprint: candidate.contentFingerprint
    };
  }

  /* ── 4. explicit approval → Approved QuoteTemplateProfile (store 기록, 기본값 변경 없음) ── */

  function approveTemplateCandidate(candidate, rawStore, evidenceMeta, options) {
    var opts = options || {};
    var meta = isPlainObject(evidenceMeta) ? evidenceMeta : {};
    if (!candidate || candidate.status !== Candidate.STATUS_CANDIDATE) {
      return { ok: false, code: "candidate_not_approvable", message: null, store: null, template: null };
    }
    var approvedAt = typeof meta.approvedAt === "string" && meta.approvedAt
      ? meta.approvedAt.slice(0, 40)
      : stampOf(opts);
    var created = Store.createTemplate(rawStore, {
      name: candidate.name,
      content: candidate.content
    }, {
      id: meta.id,
      approval: {
        schemaVersion: Template.APPROVAL_SCHEMA_VERSION,
        status: "approved",
        contentFingerprint: candidate.contentFingerprint,
        approvedBy: meta.approvedBy,
        approvedAt: approvedAt,
        approvalRef: typeof meta.approvalRef === "string" ? meta.approvalRef : ""
      },
      isDefault: false,
      now: approvedAt
    });
    if (!created.ok) {
      return { ok: false, code: created.code || "template_approval_failed", message: null, store: null, template: null };
    }
    if (!created.template || created.template.approved !== true ||
        created.template.fingerprint !== candidate.contentFingerprint) {
      return { ok: false, code: "template_approval_failed", message: null, store: null, template: null };
    }
    return { ok: true, code: "template_approved", message: null, store: created.store, template: created.template };
  }

  return {
    DRAFT_NOTE: DRAFT_NOTE,
    SEED_WARNING: SEED_WARNING,
    SEED_UNKNOWN: SEED_UNKNOWN,
    CORRECTION_KEYS: CORRECTION_KEYS.slice(),
    buildTemplateCandidateFromSource: buildTemplateCandidateFromSource,
    correctTemplateCandidate: correctTemplateCandidate,
    previewTemplateCandidate: previewTemplateCandidate,
    approveTemplateCandidate: approveTemplateCandidate
  };
});
