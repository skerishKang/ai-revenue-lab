/* legal-authority.js — LEGAL-SPECIFIC domain logic for the Padiem Legal vertical.
 *
 * This module owns everything Legal decides and Claw must not:
 *   1. what a source scope MEANS (which corpora it routes to),
 *   2. how an authority class is named and ordered,
 *   3. how a provenance record is judged complete enough to display,
 *   4. the fail-closed predicate.
 *
 * It is deliberately free of DOM code so it can be unit-tested and later moved
 * into a Legal capability module under Claw unchanged. The shared shell calls
 * into it; it never reaches into the shell.
 *
 * It contains NO second search engine, NO evidence graph, and NO verifier.
 * Those are shared authorities that already exist in the repo and are reused
 * by the backend later:
 *   grounding        apps/padiem-chat/app/grounding.py, grounding_runtime.py
 *   evidence graph   packages/padiem-ai-core/padiem_ai_core/evidence_graph.py
 *   verification     .../evidence_verification.py
 *   Drive read       .../drive_capability.py
 */
(function (global) {
  "use strict";

  /* ── Source scopes ────────────────────────────────────────────────────
   * `routable` marks whether a backend route is proven to exist yet. On this
   * static surface every scope is unproven, which is why the UI says so.
   */
  var SCOPES = [
    {
      id: "unified",
      label: "통합",
      icon: "◈",
      description: "공식 법률자료 · 내 Drive · 웹을 함께 검색합니다.",
      corpora: ["official", "drive", "web"],
      routable: false,
      note: "검색 라우터 미연결 — 이 화면에서는 범위만 선택됩니다."
    },
    {
      id: "official",
      label: "공식 법률자료",
      icon: "⚖",
      description: "법령·판례 등 공식 1차자료만 대상으로 합니다.",
      corpora: ["official"],
      routable: false,
      note: "공식 법률 소스 커넥터 미구현 — 법령·판례 API는 아직 연결되지 않았습니다."
    },
    {
      id: "drive",
      label: "내 Drive",
      icon: "▤",
      description: "선택한 사건 자료실의 문서만 대상으로 합니다.",
      corpora: ["drive"],
      routable: false,
      note: "Drive 읽기 권한은 기존 공용 커넥터에 있습니다. 사건 폴더 단위 범위 강제는 후속 작업입니다."
    },
    {
      id: "web",
      label: "웹",
      icon: "◍",
      description: "공개 웹에서 찾은 자료를 2차자료로 다룹니다.",
      corpora: ["web"],
      routable: false,
      note: "바운디드 웹 검색 런타임은 이미 존재하나 본 화면에 연결되지 않았습니다."
    }
  ];

  /* Authority ordering, strongest first. Used to sort the evidence panel so a
   * secondary source can never visually outrank official primary authority. */
  var AUTHORITY_RANK = { primary: 0, party: 1, internal: 2, secondary: 3 };

  var AUTHORITY_LABEL = {
    primary: "1차자료",
    party: "당사자 문서",
    internal: "내부 산출물",
    secondary: "2차자료"
  };

  var SOURCE_TYPE_LABEL = {
    official: "공식 법률자료",
    drive: "내 Drive",
    web: "웹",
    internal: "법무 산출물"
  };

  /* Fields the backend must supply for an evidence record to be displayable.
   * Mirrors CENTRAL's provenance contract for Legal. */
  var REQUIRED_PROVENANCE = [
    "source_type",
    "source_id",
    "title",
    "authority_class",
    "retrieved_at",
    "url_or_drive_ref"
  ];

  /* Fields a document-backed record additionally needs. */
  var REQUIRED_DOCUMENT_PROVENANCE = REQUIRED_PROVENANCE.concat([
    "document_id",
    "page_or_section"
  ]);

  function scopeById(id) {
    for (var i = 0; i < SCOPES.length; i += 1) {
      if (SCOPES[i].id === id) return SCOPES[i];
    }
    return SCOPES[0];
  }

  function authorityLabel(cls) {
    return AUTHORITY_LABEL[cls] || "미분류";
  }

  function sourceTypeLabel(type) {
    return SOURCE_TYPE_LABEL[type] || type || "미분류";
  }

  function rank(cls) {
    return Object.prototype.hasOwnProperty.call(AUTHORITY_RANK, cls)
      ? AUTHORITY_RANK[cls]
      : 99;
  }

  /* Sort strongest-authority first, then by original evidence number so the
   * [1] [2] [3] markers in the answer always line up with panel order. */
  function sortEvidence(list) {
    return list.slice().sort(function (a, b) {
      var d = rank(a.authority_class) - rank(b.authority_class);
      return d !== 0 ? d : a.n - b.n;
    });
  }

  function missingProvenance(record, required) {
    var fields = required || REQUIRED_PROVENANCE;
    var missing = [];
    for (var i = 0; i < fields.length; i += 1) {
      var v = record[fields[i]];
      if (v === undefined || v === null || String(v).trim() === "") {
        missing.push(fields[i]);
      }
    }
    return missing;
  }

  /* A record needs the document-level contract only when it actually points at
   * a document. Web commentary legitimately has no document_id. */
  function provenanceGaps(record) {
    var required = record.source_type === "web"
      ? REQUIRED_PROVENANCE
      : REQUIRED_DOCUMENT_PROVENANCE;
    return missingProvenance(record, required);
  }

  function isProvenanceComplete(record) {
    return provenanceGaps(record).length === 0;
  }

  /* ── Fail-closed predicate ─────────────────────────────────────────────
   * The single most important rule in this product: an answer is only produced
   * when at least one usable evidence record exists. This mirrors the existing
   * grounding runtime's zero-evidence behaviour in the canonical app; it is
   * restated here so the static surface can demonstrate the state, not because
   * it replaces the runtime rule.
   */
  function shouldFailClosed(evidence) {
    if (!evidence || evidence.length === 0) return true;
    return evidence.every(function (record) {
      return !isProvenanceComplete(record);
    });
  }

  /* Claim-to-evidence link: which evidence numbers support a given claim. */
  function evidenceNumbers(answer) {
    if (!answer || !answer.evidence_nums) return [];
    return answer.evidence_nums.slice().sort(function (a, b) { return a - b; });
  }

  global.B67Legal = {
    SCOPES: SCOPES,
    AUTHORITY_RANK: AUTHORITY_RANK,
    AUTHORITY_LABEL: AUTHORITY_LABEL,
    SOURCE_TYPE_LABEL: SOURCE_TYPE_LABEL,
    REQUIRED_PROVENANCE: REQUIRED_PROVENANCE,
    REQUIRED_DOCUMENT_PROVENANCE: REQUIRED_DOCUMENT_PROVENANCE,
    scopeById: scopeById,
    authorityLabel: authorityLabel,
    sourceTypeLabel: sourceTypeLabel,
    rank: rank,
    sortEvidence: sortEvidence,
    missingProvenance: missingProvenance,
    provenanceGaps: provenanceGaps,
    isProvenanceComplete: isProvenanceComplete,
    shouldFailClosed: shouldFailClosed,
    evidenceNumbers: evidenceNumbers
  };
})(window);
