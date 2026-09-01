/* external-portfolio-projects.js — unnumbered external portfolio visibility
 *
 * This file intentionally does not create or assign a BI/Business number.
 * It augments ARL_PROJECTS with external portfolio projects that must be visible
 * in the Portfolio Console but remain outside BUSINESS_REGISTRY numbering.
 */

(function () {
  "use strict";

  var externalProjects = [
    {
      id: "fmindex",
      name: "FMIndex",
      koreanName: "펨코지수",
      businessNumber: null,
      purpose: "KOSPI 시장 데이터와 FMKorea 커뮤니티 심리를 결합한 시장 보조지표 포트폴리오 프로젝트입니다.",
      repositoryLabel: "skerishKang/fmindex",
      repositoryUrl: "https://github.com/skerishKang/fmindex",
      workspace: "external:skerishKang/fmindex",
      pageUrl: "https://fmindex.pages.dev/",
      stage: "paused",
      developmentMode: "complete",
      progressBasis: "#24 closeout 기준: main 단일 canonical source, CI gate, branch cleanup, Cloudflare main production 확인",
      milestoneStatus: "defined",
      currentMilestone: "FMIndex external portfolio registration (#1310)",
      milestoneTasks: [
        {
          id: "fmindex-main-canonical",
          label: "Canonical main consolidation",
          done: true,
          evidence: "skerishKang/fmindex main @ 7f70a735b7c49f7e289a0bfa5f63d63255d3e5cc"
        },
        {
          id: "fmindex-ci-protection",
          label: "CI gate and main protection",
          done: true,
          evidence: "main protected; required check = ci"
        },
        {
          id: "fmindex-branch-cleanup",
          label: "Stale branch cleanup",
          done: true,
          evidence: "remote branches pruned to main only; Issue #24 closed/completed"
        },
        {
          id: "fmindex-portfolio-registration",
          label: "Portfolio registration",
          done: true,
          evidence: "Registered as unnumbered external portfolio project via Issue #1310"
        }
      ],
      progressNote: "BI 번호는 강제하지 않음. 포트폴리오 표시용 외부 프로젝트로 등록.",
      currentWork: "우선 마무리 상태. 추가 구현은 제품 운영화 또는 데이터 파이프라인 2차 작업 시 재개.",
      nextAction: "필요 시 BI 번호 부여 절차 또는 운영화 이슈를 별도로 생성",
      blockers: [],
      futureRoadmap: [
        "정기 KOSPI 수집 운영화",
        "FMKorea 수집 정책 재검토",
        "실제 LLM provider 연결",
        "공개 서비스 UX/도메인/배포 정비"
      ],
      lastVerified: "2026-09-01"
    }
  ];

  var target = Array.isArray(window.ARL_PROJECTS) ? window.ARL_PROJECTS : [];
  var existing = {};
  for (var i = 0; i < target.length; i++) existing[target[i].id] = true;

  for (var j = 0; j < externalProjects.length; j++) {
    if (!existing[externalProjects[j].id]) target.push(externalProjects[j]);
  }

  window.ARL_PROJECTS = target;
  window.ARL_EXTERNAL_PORTFOLIO_PROJECTS = externalProjects;
})();
