/*  tutorial-data.js  —  de-identified synthetic tutorial fixture (UMD)
 *
 *  Mirrors data/tutorial-data.json exactly (tests assert equality).
 *  No real complex/person/date/amount/event/litigation/CCTV/vote data.
 *  No legal judgement terms.
 */

(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ARL_TUTORIAL = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  return {
    meta: {
      title: "공동주택 운영 단계별 가이드 (합성 튜토리얼)",
      subtitle: "Business 29 · Apartment Governance — 비식별 합성 시각 튜토리얼",
      community: "솔빛마루 2단지 (합성)",
      households: 420,
      synthetic: true,
      note: "모든 단지명·인물·날짜·금액·사건·소송·고소·CCTV·투표 결과는 합성이며 실제 데이터가 아닙니다."
    },
    chapters: [
      {
        id: "preparation", no: 1, title: "회의 준비와 사전 공고",
        steps: [
          { id: "prep-1", title: "안건 목록 정리", text: "회의 안건을 목록으로 정리하고 우선순위를 표시합니다." },
          { id: "prep-2", title: "공고 초안 작성", text: "회의 일시·안건·준비물을 포함한 공고 초안을 작성합니다." },
          { id: "prep-3", title: "사전 공고 게시", text: "초안을 검토한 뒤 사전 공고를 게시합니다." },
          { id: "prep-4", title: "변경·재공고", text: "내용이 바뀌면 재공고로 안내합니다." }
        ],
        guide: "사전 공고 후 의견을 수집하고, 누락이 있으면 자료 부족으로 안내하고 절차 보완 필요 상태로 표시합니다."
      },
      {
        id: "roles", no: 2, title: "역할·권한·이해관계 확인",
        steps: [
          { id: "roles-1", title: "역할 확인", text: "참여자별 역할(관리자·동대표·선관위원·관리사무소·외부 검토자·일반 주민)을 확인합니다." },
          { id: "roles-2", title: "권한 확인", text: "역할별 권한 범위를 확인합니다." },
          { id: "roles-3", title: "이해관계 확인 필요", text: "이해관계가 있는 경우 확인 필요로 표시하고 전문 검토 필요로 안내합니다." }
        ],
        guide: "권한 밖의 처리나 이해관계가 의심되면 확인 필요로 표시하고, 판단이 필요한 경우 전문 검토 필요로 안내합니다."
      },
      {
        id: "attendance", no: 3, title: "출석과 정족수",
        steps: [
          { id: "att-1", title: "출석 기록", text: "출석 명단을 기록합니다(개인정보는 가림 처리 대상)." },
          { id: "att-2", title: "정족수 확인", text: "출석 수와 기준을 비교해 확인합니다." },
          { id: "att-3", title: "정족수 미달 처리", text: "미달 시 절차 보완 필요로 표시하고 재소집 공고를 안내합니다." }
        ],
        guide: "정족수 미달은 곧바로 판정하지 않고 절차 보완 필요로 표시하며, 출석 자료 보완 후 재확인합니다."
      },
      {
        id: "evidence", no: 4, title: "소명자료와 반대 의견",
        steps: [
          { id: "ev-1", title: "소명자료 수집", text: "소명자료 요청과 제출 목록을 기록합니다." },
          { id: "ev-2", title: "소명자료 누락 처리", text: "누락 시 자료 부족으로 표시하고 추가 제출을 안내합니다." },
          { id: "ev-3", title: "반대 의견 기록", text: "반대 의견을 기록으로 보존합니다." }
        ],
        guide: "소명자료가 누락되면 자료 부족으로 표시하고, 반대 의견은 의결과 함께 기록으로 유지합니다."
      },
      {
        id: "resolution", no: 5, title: "의결과 후속조치",
        steps: [
          { id: "res-1", title: "의결안 작성", text: "의결안 초안을 작성합니다." },
          { id: "res-2", title: "의결", text: "의결 결과를 기록합니다." },
          { id: "res-3", title: "후속조치 등록", text: "담당자와 기한을 등록합니다." },
          { id: "res-4", title: "기한초과 처리", text: "기한초과 시 기록 유지로 표시하고 후속 조치를 안내합니다." }
        ],
        guide: "의결은 결과만이 아니라 이견·반대 의견과 함께 기록하여 기록 유지합니다."
      },
      {
        id: "disclosure", no: 6, title: "주민 공개·가림처리·공개 보류",
        steps: [
          { id: "disc-1", title: "공개 대상 선별", text: "공개·비공개·가림 대상으로 나눕니다." },
          { id: "disc-2", title: "가림처리", text: "개인정보·세부 자료를 가림 처리합니다." },
          { id: "disc-3", title: "공개 보류 판단", text: "공개가 적절하지 않으면 공개 보류로 표시하고 전문 검토 필요로 안내합니다." }
        ],
        guide: "공개 여부 판단은 사람 검토를 거치며, 부적절하면 공개 보류로 표시하고 전문 검토 필요로 안내합니다."
      },
      {
        id: "audit", no: 7, title: "변경이력과 감사기록",
        steps: [
          { id: "aud-1", title: "변경이력 기록", text: "문서·상태 변경을 이력으로 남깁니다." },
          { id: "aud-2", title: "감사기록 열람", text: "감사 역할은 이력과 기록을 열람합니다." },
          { id: "aud-3", title: "기록 유지", text: "기록을 유지하고 보존 상태를 표시합니다." }
        ],
        guide: "모든 변경은 이력으로 남기고, 감사기록은 수정하지 않고 기록 유지합니다."
      }
    ],
    scenarios: [
      { id: "normal", title: "정상 회의", text: "준비·공고·출석·정족수·의결·후속조치·공개까지 정상 흐름으로 진행됩니다.", status: "기록 유지" },
      { id: "quorum_miss", title: "정족수 미달", text: "출석 기준 미달 시 절차 보완 필요로 표시하고 재소집 공고를 안내합니다.", status: "절차 보완 필요" },
      { id: "evidence_missing", title: "소명자료 누락", text: "소명자료가 누락되면 자료 부족으로 표시하고 추가 제출을 안내합니다.", status: "자료 부족" },
      { id: "conflict", title: "이해관계 확인 필요", text: "이해관계가 의심되면 확인 필요로 표시하고 전문 검토 필요로 안내합니다.", status: "확인 필요" },
      { id: "dissent", title: "반대 의견 존재", text: "반대 의견은 의결과 함께 기록으로 보존하고 기록 유지합니다.", status: "기록 유지" },
      { id: "disclosure_hold", title: "주민 공개 보류", text: "공개가 적절하지 않으면 공개 보류로 표시하고 전문 검토 필요로 안내합니다.", status: "공개 보류" },
      { id: "overdue", title: "기한초과 후속조치", text: "후속조치 기한이 지나면 기록 유지로 표시하고 후속 조치를 안내합니다.", status: "기록 유지" }
    ]
  };
});
