/* B66 · Quote Beta — quote-template-candidate.js
   QuoteTemplateCandidate 계약: 승인 전 검토 대상.

   - candidate 는 approved profile 이 아니다. 이름/상태/지문 어디에도 승인 의미를 담지 않는다.
   - 모르는 필드는 조용히 버리지 않고 명시적으로 거부한다(unsupported_candidate_field).
   - 파일 이름·경고·증거 문자열은 "데이터"이며 실행 가능한 지시가 아니다.
   - 실제 analyzer 는 아직 없다(#3185). 이 모듈은 manual/test 주입 seam 만 제공한다.

   (DOM 없음 · 브라우저/Node 양쪽에서 실행) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./quote-template.js"));
  } else {
    root.QuoteTemplateCandidate = factory(root.QuoteTemplate);
  }
})(typeof self !== "undefined" ? self : this, function (Template) {
  "use strict";

  if (!Template) throw new Error("QuoteTemplate is required");

  var CANDIDATE_SCHEMA_VERSION = 1;
  var MAX_CANDIDATE_NAME_CHARS = Template.MAX_TEMPLATE_NAME_CHARS;
  var MAX_SOURCE_NAME_CHARS = 160;
  var MAX_SOURCE_REF_CHARS = 256;
  var MAX_NOTE_ITEMS = 8;
  var MAX_NOTE_CHARS = 200;
  var MAX_EVIDENCE_ITEMS = 8;
  var MAX_EVIDENCE_LABEL_CHARS = 60;
  var MAX_EVIDENCE_VALUE_CHARS = 200;

  var CANDIDATE_KEYS = ["schemaVersion", "candidateId", "name", "content", "provenance", "review"];
  var PROVENANCE_KEYS = ["sourceKind", "sourceName", "sourceRef", "capturedAt"];
  var REVIEW_KEYS = ["warnings", "unknowns", "confidence", "evidence"];
  var SOURCE_KINDS = ["file", "manual", "sample"];
  var STATUS_CANDIDATE = "candidate";

  var LABEL_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/;
  var ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/;
  var ISO_UTC_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/;

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function fail(code, message) {
    return { ok: false, code: code, message: message || null, candidate: null };
  }

  function bound(value, max, fallback) {
    if (typeof value !== "string") return fallback;
    return value.slice(0, max);
  }

  function unknownKeys(source, allowed) {
    return Object.keys(source).filter(function (key) { return allowed.indexOf(key) === -1; });
  }

  /* ── analyzer boundary: 이번 단계에서는 live 가 아니다 ── */

  function analyzerBoundary() {
    return {
      kind: "quote-template-analyzer",
      live: false,
      model: "none",
      network: "none",
      acceptsSourceKinds: SOURCE_KINDS.slice(),
      produces: "QuoteTemplateCandidate",
      note: "실제 문서 분석기는 아직 연결되지 않았습니다. 검토·승인 흐름만 동작합니다."
    };
  }

  /* ── 정규화: 화이트리스트 + 명시적 거부 ── */

  function normalizeNotes(raw, field) {
    if (raw === undefined || raw === null) return [];
    if (!Array.isArray(raw)) return null;
    if (raw.length > MAX_NOTE_ITEMS) return null;
    var notes = [];
    for (var i = 0; i < raw.length; i += 1) {
      var entry = raw[i];
      if (!isPlainObject(entry)) return null;
      var extra = unknownKeys(entry, ["code", "message"]);
      if (extra.length > 0) return null;
      if (typeof entry.code !== "string" || !LABEL_PATTERN.test(entry.code)) return null;
      notes.push({
        code: entry.code,
        message: bound(entry.message, MAX_NOTE_CHARS, "")
      });
    }
    return notes;
  }

  function normalizeEvidence(raw) {
    if (raw === undefined || raw === null) return [];
    if (!Array.isArray(raw) || raw.length > MAX_EVIDENCE_ITEMS) return null;
    var items = [];
    for (var i = 0; i < raw.length; i += 1) {
      var entry = raw[i];
      if (!isPlainObject(entry)) return null;
      if (unknownKeys(entry, ["label", "value"]).length > 0) return null;
      if (typeof entry.label !== "string" || !entry.label.trim()) return null;
      items.push({
        label: bound(entry.label.trim(), MAX_EVIDENCE_LABEL_CHARS, ""),
        value: bound(entry.value, MAX_EVIDENCE_VALUE_CHARS, "")
      });
    }
    return items;
  }

  function normalizeProvenance(raw) {
    if (raw === undefined || raw === null) {
      return { sourceKind: "manual", sourceName: "", sourceRef: "", capturedAt: "" };
    }
    if (!isPlainObject(raw)) return null;
    if (unknownKeys(raw, PROVENANCE_KEYS).length > 0) return null;
    if (SOURCE_KINDS.indexOf(raw.sourceKind) === -1) return null;
    var capturedAt = typeof raw.capturedAt === "string" ? raw.capturedAt.trim() : "";
    if (capturedAt && !ISO_UTC_PATTERN.test(capturedAt)) return null;
    return {
      sourceKind: raw.sourceKind,
      /* 파일 이름은 표시용 데이터다. 절대 지시로 해석하지 않는다. */
      sourceName: bound(typeof raw.sourceName === "string" ? raw.sourceName.trim() : "", MAX_SOURCE_NAME_CHARS, ""),
      sourceRef: bound(typeof raw.sourceRef === "string" ? raw.sourceRef.trim() : "", MAX_SOURCE_REF_CHARS, ""),
      capturedAt: capturedAt
    };
  }

  function normalizeCandidateId(value, fallbackSeed) {
    if (typeof value === "string" && ID_PATTERN.test(value.trim())) return value.trim();
    var stamp = String(fallbackSeed == null ? "" : fallbackSeed).replace(/[^0-9]/g, "").slice(0, 17);
    var suffix = Math.random().toString(36).slice(2, 8);
    return "candidate-" + (stamp || "0") + "-" + suffix;
  }

  /* 손상/미지원 필드/금지 필드는 fail-closed. candidate 를 approved 처럼 만들지 않는다. */
  function normalizeCandidate(raw, options) {
    var opts = options || {};
    if (!isPlainObject(raw)) return fail("invalid_candidate", "candidate must be an object");
    if (raw.schemaVersion !== CANDIDATE_SCHEMA_VERSION) {
      return fail("invalid_candidate_schema", "candidate schema version is not supported");
    }

    /* 금지 필드(신뢰 합계·자격증명·원본 바이트)를 먼저 구분해 명시적으로 거부한다. */
    var forbidden = Template.findForbiddenKeys(raw);
    if (forbidden.length > 0) {
      return fail("forbidden_candidate_field", "candidate contains forbidden fields: " + forbidden.join(", "));
    }

    var extraTop = unknownKeys(raw, CANDIDATE_KEYS);
    if (extraTop.length > 0) {
      return fail("unsupported_candidate_field", "unsupported candidate field: " + extraTop.join(", "));
    }

    var content = Template.normalizeTemplateContent(raw.content);
    if (!content) return fail("invalid_candidate_content", "candidate content is not a valid template profile");

    var provenance = normalizeProvenance(raw.provenance);
    if (!provenance) return fail("invalid_candidate_provenance", "candidate provenance is not supported");

    var reviewSource = raw.review === undefined || raw.review === null ? {} : raw.review;
    if (!isPlainObject(reviewSource)) return fail("invalid_candidate_review", "candidate review must be an object");
    if (unknownKeys(reviewSource, REVIEW_KEYS).length > 0) {
      return fail("unsupported_candidate_field", "unsupported review field");
    }

    var warnings = normalizeNotes(reviewSource.warnings, "warnings");
    if (!warnings) return fail("invalid_candidate_review", "candidate warnings are not bounded");
    var unknowns = normalizeNotes(reviewSource.unknowns, "unknowns");
    if (!unknowns) return fail("invalid_candidate_review", "candidate unknowns are not bounded");
    var evidence = normalizeEvidence(reviewSource.evidence);
    if (!evidence) return fail("invalid_candidate_review", "candidate evidence is not bounded");

    var confidence = null;
    if (reviewSource.confidence !== undefined && reviewSource.confidence !== null) {
      var value = Number(reviewSource.confidence);
      if (!Number.isFinite(value) || value < 0 || value > 1) {
        return fail("invalid_candidate_confidence", "candidate confidence must be between 0 and 1");
      }
      confidence = value;
    }

    var name = typeof raw.name === "string" ? raw.name.trim() : "";
    if (!name) name = provenance.sourceName || "이름 없는 양식";
    name = name.slice(0, MAX_CANDIDATE_NAME_CHARS);

    var candidate = {
      schemaVersion: CANDIDATE_SCHEMA_VERSION,
      candidateId: normalizeCandidateId(raw.candidateId, opts.now),
      name: name,
      content: content,
      provenance: provenance,
      review: {
        warnings: warnings,
        unknowns: unknowns,
        confidence: confidence,
        evidence: evidence
      },
      contentFingerprint: Template.templateFingerprint(content),
      status: STATUS_CANDIDATE
    };

    return { ok: true, code: "candidate_ready", message: null, candidate: candidate };
  }

  /* ── manual/test 주입 seam: 검증을 반드시 거친다(곧바로 approved 가 되지 않는다) ── */

  function injectCandidate(payload, options) {
    return normalizeCandidate(payload, options);
  }

  /* ── 검토 화면 모델 ── */

  var SECTION_LABELS = {
    title: "제목",
    meta: "견적 정보",
    parties: "당사자",
    items: "품목 표",
    totals: "합계",
    memo: "비고",
    mark: "표시 문구"
  };

  function buildReviewModel(candidate) {
    if (!candidate || !isPlainObject(candidate.content)) return null;
    var content = candidate.content;
    var totals = content.totals || {};
    var provisional = totals.provisional || {};
    var page = content.page || {};
    var style = content.style || {};
    var slots = content.slots || {};

    return {
      candidateId: candidate.candidateId,
      name: candidate.name,
      status: STATUS_CANDIDATE,
      statusLabel: "승인 전",
      contentFingerprint: candidate.contentFingerprint,
      fingerprintShort: String(candidate.contentFingerprint || "").slice(0, 12),
      provenance: {
        sourceKind: candidate.provenance.sourceKind,
        sourceName: candidate.provenance.sourceName,
        capturedAt: candidate.provenance.capturedAt
      },
      sections: (content.sections || []).map(function (key) {
        return { key: key, label: SECTION_LABELS[key] || key };
      }),
      columns: (content.items && content.items.columns ? content.items.columns : []).map(function (column) {
        return { key: column.key, label: column.label, width: column.width, align: column.align };
      }),
      tax: {
        supplyLabel: totals.supplyLabel,
        grandLabel: totals.grandLabel,
        vatLabels: Object.assign({}, totals.vatLabels),
        provisional: {
          subtotalLabel: provisional.subtotalLabel,
          vatLabel: provisional.vatLabel,
          vatText: provisional.vatText,
          grandLabel: provisional.grandLabel,
          grandText: provisional.grandText
        }
      },
      text: {
        title: content.title ? content.title.text : "",
        emptyNameText: content.items ? content.items.emptyNameText : "",
        memoEmptyText: content.memo ? content.memo.emptyText : "",
        mark: content.mark ? content.mark.text : ""
      },
      layout: {
        page: page,
        style: style
      },
      slots: {
        support: Template.SLOT_SUPPORT,
        logo: slots.logo || "",
        stamp: slots.stamp || "",
        declared: Boolean(String(slots.logo || "") || String(slots.stamp || ""))
      },
      warnings: candidate.review.warnings.slice(),
      unknowns: candidate.review.unknowns.slice(),
      confidence: candidate.review.confidence,
      evidence: candidate.review.evidence.slice()
    };
  }

  /* candidate 를 승인 없이 profile 처럼 쓰지 못하게 하는 명시적 차단 */
  function isApprovedCandidate() {
    return false;
  }

  return {
    CANDIDATE_SCHEMA_VERSION: CANDIDATE_SCHEMA_VERSION,
    STATUS_CANDIDATE: STATUS_CANDIDATE,
    MAX_CANDIDATE_NAME_CHARS: MAX_CANDIDATE_NAME_CHARS,
    MAX_NOTE_ITEMS: MAX_NOTE_ITEMS,
    MAX_EVIDENCE_ITEMS: MAX_EVIDENCE_ITEMS,
    SECTION_LABELS: SECTION_LABELS,
    analyzerBoundary: analyzerBoundary,
    normalizeCandidate: normalizeCandidate,
    injectCandidate: injectCandidate,
    buildReviewModel: buildReviewModel,
    isApprovedCandidate: isApprovedCandidate
  };
});
