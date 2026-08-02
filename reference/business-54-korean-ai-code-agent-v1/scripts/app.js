(() => {
  "use strict";

  const body = document.body;
  const startButton = document.querySelector("[data-start]");
  const nextButton = document.querySelector("[data-next]");
  const previousButton = document.querySelector("[data-previous]");
  const replayButtons = document.querySelectorAll("[data-replay]");
  const timelineItems = [...document.querySelectorAll("[data-timeline-step]")];
  const runTitle = document.querySelector("[data-run-title]");
  const runStatus = document.querySelector("[data-run-status]");
  const stepCount = document.querySelector("[data-step-count]");
  const planSummary = document.querySelector("[data-plan-summary]");
  const diffCaption = document.querySelector("[data-diff-caption]");
  const testResult = document.querySelector("[data-test-result]");
  const reviewDecision = document.querySelector("[data-review-decision]");
  const decisionStatus = document.querySelector("[data-decision-status]");
  const modeButtons = [...document.querySelectorAll("[data-mode]")];
  const evidenceTabs = [...document.querySelectorAll("[data-evidence-tab]")];
  const evidencePanels = [...document.querySelectorAll("[data-evidence-panel]")];
  const fileRows = [...document.querySelectorAll("[data-file]")];
  const mobileViewButtons = [...document.querySelectorAll("[data-mobile-view]")];
  const panels = [...document.querySelectorAll("[data-panel]")];

  const routeSelect = document.querySelector("[data-route-select]");
  const localFirst = document.querySelector("[data-local-first]");
  const externalFallback = document.querySelector("[data-external-fallback]");
  const planRoute = document.querySelector("[data-plan-route]");
  const buildRoute = document.querySelector("[data-build-route]");
  const reviewRoute = document.querySelector("[data-review-route]");
  const usage = document.querySelector("[data-usage]");
  const boundary = document.querySelector("[data-boundary]");
  const routeReasons = document.querySelector("[data-route-reasons]");
  const routeWarning = document.querySelector("[data-route-warning]");

  const steps = [
    {
      title: "시작할 준비가 되었습니다",
      status: "사용자 입력 대기",
      mode: "plan",
      tab: "plan",
      plan: "작업을 시작하면 영향을 받는 파일과 수정 계획이 표시됩니다."
    },
    {
      title: "관련 코드와 이벤트 흐름을 찾았습니다",
      status: "저장소 탐색 완료",
      mode: "plan",
      tab: "plan",
      plan: "src/save-note.js가 성공 메시지를 직접 dispatch하고 반환값에도 같은 메시지를 포함합니다."
    },
    {
      title: "한 파일만 수정하는 계획을 만들었습니다",
      status: "수정 계획 검토 가능",
      mode: "plan",
      tab: "plan",
      plan: "중복 dispatch를 제거하고 반환값 기반 알림만 유지한 뒤 기존 8개 테스트를 실행합니다."
    },
    {
      title: "Business 14가 작업별 모델 경로를 제안했습니다",
      status: "모델 경로 결정 · 합성",
      mode: "plan",
      tab: "plan",
      plan: "Plan은 한국어 추론 모델, Build는 코드 수정 모델, Review는 경량 검토 모델로 분리합니다."
    },
    {
      title: "제한된 수정안을 미리 만들었습니다",
      status: "파일 1개 · 적용 전",
      mode: "build",
      tab: "diff",
      plan: "허용된 src/save-note.js에서 중복 성공 이벤트 한 줄만 제거합니다."
    },
    {
      title: "첫 테스트에서 회귀 실패를 발견했습니다",
      status: "1 failed · 7 passed",
      mode: "build",
      tab: "test",
      plan: "기존 테스트가 반환 메시지와 UI announcement를 함께 검증하므로 한 단계 교정이 필요합니다."
    },
    {
      title: "실패 근거를 반영해 수정안을 교정했습니다",
      status: "재검증 준비",
      mode: "build",
      tab: "diff",
      plan: "중복 dispatch 제거는 유지하고 반환 메시지를 단일 announcement 경로에서 사용하도록 정리했습니다."
    },
    {
      title: "전체 테스트가 통과했습니다",
      status: "8 passed · 0 failed",
      mode: "review",
      tab: "test",
      plan: "저장 성공 메시지는 한 번만 표시되며 기존 저장 결과와 오류 경로는 유지됩니다."
    },
    {
      title: "최종 diff와 근거가 준비되었습니다",
      status: "사용자 결정 대기",
      mode: "review",
      tab: "diff",
      plan: "파일 1개 변경, 테스트 8개 통과, 네트워크·Push·merge·deploy 실행 없음."
    }
  ];

  let currentStep = 0;

  function selectEvidenceTab(name, focus = false) {
    evidenceTabs.forEach((tab) => {
      const selected = tab.dataset.evidenceTab === name;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    });
    evidencePanels.forEach((panel) => {
      panel.hidden = panel.dataset.evidencePanel !== name;
    });
  }

  function selectMode(name) {
    modeButtons.forEach((button) => {
      const selected = button.dataset.mode === name;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
  }

  function updateTestEvidence() {
    testResult.classList.remove("is-failed", "is-passed");
    const strong = testResult.querySelector("strong");
    const detail = testResult.querySelector("span");

    if (currentStep === 5) {
      testResult.classList.add("is-failed");
      strong.textContent = "1 failed · 7 passed";
      detail.textContent = "성공 announcement 횟수 기대값 1, 실제값 2 · 교정 필요";
      return;
    }

    if (currentStep >= 7) {
      testResult.classList.add("is-passed");
      strong.textContent = "8 passed · 0 failed";
      detail.textContent = "중복 성공 메시지 회귀 테스트와 기존 저장 테스트 통과";
      return;
    }

    strong.textContent = "아직 실행되지 않음";
    detail.textContent = "명령은 이 데모에서 합성 결과로만 표시됩니다.";
  }

  function updateTimeline() {
    timelineItems.forEach((item) => {
      const itemStep = Number(item.dataset.timelineStep);
      item.classList.toggle("is-complete", itemStep < currentStep);
      item.classList.toggle("is-active", itemStep === currentStep);
      item.classList.toggle("is-failed", itemStep === 5 && currentStep === 5);
    });
  }

  function renderStep(nextStep, announce = true) {
    currentStep = Math.max(0, Math.min(steps.length - 1, nextStep));
    const state = steps[currentStep];

    body.dataset.step = String(currentStep);
    runTitle.textContent = state.title;
    runStatus.textContent = state.status;
    stepCount.textContent = `${currentStep} / 8`;
    planSummary.textContent = state.plan;
    diffCaption.textContent = currentStep >= 4
      ? "이 patch는 아직 실제 파일에 적용되지 않았습니다. 최종 결정은 사용자에게 있습니다."
      : "수정 단계가 되면 최종 patch 근거가 표시됩니다.";

    updateTimeline();
    updateTestEvidence();
    selectMode(state.mode);
    selectEvidenceTab(state.tab);

    previousButton.disabled = currentStep === 0;
    nextButton.disabled = currentStep === 0 || currentStep === steps.length - 1;
    nextButton.textContent = currentStep === 7 ? "최종 검토" : "다음 단계";
    reviewDecision.hidden = currentStep !== steps.length - 1;
    decisionStatus.textContent = "";

    if (announce && currentStep > 0) {
      runStatus.setAttribute("aria-label", `${state.title}. ${state.status}`);
    }
  }

  function replaceReasonList(items) {
    routeReasons.replaceChildren();
    items.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      routeReasons.append(li);
    });
  }

  function updateRoute() {
    const route = routeSelect.value;
    const localPreferred = localFirst.checked;
    const fallbackAllowed = externalFallback.checked;
    let noSafeRoute = false;

    if (route === "local") {
      planRoute.textContent = "Local Reasoner 14B";
      buildRoute.textContent = "Code Builder 32B";
      reviewRoute.textContent = "Korean Review 8B";
      usage.textContent = "₩0 · 로컬";
      boundary.textContent = "장비 밖 전송 없음";
      replaceReasonList(["사용자가 로컬 경로를 직접 선택", "네트워크 권한 없음", "외부 fallback 비활성"]);
    } else if (route === "external") {
      planRoute.textContent = "External Planning Model";
      buildRoute.textContent = "External Coding Model";
      reviewRoute.textContent = "External Review Model";
      usage.textContent = "예상 ₩42 · 합성";
      boundary.textContent = "네트워크 권한 필요";
      replaceReasonList(["사용자가 외부 모델을 직접 선택", "현재 작업의 네트워크 권한은 차단", "권한 변경 전 실행 불가"]);
      noSafeRoute = true;
    } else if (!localPreferred && !fallbackAllowed) {
      planRoute.textContent = "경로 없음";
      buildRoute.textContent = "경로 없음";
      reviewRoute.textContent = "Human handoff";
      usage.textContent = "실행 안 함";
      boundary.textContent = "제약 충족 실패";
      replaceReasonList(["로컬 우선 비활성", "외부 fallback 비활성", "강제 실행 대신 사용자에게 반환"]);
      noSafeRoute = true;
    } else if (localPreferred) {
      planRoute.textContent = "Local Reasoner 14B";
      buildRoute.textContent = "Code Builder 32B";
      reviewRoute.textContent = "Korean Review 8B";
      usage.textContent = fallbackAllowed ? "₩0 우선 · fallback 합성" : "₩0 · 로컬";
      boundary.textContent = fallbackAllowed ? "로컬 우선 · 외부는 실패 시" : "장비 밖 전송 없음";
      replaceReasonList(["개인 저장소 작업", "로컬 처리 우선", fallbackAllowed ? "외부 fallback은 실패 시에만" : "외부 fallback 비활성"]);
    } else {
      planRoute.textContent = "Korean Planning Cloud";
      buildRoute.textContent = "Coding Cloud Fast";
      reviewRoute.textContent = "Local Review 8B";
      usage.textContent = "예상 ₩31 · 합성";
      boundary.textContent = "외부 전송 허용 필요";
      replaceReasonList(["로컬 우선 비활성", "외부 fallback 허용", "Review는 로컬 경로 유지"]);
    }

    routeWarning.hidden = !noSafeRoute;
  }

  function selectMobilePanel(name) {
    mobileViewButtons.forEach((button) => {
      const selected = button.dataset.mobileView === name;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    panels.forEach((panel) => {
      panel.classList.toggle("is-mobile-active", panel.dataset.panel === name);
    });
  }

  startButton.addEventListener("click", () => {
    renderStep(1);
    nextButton.focus();
  });

  nextButton.addEventListener("click", () => renderStep(currentStep + 1));
  previousButton.addEventListener("click", () => renderStep(currentStep - 1));
  replayButtons.forEach((button) => button.addEventListener("click", () => {
    renderStep(0);
    selectMobilePanel("work");
    startButton.focus();
  }));

  modeButtons.forEach((button) => button.addEventListener("click", () => {
    const mode = button.dataset.mode;
    selectMode(mode);
    selectEvidenceTab(mode === "plan" ? "plan" : mode === "build" ? "diff" : "test");
  }));

  evidenceTabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectEvidenceTab(tab.dataset.evidenceTab));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      let targetIndex = index;
      if (event.key === "ArrowLeft") targetIndex = (index - 1 + evidenceTabs.length) % evidenceTabs.length;
      if (event.key === "ArrowRight") targetIndex = (index + 1) % evidenceTabs.length;
      if (event.key === "Home") targetIndex = 0;
      if (event.key === "End") targetIndex = evidenceTabs.length - 1;
      selectEvidenceTab(evidenceTabs[targetIndex].dataset.evidenceTab, true);
    });
  });

  fileRows.forEach((row) => row.addEventListener("click", () => {
    fileRows.forEach((item) => item.classList.toggle("is-selected", item === row));
  }));

  [routeSelect, localFirst, externalFallback].forEach((control) => control.addEventListener("change", updateRoute));

  mobileViewButtons.forEach((button) => button.addEventListener("click", () => {
    selectMobilePanel(button.dataset.mobileView);
  }));

  document.querySelectorAll("[data-decision]").forEach((button) => button.addEventListener("click", () => {
    const decision = button.dataset.decision;
    if (decision === "accept") decisionStatus.textContent = "수정안이 승인되었습니다. 실제 적용은 이 합성 데모에서 수행하지 않습니다.";
    if (decision === "revise") decisionStatus.textContent = "추가 수정 요청이 기록되었습니다. 실제 에이전트 실행은 없습니다.";
    if (decision === "reject") decisionStatus.textContent = "수정안이 거절되었습니다. 원본 상태가 유지됩니다.";
  }));

  updateRoute();
  renderStep(0, false);
  selectMobilePanel("work");
})();
