/* legal-evidence-provenance.js — LEGAL-SPECIFIC evidence decoration.
 *
 * This is the decorator the generic shared card (js/claw-evidence.js) calls
 * into. It adds the two things a lawyer needs and a generic chat does not:
 *
 *   1. an AUTHORITY BADGE — is this official primary authority, a party
 *      document, a firm work product, or secondary commentary?
 *   2. a PROVENANCE BLOCK — the record that ties a claim to an exact location
 *      inside an exact document, with its retrieval time and version.
 *
 * Both are Legal decisions. Deleting this file removes all Legal specificity
 * from the evidence surface and leaves a working generic grounded-research UI.
 */
(function (global) {
  "use strict";

  var el = global.ClawShell.el;
  var Legal = global.B67Legal;

  /* Fields the reviewer can check against the backend contract. Rendered as a
   * labelled list so a missing field is visibly missing rather than silently
   * absent. */
  var FIELD_LABELS = {
    source_type: "출처 유형",
    source_id: "출처 ID",
    title: "제목",
    authority_class: "자료 구분",
    document_id: "문서 ID",
    page_or_section: "위치",
    retrieved_at: "확인 시각",
    effective_date_or_version: "시행·버전",
    url_or_drive_ref: "참조",
    quote_span: "인용 구간"
  };

  function authorityBadge(record) {
    return el("span", {
      class: "auth-badge",
      "data-authority": record.authority_class || "secondary",
      text: Legal.authorityLabel(record.authority_class)
    });
  }

  function sourceChip(record) {
    return el("span", {
      class: "src-chip",
      "data-source-type": record.source_type || "web",
      text: Legal.sourceTypeLabel(record.source_type)
    });
  }

  function provRow(key, value) {
    var dd;
    if (value === undefined || value === null || String(value).trim() === "") {
      dd = el("dd", null, [
        el("em", { class: "prov-pending", text: "미연결" })
      ]);
    } else {
      dd = el("dd", null, [el("code", { text: String(value) })]);
    }
    return el("div", { class: "prov-row" }, [el("dt", { text: FIELD_LABELS[key] || key }), dd]);
  }

  function provenanceBlock(record, onLocator) {
    var gaps = Legal.provenanceGaps(record);

    var block = el("dl", { class: "prov" }, [
      el("p", { class: "prov-head" }, [
        el("span", { "aria-hidden": "true", text: "⌖" }),
        el("span", { text: "근거 위치 (provenance)" })
      ])
    ]);

    /* The page/section locator is a TARGET, not a verified result.
     *
     * Verified against the repo: the evidence graph carries no page/section
     * field at all. A page number is only meaningful once a document-segment
     * locator is joined onto it. So the locator is rendered as an unverified
     * affordance, explicitly, and the model never appears to have produced a
     * page number. */
    if (record.page_or_section) {
      var locatorRow = el("div", { class: "prov-row" }, [
        el("dt", { text: FIELD_LABELS.page_or_section }),
        el("dd", null, [
          el("button", {
            type: "button",
            class: "prov-locator",
            "data-verified": "false",
            "aria-label": (record.title || "근거") + " " + record.page_or_section +
              " 위치 보기 — 검증된 위치가 아닙니다",
            onClick: function () { onLocator(record); }
          }, [
            el("span", { text: record.page_or_section }),
            el("span", { class: "prov-pending", text: " 미검증" })
          ])
        ])
      ]);
      block.appendChild(locatorRow);
    }

    ["document_id", "source_id", "retrieved_at", "effective_date_or_version", "quote_span"].forEach(function (key) {
      block.appendChild(provRow(key, record[key]));
    });

    if (gaps.length) {
      block.appendChild(el("p", {
        class: "ev-empty-body",
        text: "연결 대기 중인 provenance 필드: " + gaps.join(", ")
      }));
    }

    return block;
  }

  /* Completion read-out. A reviewer must be able to tell, without opening the
   * record, whether it is safe to rely on. Field completeness and provenance
   * verification are reported as two DIFFERENT things on purpose: every field
   * can be filled and the page link still be unverified. */
  function statusLine(record) {
    var gaps = Legal.provenanceGaps(record);
    var out = [];

    if (record.provenance_verified) {
      out.push("provenance 검증 완료.");
    } else {
      out.push(global.B67Demo ? global.B67Demo.PROVENANCE_NOTE : "provenance 미검증.");
    }

    if (gaps.length) {
      out.push("필수 필드 " + gaps.length + "종 미연결.");
    }

    return el("p", {
      class: "ev-empty-body",
      style: "color: var(--gold);",
      text: out.join(" ")
    });
  }

  function createDecorator(opts) {
    var options = opts || {};
    var onLocator = options.onLocator || function () {};

    return function decorate(record, ctx) {
      var head = [authorityBadge(record), sourceChip(record)];

      /* Surface-level DEMO marker. This surface renders no real data, and the
       * card says so rather than relying on a single banner elsewhere. */
      if (record.demo) {
        head.push(el("span", { class: "demo-label", text: "DEMO" }));
      }

      return {
        head: head,
        body: [provenanceBlock(record, onLocator), statusLine(record)],
        /* The card's rail is styled off these. They travel through the generic
         * card's decorator seam so the shared card never learns the vocabulary
         * `authority_class` / `source_type`. */
        attrs: [
          ["data-authority", record.authority_class || "secondary"],
          ["data-source-type", record.source_type || "web"]
        ]
      };
    };
  }

  global.B67LegalEvidence = {
    FIELD_LABELS: FIELD_LABELS,
    createDecorator: createDecorator,
    authorityBadge: authorityBadge,
    sourceChip: sourceChip
  };
})(window);
