/* B66 · Quote Beta — quote-template-cloner.js
   "견적서 양식 본뜨기" 흐름의 상태 기계.

     source 선택 → bounded preflight → analyzer boundary → candidate
     → 검토 → 수정 → 명시적 승인 → Approved QuoteTemplateProfile 저장
     → (선택) 현재 견적 적용 / 기본 양식 지정

   절대 금지(계약):
   - candidate 자동 저장/자동 활성화/자동 기본 지정
   - 지문에 묶이지 않은 승인
   - 승인 후 내용이 바뀌었는데 승인이 살아남는 것
   - 실패/취소 경로에서 profile·default·selection 을 건드리는 것

   실제 analyzer/model/network 호출은 없다(#3185). candidate 는 검증된 주입 seam 으로만 들어온다.
   (DOM 없음 · 브라우저/Node 양쪽에서 실행) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(
      require("./quote-template.js"),
      require("./quote-template-store.js"),
      require("./quote-template-selection.js"),
      require("./quote-template-candidate.js")
    );
  } else {
    root.QuoteTemplateCloner = factory(
      root.QuoteTemplate,
      root.QuoteTemplateStore,
      root.QuoteTemplateSelection,
      root.QuoteTemplateCandidate
    );
  }
})(typeof self !== "undefined" ? self : this, function (Template, Store, Selection, Candidate) {
  "use strict";

  if (!Template) throw new Error("QuoteTemplate is required");
  if (!Store) throw new Error("QuoteTemplateStore is required");
  if (!Selection) throw new Error("QuoteTemplateSelection is required");
  if (!Candidate) throw new Error("QuoteTemplateCandidate is required");

  var CLONER_SCHEMA_VERSION = 1;
  var DEFAULT_APPROVER = "local-owner";
  var APPROVER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,127}$/;
  var MAX_SESSION_ID_CHARS = 64;

  var STATUS_IDLE = "idle";
  var STATUS_PREFLIGHT_OK = "preflight_ok";
  var STATUS_REVIEWING = "reviewing";
  var STATUS_APPROVED = "approved";
  var STATUS_CANCELLED = "cancelled";
  var STATUS_FAILED = "failed";

  var STATUS_LABELS = {};
  STATUS_LABELS[STATUS_IDLE] = "대기";
  STATUS_LABELS[STATUS_PREFLIGHT_OK] = "분석 대기";
  STATUS_LABELS[STATUS_REVIEWING] = "검토 중";
  STATUS_LABELS[STATUS_APPROVED] = "승인됨";
  STATUS_LABELS[STATUS_CANCELLED] = "취소됨";
  STATUS_LABELS[STATUS_FAILED] = "실패";

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function ok(code, session, extra) {
    return Object.assign({ ok: true, code: code, message: null, session: session }, extra || {});
  }

  function fail(code, message, session) {
    return { ok: false, code: code, message: message || null, session: session || null };
  }

  function stampOf(options) {
    var opts = options || {};
    return typeof opts.now === "string" && opts.now
      ? opts.now.slice(0, 40)
      : new Date().toISOString();
  }

  function makeSessionId(seed) {
    var stamp = String(seed == null ? "" : seed).replace(/[^0-9]/g, "").slice(0, 17);
    var suffix = Math.random().toString(36).slice(2, 8);
    return ("clone-" + (stamp || "0") + "-" + suffix).slice(0, MAX_SESSION_ID_CHARS);
  }

  function createSession(options) {
    var opts = options || {};
    return {
      schemaVersion: CLONER_SCHEMA_VERSION,
      sessionId: typeof opts.sessionId === "string" && opts.sessionId ? opts.sessionId.slice(0, MAX_SESSION_ID_CHARS) : makeSessionId(opts.now),
      status: STATUS_IDLE,
      source: null,
      candidate: null,
      reviewedFingerprint: null,
      approval: null,
      error: null
    };
  }

  /* ── 1) 파일 선택 + bounded preflight 재사용 ── */

  function startFromFile(session, preflight, options) {
    var base = session || createSession(options);
    if (!isPlainObject(preflight)) {
      return fail("invalid_preflight", "preflight result is missing", base);
    }
    if (preflight.ok !== true) {
      return fail(
        typeof preflight.error === "string" ? preflight.error : "preflight_failed",
        "파일 사전 검증에 실패했습니다.",
        Object.assign({}, base, {
          status: STATUS_FAILED,
          source: null,
          candidate: null,
          reviewedFingerprint: null,
          approval: null,
          error: { code: typeof preflight.error === "string" ? preflight.error : "preflight_failed" }
        })
      );
    }

    var next = Object.assign({}, base, {
      status: STATUS_PREFLIGHT_OK,
      source: {
        kind: "file",
        name: typeof preflight.name === "string" ? preflight.name.slice(0, 160) : "",
        preflight: {
          extension: preflight.extension || "",
          media: preflight.media || "",
          size: preflight.size == null ? null : preflight.size
        }
      },
      candidate: null,
      reviewedFingerprint: null,
      approval: null,
      error: null
    });
    return ok("preflight_ok", next, { analyzer: Candidate.analyzerBoundary() });
  }

  /* ── 2) analyzer boundary → candidate (주입 seam, 반드시 계약 검증을 거친다) ── */

  function startFromCandidate(session, payload, options) {
    var base = session || createSession(options);
    var opts = options || {};

    var merged = payload;
    if (isPlainObject(payload) && isPlainObject(base.source) && payload.provenance === undefined) {
      merged = Object.assign({}, payload, {
        provenance: {
          sourceKind: "file",
          sourceName: base.source.name || "",
          capturedAt: stampOf(opts)
        }
      });
    }

    var injected = Candidate.injectCandidate(merged, opts);
    if (!injected.ok) {
      return fail(
        injected.code,
        injected.message,
        Object.assign({}, base, {
          status: STATUS_FAILED,
          candidate: null,
          reviewedFingerprint: null,
          approval: null,
          error: { code: injected.code }
        })
      );
    }

    var candidate = injected.candidate;
    var next = Object.assign({}, base, {
      status: STATUS_REVIEWING,
      candidate: candidate,
      reviewedFingerprint: candidate.contentFingerprint,
      approval: null,
      error: null
    });
    return ok("reviewing", next, { review: Candidate.buildReviewModel(candidate) });
  }

  /* ── 3) 검토 중 수정: 승인 전에는 자유, 승인 후 내용이 바뀌면 승인 무효 ── */

  function editCandidate(session, patch, options) {
    if (!session) return fail("invalid_session", "session is missing");
    if (session.status !== STATUS_REVIEWING && session.status !== STATUS_APPROVED) {
      return fail("session_not_editable", "candidate is not under review", session);
    }
    if (!session.candidate) return fail("candidate_missing", "no candidate to edit", session);
    if (!isPlainObject(patch)) return fail("invalid_patch", "patch must be an object", session);

    /* 검토 중 이름을 비우는 것은 허용하지 않는다(조용한 기본값 대체 금지). */
    if (patch.name !== undefined) {
      var nextName = typeof patch.name === "string" ? patch.name.trim() : "";
      if (!nextName) return fail("invalid_candidate_name", "양식 이름을 입력해 주세요.", session);
    }

    var rebuilt = Candidate.normalizeCandidate(
      {
        schemaVersion: Candidate.CANDIDATE_SCHEMA_VERSION,
        candidateId: session.candidate.candidateId,
        name: patch.name === undefined ? session.candidate.name : patch.name,
        content: patch.content === undefined ? session.candidate.content : patch.content,
        provenance: session.candidate.provenance,
        review: session.candidate.review
      },
      options
    );
    if (!rebuilt.ok) return fail(rebuilt.code, rebuilt.message, session);

    var candidate = rebuilt.candidate;
    var contentChanged = candidate.contentFingerprint !== session.reviewedFingerprint;

    if (!contentChanged) {
      return ok("edited", Object.assign({}, session, { candidate: candidate }), {
        review: Candidate.buildReviewModel(candidate)
      });
    }

    var next = Object.assign({}, session, {
      status: STATUS_REVIEWING,
      candidate: candidate,
      reviewedFingerprint: candidate.contentFingerprint,
      approval: null
    });

    /* 승인된 뒤 내용이 바뀌면 저장된 profile 의 승인도 무효화한다(조용한 승인 유지 금지). */
    if (session.status === STATUS_APPROVED && session.approval && options && options.storage) {
      var updated = Store.updateTemplate(
        Store.readStore(options.storage),
        session.approval.templateId,
        { content: candidate.content },
        { now: stampOf(options) }
      );
      if (!updated.ok) return fail(updated.code, updated.message, session);
      if (!Store.writeStore(options.storage, updated.store)) {
        return fail("template_storage_failed", "양식을 저장하지 못했습니다.", session);
      }
      next.approval = null;
      next.error = null;
      return ok("approval_invalidated", next, { review: Candidate.buildReviewModel(candidate) });
    }

    return ok("edited", next, { review: Candidate.buildReviewModel(candidate) });
  }

  /* ── 4) 명시적 승인: 사용자가 눌러야만 profile 이 저장된다 ── */

  function approveCandidate(session, storage, options) {
    var opts = options || {};
    if (!session) return fail("invalid_session", "session is missing");
    if (session.status !== STATUS_REVIEWING) return fail("session_not_reviewable", "candidate is not under review", session);
    if (!session.candidate) return fail("candidate_missing", "no candidate to approve", session);

    /* 승인 직전에 보여준 내용과 지금 내용이 같아야 한다(지문 결속). */
    var current = Template.templateFingerprint(session.candidate.content);
    if (!session.reviewedFingerprint || current !== session.reviewedFingerprint) {
      return Object.assign(
        fail("candidate_changed_after_review", "검토 후 내용이 바뀌어 승인할 수 없습니다.", session),
        { changed: true }
      );
    }

    var approver = typeof opts.approver === "string" && APPROVER_PATTERN.test(opts.approver.trim())
      ? opts.approver.trim()
      : DEFAULT_APPROVER;
    var approvedAt = stampOf(opts);

    var evidence = {
      schemaVersion: Template.APPROVAL_SCHEMA_VERSION,
      status: "approved",
      contentFingerprint: current,
      approvedBy: approver,
      approvedAt: approvedAt
    };

    var store = Store.readStore(storage);
    var created = Store.createTemplate(
      store,
      { name: session.candidate.name, content: session.candidate.content },
      { id: opts.id, approval: evidence, now: approvedAt }
    );
    /* 실패하면 아무것도 쓰지 않는다 — profile/default/selection 모두 그대로다. */
    if (!created.ok) return fail(created.code, created.message, session);
    if (!Store.writeStore(storage, created.store)) {
      return fail("template_storage_failed", "양식을 저장하지 못했습니다.", session);
    }

    var templateId = created.template.id;
    var applied = null;
    var defaulted = null;

    if (opts.applyToQuoteNo) {
      var selected = Selection.selectTemplate(storage, opts.applyToQuoteNo, templateId, { now: approvedAt });
      applied = selected.ok ? templateId : null;
      if (!selected.ok) return fail(selected.code, selected.message, session);
    }
    if (opts.setAsDefault === true) {
      var defaultedResult = Selection.setDefaultTemplate(storage, templateId);
      if (!defaultedResult.ok) return fail(defaultedResult.code, defaultedResult.message, session);
      defaulted = templateId;
    }

    var next = Object.assign({}, session, {
      status: STATUS_APPROVED,
      approval: {
        templateId: templateId,
        contentFingerprint: current,
        approvedBy: approver,
        approvedAt: approvedAt
      },
      error: null
    });

    return ok("approved", next, {
      template: created.template,
      applied: applied,
      defaulted: defaulted
    });
  }

  /* ── 5) 취소: 아무것도 쓰지 않는다 ── */

  function cancelSession(session) {
    if (!session) return fail("invalid_session", "session is missing");
    var next = Object.assign({}, session, {
      status: STATUS_CANCELLED,
      candidate: null,
      reviewedFingerprint: null,
      approval: null,
      error: null
    });
    return ok("cancelled", next);
  }

  /* ── 표시용 요약 ── */

  function statusLabel(session) {
    if (!session) return STATUS_LABELS[STATUS_IDLE];
    return STATUS_LABELS[session.status] || session.status;
  }

  function buildProgress(session) {
    var status = session ? session.status : STATUS_IDLE;
    var steps = [
      { key: "source", label: "파일 선택", done: Boolean(session && session.source) },
      { key: "analyze", label: "양식 분석", done: status === STATUS_REVIEWING || status === STATUS_APPROVED },
      { key: "review", label: "검토", done: status === STATUS_REVIEWING || status === STATUS_APPROVED },
      { key: "approve", label: "승인", done: status === STATUS_APPROVED }
    ];
    return steps;
  }

  return {
    CLONER_SCHEMA_VERSION: CLONER_SCHEMA_VERSION,
    DEFAULT_APPROVER: DEFAULT_APPROVER,
    STATUS_IDLE: STATUS_IDLE,
    STATUS_PREFLIGHT_OK: STATUS_PREFLIGHT_OK,
    STATUS_REVIEWING: STATUS_REVIEWING,
    STATUS_APPROVED: STATUS_APPROVED,
    STATUS_CANCELLED: STATUS_CANCELLED,
    STATUS_FAILED: STATUS_FAILED,
    STATUS_LABELS: STATUS_LABELS,
    createSession: createSession,
    startFromFile: startFromFile,
    startFromCandidate: startFromCandidate,
    editCandidate: editCandidate,
    approveCandidate: approveCandidate,
    cancelSession: cancelSession,
    statusLabel: statusLabel,
    buildProgress: buildProgress
  };
});
