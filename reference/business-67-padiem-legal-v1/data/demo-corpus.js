/* demo-corpus.js — MOCK DATA for the B67 static review surface.
 *
 * ⚠ NOTHING IN THIS FILE IS REAL. ⚠
 *
 * No case, statute, party, court, document, date, page number, or quotation
 * below refers to a real matter, real client, or real judgment. Every record is
 * invented for layout review. The "샘플"/"DEMO" markers are load-bearing: they
 * are the reason this file is safe to open.
 *
 * The SHAPE is not invented, though — each evidence record carries exactly the
 * provenance contract CENTRAL specified for Legal:
 *
 *   source_type, source_id, title, authority_class, document_id,
 *   page_or_section, retrieved_at, effective_date_or_version,
 *   url_or_drive_ref, quote_span
 *
 * A future backend fills these in. This file proves the UI can render them
 * without the model ever inventing a page number.
 */
(function (global) {
  "use strict";

  /* Authority classes. `primary` is the only class that may be presented as
   * legal authority; everything else is reference or evidence material. */
  var AUTHORITY = {
    primary: "1차자료",        // statute / court decision — official
    party: "당사자 문서",      // produced inside the matter
    internal: "내부 산출물",   // firm-generated
    secondary: "2차자료"       // commentary, news, general web
  };

  var SOURCE_TYPE = {
    official: "공식 법률자료",
    drive: "내 Drive",
    web: "웹",
    internal: "법무 산출물"
  };

  /* ── Provenance honesty ──────────────────────────────────────────────────
   * Verified against the repo (not assumed):
   *   packages/padiem-ai-core/padiem_ai_core/evidence_graph.py carries
   *   id / title / snippet / retrieved_at / provider / source_type / url.
   *   It has NO document_id, page, section, locator, or span field.
   *   Page locators exist only in the document-segment subsystem
   *   (document_semantics.DocumentLocator, used by
   *    apps/padiem-ai-engine/app/document_evidence_projection.py).
   *
   * Consequence for this surface: a page number may be DISPLAYED as a target
   * contract, but it may never be presented as verified. Every record below
   * therefore carries provenance_verified: false, and the UI says so. */
  var PROVENANCE_NOTE =
    "페이지·섹션 위치는 문서 세그먼트 계층에서만 공급됩니다. " +
    "증거 그래프는 페이지 정보를 담지 않으므로 현재 이 값은 검증된 위치가 아닙니다.";

  /* ── Matter / case folders (DEMO) ────────────────────────────────────── */
  var MATTERS = [
    { id: "m-demo-01", title: "샘플 — 도매 계약 해지 분쟁", period: "2025.09 ~ 진행 중" },
    { id: "m-demo-02", title: "샘플 — 임차인 보상금 청구", period: "2025.06 ~ 종결" },
    { id: "m-demo-03", title: "샘플 — 제품 하자 분쟁", period: "2024.11 ~ 종결" }
  ];

  /* ── Drive corpus for the active matter (DEMO) ──────────────────────── */
  var CORPUS = [
    {
      id: "d1", name: "계약서_샘플.pdf", kind: "PDF", pages: 24,
      note: "PDF 네이티브 텍스트 — 17쪽에 해지 통지 조항 (샘플)",
      support: "foundation"
    },
    {
      id: "d2", name: "준비서면_샘플.pdf", kind: "PDF", pages: 6,
      note: "PDF 네이티브 텍스트 — 해지 통지 원문 (샘플)",
      support: "foundation"
    },
    {
      id: "d3", name: "상담메모_샘플.docx", kind: "DOCX", pages: null,
      note: "DOCX — 최초 해지 언급이 있는 상담 기록 (샘플)",
      support: "foundation"
    },
    {
      id: "d4", name: "증거자료_샘플.hwpx", kind: "HWPX", pages: null,
      note: "HWPX — 텍스트 추출 기반만 검증됨, 본 화면 미연결",
      support: "bridge-later"
    },
    {
      id: "d5", name: "갑 scanned_샘플.pdf", kind: "PDF", pages: 11,
      note: "스캔 이미지 PDF — OCR 구현은 있으나 호출 지점 없음",
      support: "bridge-later"
    },
    {
      id: "d6", name: "구계약_레거시.hwp", kind: "HWP", pages: null,
      note: "레거시 .hwp — 표준 문서 경로에서 미지원 (OLE2 바이너리)",
      support: "unsupported"
    }
  ];

  /* ── Evidence records (DEMO) ─────────────────────────────────────────── */
  var EVIDENCE = [
    {
      n: 1,
      source_type: "drive",
      source_id: "demo-ev-1",
      authority_class: "party",
      title: "계약서 (샘플)",
      document_id: "doc-demo-contract",
      page_or_section: "17쪽",
      retrieved_at: "2026-09-27 10:12",
      effective_date_or_version: "2025-08-01 서명본",
      url_or_drive_ref: "drive://DEMO/계약서_샘플.pdf#page=17",
      quote_span: "sample-span-1",
      quote: "당사자는 상대방에게 중대한 사유가 있는 경우 30일의 유예기간을 두고 서면으로 계약을 해지할 수 있다. (샘플 문구)",
      locator_action: "17쪽 열기",
      provenance_verified: false,
      demo: true
    },
    {
      n: 2,
      source_type: "drive",
      source_id: "demo-ev-2",
      authority_class: "party",
      title: "준비서면 (샘플)",
      document_id: "doc-demo-pleading",
      page_or_section: "2쪽",
      retrieved_at: "2026-09-27 10:12",
      effective_date_or_version: "2025-11-03 접수본",
      url_or_drive_ref: "drive://DEMO/준비서면_샘플.pdf#page=2",
      quote_span: "sample-span-2",
      quote: "피고는 2025년 11월 3일자로 계약 해지를 통지하였다. (샘플 문구)",
      locator_action: "2쪽 열기",
      provenance_verified: false,
      demo: true
    },
    {
      n: 3,
      source_type: "drive",
      source_id: "demo-ev-3",
      authority_class: "party",
      title: "상담메모 (샘플)",
      document_id: "doc-demo-memo",
      page_or_section: "1쪽",
      retrieved_at: "2026-09-27 10:12",
      effective_date_or_version: "2025-10-18 작성",
      url_or_drive_ref: "drive://DEMO/상담메모_샘플.docx#p=1",
      quote_span: "sample-span-3",
      quote: "상대방이 해지 의사 표시를 언급하였다. litigation 전 단계의 대화. (샘플 문구)",
      locator_action: "1쪽 열기",
      provenance_verified: false,
      demo: true
    },
    {
      n: 4,
      source_type: "official",
      source_id: "demo-ev-4",
      authority_class: "primary",
      /* FICTIONAL BY DESIGN.
       *
       * This must NOT use a real Korean statute identifier. Pairing a real
       * 조문 number or a real official publisher with invented text is exactly
       * the hallucination pattern this product exists to prevent, and doing it
       * in the demo teaches a lawyer the wrong thing: that a confident-looking
       * citation is cheap. "가상 법률요약집" and "가상 제17조" do not exist — and
       * it is deliberately NOT named after a real law either, so no reader can
       * pattern-match it onto a real article. Searching for it finds nothing,
       * which is the correct outcome. */
      fictional: true,
      title: "가상 법률요약집 (존재하지 않는 자료 · DEMO)",
      document_id: "fictional-legal-digest",
      page_or_section: "가상 제17조",
      retrieved_at: "2026-09-27 10:13",
      effective_date_or_version: "가상 판 · 실제 법령 아님",
      url_or_drive_ref: "fictional://DEMO/digest/sample-17",
      quote_span: "sample-span-4",
      quote: "당사자가 해지권을 행사한 것인지 판단하기 위한 요건. (존재하지 않는 자료의 가상 요지)",
      locator_action: "가상 자료 열기",
      provenance_verified: false,
      demo: true
    },
    {
      n: 5,
      source_type: "web",
      source_id: "demo-ev-5",
      authority_class: "secondary",
      title: "로펌 해설 아티클 (샘플)",
      document_id: null,
      page_or_section: "본문 중부",
      retrieved_at: "2026-09-27 10:13",
      effective_date_or_version: "2026-04-11 게시",
      url_or_drive_ref: "web://DEMO/commentary/sample",
      quote_span: "sample-span-5",
      quote: "계약 해지 통지의 상대적 성격에 관한 일반적 설명. (샘플 요지)",
      locator_action: "페이지 열기",
      provenance_verified: false,
      demo: true
    }
  ];

  /* ── Grounded sample answers, per scope (DEMO) ──────────────────────────
   *
   * ONE ANSWER PER SCOPE, not one global answer.
   *
   * The citation-integrity gate in legal-demo.js refuses to render an answer
   * whose [n] markers do not all resolve to records in the active evidence
   * set. The evidence sets differ per scope:
   *
   *   unified  -> all five records           -> [1][2][3][4][5]
   *   official -> the official record only   -> [4]
   *   drive    -> the three matter documents -> [1][2][3]
   *   web      -> the commentary record only  -> [5]
   *
   * A single global answer citing [1][2][3][4] therefore forces official and
   * drive into fail-closed. The gate is right; the answer model was wrong.
   * Each scope now gets an answer that can actually be grounded in the records
   * that scope can actually see — which also makes each scope a real
   * demonstration rather than a variation on one paragraph.
   *
   * The web answer states its own limit in the BODY, not only in a badge, so
   * the caveat survives a screenshot of the answer alone.
   */
  var DISCLAIMER =
    "위 내용은 모두 샘플 데이터로 구성한 시연이며 실제 사건 분석이 아닙니다.";

  var ANSWERS = {
    unified: {
      prompt: "이 사건에서 상대방이 계약 해지를 처음 주장한 시점과 그 주장을 뒷받침하는 자료를 찾아줘.",
      paragraphs: [
        {
          segments: [
            { t: "확인되는 자료상 상대방의 최초 명시적 계약해지 주장은 2025년 11월 3일 준비서면에서 확인됩니다. " },
            { cite: 2 }
          ]
        },
        {
          segments: [
            { t: "다만 2025년 10월 18일 상담메모에는 유사한 취지의 표현이 있어, " },
            { t: "'소송상 최초 주장’과 '사실상 최초 주장’은 구분할 필요가 있습니다. " },
            { cite: 3 }
          ]
        },
        {
          segments: [
            { t: "계약서의 해지 통지 조항은 유예기간 요건을 규정하고 있으므로, 통지 시점의 요건 충족 여부는 해당 요건을 함께 확인해야 합니다. " },
            { cite: 1 },
            { t: " " },
            { cite: 4 }
          ]
        },
        {
          segments: [
            { t: "로펌 해설 글은 위 판단의 일반적 배경으로 참고할 수 있으나, 법적 근거로 사용하지는 않습니다. " },
            { cite: 5 }
          ]
        },
        { segments: [{ t: DISCLAIMER }] }
      ],
      evidence_nums: [1, 2, 3, 4, 5],
      run: { searches: 3, sources: 5, status: "complete" },
      note: "이 답변은 샘플 데이터로 구성한 시연이며 실제 사건 분석이 아닙니다. 인용된 근거는 모두 가상 자료입니다."
    },

    /* Official: a question the OFFICIAL corpus alone can answer. */
    official: {
      prompt: "가상 계약 해지 요건을 공식 법률자료에서 확인해줘.",
      paragraphs: [
        {
          segments: [
            { t: "가상 법률요약집 제17조는 해지권 행사의 판단 요건을 규정합니다. " },
            { cite: 4 },
            { t: " 존재하지 않는 가상 자료이므로 실제 사건의 요건 해석에는 사용할 수 없습니다." }
          ]
        },
        {
          segments: [
            { t: "공식 법률자료 범위만으로는 사건 문서의 사실관계는 확인할 수 없습니다. 사건 자료가 필요하면 검색 범위를 '내 Drive'로 바꿔 확인하십시오." }
          ]
        },
        { segments: [{ t: DISCLAIMER }] }
      ],
      evidence_nums: [4],
      run: { searches: 1, sources: 1, status: "complete" },
      note: "이 답변은 존재하지 않는 가상 자료에 기반한 시연이며, 실제 법령 해석이 아닙니다."
    },

    /* Drive: the chronology question, grounded only in matter documents. */
    drive: {
      prompt: "상대방이 계약 해지를 처음 주장한 시점과 그 자료를 찾아줘.",
      paragraphs: [
        {
          segments: [
            { t: "확인되는 자료상 상대방의 최초 명시적 계약해지 주장은 2025년 11월 3일 준비서면에서 확인됩니다. " },
            { cite: 2 }
          ]
        },
        {
          segments: [
            { t: "다만 2025년 10월 18일 상담메모에는 유사한 취지의 표현이 있어, " },
            { t: "'소송상 최초 주장’과 '사실상 최초 주장’은 구분할 필요가 있습니다. " },
            { cite: 3 }
          ]
        },
        {
          segments: [
            { t: "계약서에는 해지 통지 시 유예기간 요건이 규정되어 있으므로, " },
            { t: "위 시점의 통지가 해당 요건을 충족했는지는 원문 대조를 통해 확인해야 합니다. " },
            { cite: 1 }
          ]
        },
        { segments: [{ t: DISCLAIMER }] }
      ],
      evidence_nums: [1, 2, 3],
      run: { searches: 2, sources: 3, status: "complete" },
      note: "이 답변은 샘플 자료실에 기반한 시연이며 실제 사건 분석이 아닙니다."
    },

    /* Web: secondary only. The limit is stated in the answer body itself. */
    web: {
      prompt: "공개 웹에서 계약 해지 관련 일반 설명을 찾아줘.",
      paragraphs: [
        {
          segments: [
            { t: "찾은 자료는 계약 해지 통지의 일반적 취지를 설명하는 해설 글입니다. " },
            { cite: 5 }
          ]
        },
        {
          segments: [
            { t: "이 자료는 2차자료이며 참고자료입니다. " },
            { t: "법적 근거로 단독 사용하지 마십시오. " },
            { t: "인용하려면 반드시 공식 1차자료로 확인해야 합니다." }
          ]
        },
        {
          segments: [
            { t: "요건 판단이나 사건 사실 확인에는 사용할 수 없습니다. 공식 법률자료나 사건 자료가 필요하면 검색 범위를 바꿔 확인하십시오." }
          ]
        },
        { segments: [{ t: DISCLAIMER }] }
      ],
      evidence_nums: [5],
      run: { searches: 2, sources: 1, status: "complete" },
      note: "이 답변은 2차자료에 기반한 시연이며 법적 근거가 아닙니다."
    }
  };

  /* Kept as an alias for callers that want the combined answer, and so the
   * citation-integrity gate keeps one obvious default. */
  var SAMPLE_ANSWER = ANSWERS.unified;

  /* ── Fail-closed record (DEMO) ───────────────────────────────────────── */
  var FAIL_CLOSED = {
    title: "검증 가능한 근거를 찾지 못했습니다.",
    body: "현재 선택한 자료 범위에서는 질문을 뒷받침할 수 있는 근거를 확인하지 못했습니다. 근거 없는 법률 결론은 제시하지 않습니다.",
    reason: "선택 범위: 공식 법률자료 + 내 Drive. 검색된 자료 중 질문의 시각 조건을 충족하는 문서가 없습니다.",
    actions: [
      { id: "widen", label: "검색 범위 바꾸기" },
      { id: "check-drive", label: "내 Drive 확인" }
    ]
  };

  /* ── Document format support — the honest matrix ───────────────────────
   * Wording is pinned to what the source audit actually found, not to what
   * the roadmap hopes for. Two things this deliberately does NOT say:
   *   - "HWPX 지원" — the shared HWPX skill pins HWPX_FULL_SPEC_SUPPORT="NO";
   *     only gate admission + text extraction are validated.
   *   - "PDF 처리 가능" — binary document parsing fails closed on the deployed
   *     chat Worker unless a server-side isolated parser composition is
   *     installed, and none is installed in the repo today. */
  var FORMAT_SUPPORT = [
    { key: "PDF", state: "기반 존재 · Worker 격리 파서 미설치", support: "bridge-later" },
    { key: "PDF OCR", state: "KAgent 구현됨 · 호출 지점 없음", support: "bridge-later" },
    { key: "DOCX", state: "기반 존재 · 본 화면 미연결", support: "foundation" },
    { key: "HWPX", state: "텍스트 추출만 · 전체 지원 아님", support: "bridge-later" },
    { key: "HWP", state: "미지원", support: "unsupported" }
  ];

  global.B67Demo = {
    MOCK: true,
    AUTHORITY: AUTHORITY,
    SOURCE_TYPE: SOURCE_TYPE,
    MATTERS: MATTERS,
    CORPUS: CORPUS,
    EVIDENCE: EVIDENCE,
    ANSWERS: ANSWERS,
    SAMPLE_ANSWER: SAMPLE_ANSWER,
    DISCLAIMER: DISCLAIMER,
    FAIL_CLOSED: FAIL_CLOSED,
    FORMAT_SUPPORT: FORMAT_SUPPORT,
    PROVENANCE_NOTE: PROVENANCE_NOTE
  };
})(window);
