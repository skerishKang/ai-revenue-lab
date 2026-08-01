/* data.js — 파디엠 AI 미디어 업무전환 v2 fixture data (deterministic) */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PADIEM = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var ORG = {
    culture: "지역 문화기관", education: "지역 교육기관",
    association: "지역 협회·단체", media: "지역 미디어·콘텐츠 기관",
  };
  var TEAM = { small: "2–5명", mid: "6–15명", large: "16명 이상" };
  var TASK = { planning: "기획·편성", production: "제작·촬영·편집", publishing: "콘텐츠 발행·배포", mixed: "전반 운영" };
  var BOTTLENECK = { draft: "초안 작성", review: "검토·수정", approval: "승인·의사결정", publish: "게시·홍보" };
  var AI = { none: "거의 사용 안 함", individual: "개인별 사용", partial: "일부 업무 적용" };
  var GOV = { loose: "정해진 절차 없음", manual: "전부 수동 검토", hybrid: "일부 자동화" };

  function diag(v) {
    var key = [v.org, v.task, v.bottleneck, v.ai, v.gov].join("|");
    var coreBottleneck = {
      planning: "기획안 확정 전에 재작업 반복",
      production: "제작·편집 산출물의 수동 전달·검토 반복",
      publishing: "검토·승인·게시가 한 사람 수동 의존",
      mixed: "단계 간 수동 인수인계로 시간 손실",
    }[v.task];
    var humanReview = {
      loose: "승인 절차 부재 — 담당자 확인 지점 부재",
      manual: "모든 검토 수동 — AI 초안도 사람 2회 확인 필요",
      hybrid: "일부 자동화 — 남은 수동 검토 지점만 유지",
    }[v.gov];

    var program, programDesc;
    if (v.ai === "none") {
      program = "A · 진단 워크숍";
      programDesc = "현재 업무 측정과 적용 후보·위험 업무 제외부터 시작합니다. 1–2일, 300만–500만원(초기형).";
    } else if (v.gov === "hybrid" && v.ai === "partial") {
      program = "C · 운영 자문";
      programDesc = "이미 일부 적용된 조직입니다. 승인 도구·프롬프트·워크플로 정비를 월 단위로 지원합니다(월 300만–600만원).";
    } else if (v.bottleneck === "review" || v.bottleneck === "approval" || v.team === "small") {
      program = "B1 · 디자인 파트너 파일럿";
      programDesc = "초기 도입 조직에 적합한 6주 파일럿. 한 팀·한 핵심 업무로 기준선→재설계→사람 검토를 설계합니다(1,000만–1,500만원, 가격 우대).";
    } else {
      program = "B2 · 표준 6주 파일럿";
      programDesc = "1팀·1핵심업무를 끝까지 바꾸는 대표 상품. 기준선 측정→교육→워크플로 재설계→파일럿→KPI→운영 playbook(1,500만–2,500만원).";
    }

    var priorityWork = {
      planning: "월간 기획안 1종을 파일럿 대상으로 선정",
      production: "보도자료·촬영 러프컷 1건을 AI-assisted 초안으로",
      publishing: "공고·SNS 게시물 초안 1종",
      mixed: "대표 공고/보도자료 흐름 1건",
    }[v.task];

    var outputs = [
      "현황 진단 보고서(병목·시간 측정)",
      "기준선 측정표와 파일럿 KPI",
      "역할별 교육 모듈 + 프롬프트·검토 카드",
      "워크플로 청사진(사람 검토 gate 포함)",
      "운영 playbook(담당자·기한·승인 경로)",
    ];

    return {
      key: key,
      org: ORG[v.org], team: TEAM[v.team], task: TASK[v.task],
      bottleneckLabel: BOTTLENECK[v.bottleneck], ai: AI[v.ai], gov: GOV[v.gov],
      coreBottleneck: coreBottleneck,
      humanReview: humanReview,
      program: program,
      programDesc: programDesc,
      priorityWork: priorityWork,
      outputs: outputs,
      estimate: { before: "4.2일", after: "2.4일", reduction: "약 43% 단축(가설)" },
    };
  }

  var DELIVERABLES = {
    map: { title: "업무진단 맵", body: "조직의 미디어 업무 단계별 소요 시간과 병목을 측정한 원본 맵입니다. 교육 전 기준선이 됩니다." },
    policy: { title: "AI 사용정책", body: "허용 업무·금지 업무·사람 검토 기준·자동 게시 금지를 명시한 조직 정책 초안입니다. 경영진 승인 대상입니다." },
    training: { title: "역할별 교육 모듈", body: "기획자·제작자·검토자·관리자별로 다른 교육 모듈과 프롬프트 카드, 검토 체크리스트를 제공합니다." },
    blueprint: { title: "워크플로 청사진", body: "brief → AI-assisted 초안 → 근거 확인 → 사람 검토 → 승인 → 게시 → 학습 루프를 담당자·기한·예외 경로와 함께 그립니다." },
    kpi: { title: "파일럿 KPI", body: "제작 시간·검토 반복 횟수·사람 검토 통과율·게시 적시성을 기준선 대비 측정합니다." },
    playbook: { title: "운영 playbook", body: "담당자·기한·승인 경로·예외 처리·교육 운영 일정을 담은 조직 승인 운영 플레이북입니다." },
  };

  return { diag: diag, deliverables: DELIVERABLES };
});
