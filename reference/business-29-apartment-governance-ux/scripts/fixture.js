/*  fixture.js  —  synthetic fixture mirror (UMD)
 *
 *  Sole synthetic data source for the Business 29 Phase 2 UX reference.
 *  Mirrors data/fixture.json exactly; tests assert equality.
 *  Every person, amount, date, vote and record is synthetic.
 */

(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ARL_FIXTURE = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  return {
    community: {
      name: "솔빛마루 2단지",
      nameEn: "Solbit Maru 2",
      households: 420,
      fictional: true,
      note: "합성 커뮤니티 — 실제 아파트/주민 데이터 아님"
    },
    meeting: {
      name: "2026년 3분기 합성 대표회의",
      quarter: "2026 Q3",
      synthetic: true
    },
    rules: [
      {
        id: "rule-1",
        title: "관리규약 제N조(회의 성립) — 합성 예시 조항",
        excerpt: "대표회의는 재적 대표의 3분의 1 이상 출석으로 성립한다. (합성 예시 — 법적 효력 없음)",
        disclosure: "private"
      }
    ],
    agenda: [
      { id: "agenda-1", title: "합성 안건 1: 공용부 정비 계획 논의", ruleRef: "rule-1", disclosure: "private" },
      { id: "agenda-2", title: "합성 안건 2: 관리규약 개정 준비", ruleRef: "rule-1", disclosure: "private" }
    ],
    attendance: {
      initialCount: 8,
      supplementedCount: 11,
      threshold: 10,
      roster: ["동대표 갑(합성)", "동대표 을(합성)", "동대표 병(합성)", "동대표 정(합성)", "동대표 무(합성)", "동대표 기(합성)", "동대표 경(합성)", "동대표 신(합성)"],
      disclosure: "private",
      note: "출석 명단은 비공개(roster). 집계만 redacted로 공개 가능."
    },
    discussion: {
      notes: [
        {
          agenda: "agenda-1",
          text: "공용부 정비 견적을 관리사무소가 비교 검토해 다음 회의에 제시하기로 논의. (합성)",
          disclosure: "private"
        }
      ]
    },
    dissent: {
      agenda: "agenda-1",
      member: "동대표 갑(합성)",
      text: "정비 범위가 과해 예산 낭비 우려가 있어 이견을 표시한다. (합성)",
      disclosure: "private",
      retained: true
    },
    resolution: {
      text: "공용부 정비 계획을 합성 절차에 따라 다음 회의에서 재논의하기로 한다. (합성 의결 — 법적 효력 없음)",
      disclosure: "private"
    },
    actions: [
      {
        id: "action-1",
        title: "정비 견적 비교자료 취합",
        owner: "관리사무소(합성)",
        due: "2026-08-05",
        overdue: true,
        disclosure: "private",
        note: "기한 초과 후속조치 1건 (합성)"
      }
    ],
    documents: [
      {
        id: "doc-1",
        title: "합성 예산 자료",
        disclosure: "private",
        redactable: true,
        redacted: null,
        note: "redaction 대상 문서 1건 (합성) — 공개 전 반드시 redacted 복사본 확인"
      }
    ],
    disclosurePackage: {
      items: ["notice", "resolution", "agenda-1", "agenda-2", "doc-1"],
      note: "공개 패키지는 사람 검토(disclosure-review) 후에만 공개 가능"
    },
    fault: {
      action: "publishNotice",
      failOnce: true,
      note: "복구 가능한 system error 1회 (합성 주입) — retry로 복구"
    }
  };
});
