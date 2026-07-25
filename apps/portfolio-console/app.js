(() => {
  "use strict";

  const businesses = Array.isArray(window.ARL_BUSINESSES) ? window.ARL_BUSINESSES : [];
  const projects = Array.isArray(window.ARL_PROJECTS) ? window.ARL_PROJECTS : [];
  const $ = (selector) => document.querySelector(selector);
  const tableBody = $("#business-table-body");
  const searchInput = $("#search-input");
  const stateFilter = $("#state-filter");
  const sortControl = $("#sort-control");
  let selectedNumber = null;
  let selectedProjectId = null;
  let currentLang = "ko";

  const labels = {
    ko: {
       businessOperations: "내 비즈니스 관리",
      projectDirectory: "프로젝트 모아보기",
      businessRegistry: "비즈니스 목록",
      priorityActions: "우선 작업",
      search: "검색",
      stage: "단계",
      repository: "저장소",
      workspace: "폴더",
      page: "페이지",
      progress: "진행 상황",
      currentWork: "현재 작업",
      nextAction: "다음 작업",
      lastVerified: "마지막 확인",
       openPage: "페이지 열기",
      openRepository: "저장소 열기",
      copyWorkspace: "폴더 경로 복사",
      viewDetail: "자세히 보기",
      allProjects: "전체 프로젝트",
      all: "전체",
      projects: "개",
      rows: "개",
      items: "개",
      noResults: "조건에 맞는 사업이 없습니다.",
      noProjects: "조건에 맞는 프로젝트가 없습니다.",
      selectBusiness: "사업을 선택하십시오.",
      selectProject: "프로젝트를 선택하십시오.",
      demoReadiness: "데모 준비도",
      lifecycle: "라이프사이클",
      deployment: "배포",
      github: "GitHub",
      openSurface: "화면 열기",
      openGithub: "GitHub 열기",
      openIssue: "Issue 열기",
      actionNote: "확인된 링크만 활성화됩니다.",
      actionNoteWithSurface: "확인된 배포 주소와 GitHub 근거만 연결되어 있습니다.",
      actionNoteNoSurface: "확인된 배포 주소가 없어 GitHub 근거만 활성화했습니다.",
      mode: "모드",
      source: "소스",
      range: "범위",
      manual: "수동",
      staticRegistry: "정적 레지스트리",
      registryLoaded: "레지스트리 로드됨",
      privateAdmin: "개인 관리자",
       businesses: "비즈니스",
       deployments: "배포",
       modelsCost: "모델 & 비용",
       registry: "레지스트리",
       projectStatus: "프로젝트 현황",
       searchFilter: "검색·필터",
       reset: "초기화",
       searchPlaceholder: "이름, 저장소, 폴더, 목적, 현재 작업, 다음 작업 검색",
       closePanel: "검색 패널 닫기",
       sortDefault: "기본순",
       sortProgressDesc: "진행률 높은 순",
       sortProgressAsc: "진행률 낮은 순",
       resultCount: "개 중",
      tracked: "추적 중",
      demoSurfaces: "데모 화면",
      needsAction: "조치 필요",
      openSlots: "미배정",
      trackedDesc: "번호가 배정되거나 제안된 사업",
      demoDesc: "즉시 열 수 있는 확인된 화면",
      actionDesc: "검토·배포·결정이 필요한 사업",
      openDesc: "현재 표시 범위의 미배정 번호",
      state: "상태",
      sort: "정렬",
      allStates: "전체 상태",
      running: "운영 중",
      reviewBuild: "검토 / 개발",
      planning: "계획",
      reserved: "예약",
      numberAsc: "번호 ↑",
      numberDesc: "번호 ↓",
      actionPriority: "우선순위",
      progressSort: "진행률",
      business: "비즈니스",
      surface: "화면",
      nextActionCol: "다음 작업",
       copySuccess: "폴더 경로를 복사했습니다",
       copyFail: "폴더 경로를 복사하지 못했습니다.",
       notDeployed: "미배포",
       demoShort: "데모",
       langKo: "한국어",
       langEn: "EN",
       milestone: "마일스톤",
       devMode: "개발 모드",
       progressBasis: "진행 기준",
       progressUndefined: "진척도 미정",
       goalDefinitionNeeded: "목표 정의 필요",
       doneTasks: "완료 작업",
       remainingTasks: "남은 작업",
       blockersLabel: "차단 사항",
       doneShort: "완료",
       remainingShort: "남음"
    },
    en: {
       businessOperations: "Business Operations",
      projectDirectory: "Project Directory",
      businessRegistry: "Business Registry",
      priorityActions: "Priority Actions",
      search: "SEARCH",
      stage: "STAGE",
      repository: "REPOSITORY",
      workspace: "WORKSPACE",
      page: "PAGE",
      progress: "PROGRESS",
      currentWork: "CURRENT WORK",
      nextAction: "NEXT ACTION",
      lastVerified: "LAST VERIFIED",
       openPage: "OPEN PAGE",
      openRepository: "OPEN REPOSITORY",
      copyWorkspace: "COPY WORKSPACE",
      viewDetail: "VIEW DETAIL",
      allProjects: "ALL PROJECTS",
      all: "ALL",
      projects: "projects",
      rows: "rows",
      items: "items",
      noResults: "No businesses match the search criteria.",
      noProjects: "No projects match the criteria.",
      selectBusiness: "Select a business.",
      selectProject: "Select a project.",
      demoReadiness: "DEMO READINESS",
      lifecycle: "LIFECYCLE",
      deployment: "DEPLOYMENT",
      github: "GITHUB",
      openSurface: "OPEN SURFACE",
      openGithub: "OPEN GITHUB",
      openIssue: "OPEN ISSUE",
      actionNote: "Only verified links are enabled.",
      actionNoteWithSurface: "Only verified deployment and GitHub evidence are linked.",
      actionNoteNoSurface: "No verified deployment, so only GitHub evidence is enabled.",
      mode: "MODE",
      source: "SOURCE",
      range: "RANGE",
      manual: "MANUAL",
      staticRegistry: "STATIC REGISTRY",
      registryLoaded: "registry loaded",
      privateAdmin: "PRIVATE ADMIN",
       businesses: "Businesses",
       deployments: "Deployments",
       modelsCost: "Models & Cost",
       registry: "Registry",
       projectStatus: "PROJECT STATUS",
       searchFilter: "SEARCH & FILTER",
       reset: "RESET",
       searchPlaceholder: "Search by name, repo, folder, purpose, current work, next action",
       closePanel: "Close search panel",
       sortDefault: "DEFAULT",
       sortProgressDesc: "PROGRESS DESC",
       sortProgressAsc: "PROGRESS ASC",
       resultCount: " of ",
      tracked: "TRACKED",
      demoSurfaces: "DEMO SURFACES",
      needsAction: "NEEDS ACTION",
      openSlots: "OPEN SLOTS",
      trackedDesc: "Assigned or proposed businesses",
      demoDesc: "Verified surfaces that can be opened immediately",
      actionDesc: "Businesses needing review, deployment, or decision",
      openDesc: "Unassigned numbers in current display range",
      state: "STATE",
      sort: "SORT",
      allStates: "ALL STATES",
      running: "RUNNING",
      reviewBuild: "REVIEW / BUILD",
      planning: "PLANNING",
      reserved: "RESERVED",
      numberAsc: "NUMBER ↑",
      numberDesc: "NUMBER ↓",
      actionPriority: "ACTION PRIORITY",
      progressSort: "PROGRESS",
      business: "BUSINESS",
      surface: "SURFACE",
      nextActionCol: "NEXT ACTION",
       copySuccess: "Workspace path copied",
       copyFail: "Failed to copy workspace path.",
       notDeployed: "Not deployed",
       demoShort: "DEMO",
       langKo: "한국어",
       langEn: "EN",
       milestone: "MILESTONE",
       devMode: "DEV MODE",
       progressBasis: "PROGRESS BASIS",
       progressUndefined: "PROGRESS UNDEFINED",
       goalDefinitionNeeded: "GOAL DEFINITION NEEDED",
       doneTasks: "DONE TASKS",
       remainingTasks: "REMAINING TASKS",
       blockersLabel: "BLOCKERS",
       doneShort: "DONE",
       remainingShort: "REMAINING"
    }
  };

  const stateLabels = {
    running: { ko: "운영 중", en: "RUNNING" },
    review: { ko: "검토 중", en: "REVIEW" },
    planning: { ko: "계획", en: "PLANNING" },
    reserved: { ko: "예약", en: "RESERVED" }
  };

  const stageLabels = {
    live: { ko: "운영 중", en: "LIVE" },
    building: { ko: "개발 중", en: "BUILDING" },
    review: { ko: "검토 중", en: "REVIEW" },
    planned: { ko: "계획", en: "PLANNED" },
    paused: { ko: "일시 중지", en: "PAUSED" }
  };

  const developmentModeLabels = {
    "not-started": { ko: "시작 전", en: "NOT STARTED" },
    "active-development": { ko: "개발 중", en: "ACTIVE DEV" },
    "needs-improvement": { ko: "개선 필요", en: "NEEDS IMPROVEMENT" },
    "maintenance": { ko: "유지보수", en: "MAINTENANCE" },
    "complete": { ko: "완료", en: "COMPLETE" },
    "paused": { ko: "일시 중지", en: "PAUSED" }
  };

  function computeProgress(tasks) {
    if (!Array.isArray(tasks) || tasks.length === 0) {
      return {
        hasProgress: false,
        doneCount: 0,
        totalCount: 0,
        progressPercent: null,
        remainingPercent: null
      };
    }

    const totalCount = tasks.length;
    const doneCount = tasks.filter(task => task.done).length;
    const progressPercent = Math.round((doneCount / totalCount) * 100);

    return {
      hasProgress: true,
      doneCount,
      totalCount,
      progressPercent,
      remainingPercent: 100 - progressPercent
    };
  }

  function t(key) {
    return labels[currentLang][key] || labels.ko[key] || key;
  }

  function stateLabel(state) {
    return stateLabels[state]?.[currentLang] || stateLabels[state]?.en || state;
  }

  function stageLabel(stage) {
    return stageLabels[stage]?.[currentLang] || stageLabels[stage]?.en || stage;
  }

  function developmentModeLabel(mode) {
    return developmentModeLabels[mode]?.[currentLang] || developmentModeLabels[mode]?.en || mode;
  }

  function pad(number) {
    return String(number).padStart(2, "0");
  }

  function updateMetrics() {
    const tracked = businesses.filter((item) => item.state !== "reserved").length;
    const demos = businesses.filter((item) => Boolean(item.surfaceUrl)).length;
    const needsAction = businesses.filter((item) => ["review", "planning"].includes(item.state)).length;
    const openSlots = businesses.filter((item) => item.state === "reserved").length;
    $("#metric-tracked").textContent = pad(tracked);
    $("#metric-demo").textContent = pad(demos);
    $("#metric-action").textContent = pad(needsAction);
    $("#metric-open").textContent = pad(openSlots);
    const maxNumber = Math.max(...businesses.map((item) => item.number), 0);
    $("#sidebar-range").textContent = `01–${pad(maxNumber)}`;
  }

  function filteredBusinesses() {
    const query = searchInput.value.trim().toLowerCase();
    const state = stateFilter.value;
    const sort = sortControl.value;
    const filtered = businesses.filter((item) => {
      const haystack = `${item.number} ${pad(item.number)} ${item.title} ${item.koreanTitle} ${item.slug}`.toLowerCase();
      return (!query || haystack.includes(query)) && (state === "all" || item.state === state);
    });

    return filtered.sort((a, b) => {
      if (sort === "number-desc") return b.number - a.number;
      if (sort === "priority") return b.priority - a.priority || a.number - b.number;
      if (sort === "progress") return b.progress - a.progress || a.number - b.number;
      return a.number - b.number;
    });
  }

  function rowTemplate(item) {
    const selectedClass = item.number === selectedNumber ? " is-selected" : "";
    const reservedClass = item.state === "reserved" ? " is-reserved" : "";
    return `
      <tr class="business-row${selectedClass}${reservedClass}" data-business-number="${item.number}" tabindex="0" aria-selected="${item.number === selectedNumber}">
        <td>
          <div class="business-id">
            <span class="business-number">${pad(item.number)}</span>
            <span class="business-title">
              <strong>${item.title}</strong>
              <span>${item.koreanTitle}</span>
            </span>
          </div>
        </td>
        <td><span class="status-badge status-${item.state}">${stateLabel(item.state)}</span></td>
        <td class="progress-cell">
          <div class="progress-label"><span>${t("demoShort")}</span><span>${item.progress}%</span></div>
          <div class="progress-track"><i style="width:${item.progress}%"></i></div>
        </td>
        <td class="mono-cell">${item.surfaceType}</td>
        <td class="mono-cell">${item.githubLabel}</td>
        <td class="action-cell">${item.nextAction}</td>
      </tr>
    `;
  }

  function renderTable() {
    const visible = filteredBusinesses();
    tableBody.innerHTML = visible.map(rowTemplate).join("") || `<tr><td colspan="6" class="empty-state">${t("noResults")}</td></tr>`;
    $("#result-count").textContent = `${visible.length} ${t("rows")}`;

    tableBody.querySelectorAll(".business-row").forEach((row) => {
      const select = () => selectBusiness(Number(row.dataset.businessNumber));
      row.addEventListener("click", select);
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          select();
        }
      });
    });
  }

  function configureLink(selector, url) {
    const link = $(selector);
    if (url) {
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.tabIndex = 0;
      link.classList.remove("is-disabled");
      link.removeAttribute("aria-disabled");
    } else {
      link.removeAttribute("href");
      link.removeAttribute("target");
      link.removeAttribute("rel");
      link.tabIndex = -1;
      link.classList.add("is-disabled");
      link.setAttribute("aria-disabled", "true");
    }
  }

  function selectBusiness(number) {
    const item = businesses.find((business) => business.number === number);
    if (!item) return;
    selectedNumber = number;
    $("#detail-number").textContent = `${t("business")} ${pad(item.number)}`;
    $("#detail-status").className = `status-badge status-${item.state}`;
    $("#detail-status").textContent = stateLabel(item.state);
    $("#detail-title").textContent = item.title;
    $("#detail-korean").textContent = item.koreanTitle;
    $("#detail-progress-value").textContent = `${item.progress}%`;
    $("#detail-progress-bar").style.width = `${item.progress}%`;
    $("#detail-lifecycle").textContent = item.lifecycle;
    $("#detail-workspace").textContent = item.workspace;
    $("#detail-deployment").textContent = item.deployment;
    $("#detail-github").textContent = item.githubLabel;
    $("#detail-verified").textContent = item.lastVerified;
    $("#detail-next-action").textContent = item.nextAction;
    configureLink("#surface-link", item.surfaceUrl);
    configureLink("#github-link", item.githubUrl);
    configureLink("#issue-link", item.issueUrl);
    $("#action-note").textContent = item.surfaceUrl
      ? t("actionNoteWithSurface")
      : t("actionNoteNoSurface");
    renderTable();
  }

  function renderPriorityActions() {
    const actions = businesses
      .filter((item) => item.priority > 0 && item.state !== "reserved")
      .sort((a, b) => b.priority - a.priority)
      .slice(0, 6);

    $("#priority-count").textContent = `${actions.length} ${t("items")}`;
    $("#priority-list").innerHTML = actions.map((item) => `
      <button class="priority-item" type="button" data-priority-number="${item.number}">
        <span class="priority-number">BIZ ${pad(item.number)}</span>
        <span class="priority-title">${item.title}</span>
        <span class="priority-action">${item.nextAction}</span>
        <span class="priority-score">P${item.priority}</span>
      </button>
    `).join("");

    document.querySelectorAll("[data-priority-number]").forEach((button) => {
      button.addEventListener("click", () => selectBusiness(Number(button.dataset.priorityNumber)));
    });
  }

  [searchInput, stateFilter, sortControl].forEach((control) => {
    control.addEventListener(control === searchInput ? "input" : "change", renderTable);
  });

  function computeProjectProgress(item) {
    const progress = computeProgress(item.milestoneTasks);
    if (!progress.hasProgress) return null;
    return progress.progressPercent;
  }

  function sortedProjects(items, sortValue) {
    if (sortValue === "default") return items;
    return items.slice().sort((a, b) => {
      const progressA = computeProjectProgress(a);
      const progressB = computeProjectProgress(b);
      if (progressA === null && progressB === null) return 0;
      if (progressA === null) return 1;
      if (progressB === null) return -1;
      if (sortValue === "progress-desc") return progressB - progressA;
      return progressA - progressB;
    });
  }

  function formatResultCount(total, visible) {
    if (currentLang === "ko") {
      return `${total}${t("projects")} 중 ${visible}${t("projects")}`;
    }
    return `${visible} of ${total} ${t("projects")}`;
  }

  function filteredProjects() {
    const query = ($("#pd-search-input")?.value || "").trim().toLowerCase();
    const stage = $("#pd-stage-filter")?.value || "all";
    const devMode = $("#pd-dev-mode-filter")?.value || "all";
    const sort = $("#pd-sort-filter")?.value || "default";
    const filtered = projects.filter((item) => {
      const haystack = `${item.name} ${item.koreanName} ${item.businessNumber || ""} ${item.purpose} ${item.repositoryLabel} ${item.workspace} ${item.currentWork} ${item.nextAction}`.toLowerCase();
      return (!query || haystack.includes(query)) && (stage === "all" || item.stage === stage) && (devMode === "all" || item.developmentMode === devMode);
    });
    return sortedProjects(filtered, sort);
  }

  function projectCardTemplate(item) {
    const selectedClass = item.id === selectedProjectId ? " is-selected" : "";
    const bizLabel = item.businessNumber ? `BIZ ${pad(item.businessNumber)}` : "";
    const hasPageUrl = Boolean(item.pageUrl);
    const undeployedBadge = hasPageUrl
      ? ""
      : `<span class="pd-card-undeployed" title="${t('notDeployed')}">${t('notDeployed')}</span>`;
    const progress = computeProgress(item.milestoneTasks);
    const milestoneSection = progress.hasProgress
      ? `<div class="pd-card-milestone">
          <span class="pd-card-milestone-name">${item.currentMilestone}</span>
          <div class="pd-card-progress-row">
            <span class="pd-card-pct">${t("doneShort")} ${progress.progressPercent}%</span>
            <span class="pd-card-pct">${t("remainingShort")} ${progress.remainingPercent}%</span>
          </div>
          <div class="pd-card-bar"><i style="width:${progress.progressPercent}%"></i></div>
        </div>`
      : `<div class="pd-card-milestone pd-card-milestone-undefined">
          <span>${t("progressUndefined")}</span>
          <span>${t("goalDefinitionNeeded")}</span>
        </div>`;
    const cardBody = `
      <div class="pd-card-top">
        <span class="pd-card-name">${item.name}</span>
        <span class="status-badge status-${item.stage}">${stageLabel(item.stage)}</span>
        ${undeployedBadge}
      </div>
      <span class="pd-card-korean">${item.koreanName}${bizLabel ? ` · ${bizLabel}` : ""}</span>
      <div class="pd-card-badges">
        <span class="pd-mode-badge">${developmentModeLabel(item.developmentMode)}</span>
      </div>
      ${milestoneSection}
      <div class="pd-card-meta">
        <span>${item.repositoryLabel}</span>
        <span>${item.workspace}</span>
      </div>
      <span class="pd-card-work">${item.currentWork}</span>
      <span class="pd-card-next">${item.nextAction}</span>
    `;

    if (hasPageUrl) {
      return `
        <article class="pd-card${selectedClass}" data-project-id="${item.id}" data-has-page-url="true">
          <a class="pd-card-service-link" href="${item.pageUrl}" target="_blank" rel="noopener noreferrer">
            ${cardBody}
          </a>
          <button type="button" class="pd-card-detail-btn" aria-label="${t('viewDetail')}">${t('viewDetail')}</button>
        </article>
      `;
    }

    return `
      <article class="pd-card${selectedClass}" data-project-id="${item.id}" data-has-page-url="false">
        <div class="pd-card-main">
          ${cardBody}
        </div>
        <button type="button" class="pd-card-detail-btn" aria-label="${t('viewDetail')}">${t('viewDetail')}</button>
      </article>
    `;
  }

  function renderProjectDirectory() {
    const grid = $("#pd-grid");
    if (!grid) return;
    const visible = filteredProjects();
    grid.innerHTML = visible.map(projectCardTemplate).join("") || `<div class="empty-state">${t("noProjects")}</div>`;
    $("#project-count").textContent = formatResultCount(projects.length, visible.length);
    $("#pd-result-count").textContent = formatResultCount(projects.length, visible.length);

    grid.querySelectorAll(".pd-card").forEach((card) => {
      const projectId = card.dataset.projectId;
      const hasPageUrl = card.dataset.hasPageUrl === "true";

      card.addEventListener("click", (event) => {
        if (event.target.closest(".pd-card-detail-btn")) {
          selectProject(projectId);
          return;
        }
        if (!hasPageUrl) {
          selectProject(projectId);
        }
      });
    });
  }

  function configureProjectLink(selector, url) {
    const link = $(selector);
    if (!link) return;
    if (url) {
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.tabIndex = 0;
      link.classList.remove("is-disabled");
      link.removeAttribute("aria-disabled");
    } else {
      link.removeAttribute("href");
      link.removeAttribute("target");
      link.removeAttribute("rel");
      link.tabIndex = -1;
      link.classList.add("is-disabled");
      link.setAttribute("aria-disabled", "true");
    }
  }

  function selectProject(id) {
    const item = projects.find((project) => project.id === id);
    if (!item) return;
    selectedProjectId = id;
    $("#pd-detail-badge").className = `status-badge status-${item.stage}`;
    $("#pd-detail-badge").textContent = stageLabel(item.stage);
    $("#pd-detail-biz").textContent = item.businessNumber ? `${t("business")} ${pad(item.businessNumber)}` : "";
    $("#pd-detail-title").textContent = item.name;
    $("#pd-detail-korean").textContent = item.koreanName;
    $("#pd-detail-purpose").textContent = item.purpose;
    $("#pd-detail-repo").textContent = item.repositoryLabel;
    $("#pd-detail-workspace").textContent = item.workspace;
    $("#pd-detail-page").textContent = item.pageUrl || t("notDeployed");
    $("#pd-detail-mode").textContent = developmentModeLabel(item.developmentMode);
    $("#pd-detail-milestone").textContent = item.currentMilestone || t("progressUndefined");
    $("#pd-detail-basis").textContent = item.progressBasis || "—";
    const progress = computeProgress(item.milestoneTasks);
    if (progress.hasProgress) {
      $("#pd-detail-progress").textContent = `${t("doneShort")} ${progress.progressPercent}% · ${t("remainingShort")} ${progress.remainingPercent}% (${progress.doneCount}/${progress.totalCount})`;
      $("#pd-detail-progress-bar").style.width = `${progress.progressPercent}%`;
      $("#pd-detail-progress-track").style.display = "";
    } else {
      $("#pd-detail-progress").textContent = `${t("progressUndefined")} · ${t("goalDefinitionNeeded")}`;
      $("#pd-detail-progress-bar").style.width = "0%";
      $("#pd-detail-progress-track").style.display = "none";
    }
    const doneTasks = item.milestoneTasks.filter(task => task.done);
    const remainingTasks = item.milestoneTasks.filter(task => !task.done);
    $("#pd-detail-done-tasks").innerHTML = doneTasks.length > 0
      ? doneTasks.map(task => `<li>${task.label} — ${task.evidence}</li>`).join("")
      : `<li>—</li>`;
    $("#pd-detail-remaining-tasks").innerHTML = remainingTasks.length > 0
      ? remainingTasks.map(task => `<li>${task.label} — ${task.evidence}</li>`).join("")
      : `<li>—</li>`;
    $("#pd-detail-blockers").textContent = item.blockers.length > 0 ? item.blockers.join(", ") : "—";
    $("#pd-detail-current").textContent = item.currentWork;
    $("#pd-detail-verified").textContent = item.lastVerified;
    $("#pd-detail-next").textContent = item.nextAction;
    configureProjectLink("#pd-page-link", item.pageUrl);
    configureProjectLink("#pd-repo-link", item.repositoryUrl);
    const copyBtn = $("#pd-copy-workspace");
    if (item.workspace === "확인 필요") {
      copyBtn.disabled = true;
      copyBtn.classList.add("is-disabled");
    } else {
      copyBtn.disabled = false;
      copyBtn.classList.remove("is-disabled");
    }
    $("#pd-copy-note").textContent = "";
    renderProjectDirectory();
  }

  function initProjectDirectory() {
    const pdSearch = $("#pd-search-input");
    const pdStage = $("#pd-stage-filter");
    const pdDevMode = $("#pd-dev-mode-filter");
    const pdSort = $("#pd-sort-filter");
    const pdReset = $("#pd-reset-filter");
    if (pdSearch) pdSearch.addEventListener("input", renderProjectDirectory);
    if (pdStage) pdStage.addEventListener("change", renderProjectDirectory);
    if (pdDevMode) pdDevMode.addEventListener("change", renderProjectDirectory);
    if (pdSort) pdSort.addEventListener("change", renderProjectDirectory);

    if (pdReset) {
      pdReset.addEventListener("click", resetFilters);
    }

    const copyButton = $("#pd-copy-workspace");
    if (copyButton) {
      copyButton.addEventListener("click", () => {
        const item = projects.find((project) => project.id === selectedProjectId);
        if (!item) return;

        if (!navigator.clipboard || !navigator.clipboard.writeText) {
          $("#pd-copy-note").textContent = t("copyFail");
          setTimeout(() => { $("#pd-copy-note").textContent = ""; }, 2000);
          return;
        }

        navigator.clipboard.writeText(item.workspace).then(() => {
          $("#pd-copy-note").textContent = `${t("copySuccess")}: ${item.workspace}`;
          setTimeout(() => { $("#pd-copy-note").textContent = ""; }, 2000);
        }).catch(() => {
          $("#pd-copy-note").textContent = t("copyFail");
          setTimeout(() => { $("#pd-copy-note").textContent = ""; }, 2000);
        });
       });
     }
   }

  function resetFilters() {
    const searchInput = $("#pd-search-input");
    const stageFilter = $("#pd-stage-filter");
    const devModeFilter = $("#pd-dev-mode-filter");
    const sortFilter = $("#pd-sort-filter");
    if (searchInput) searchInput.value = "";
    if (stageFilter) stageFilter.value = "all";
    if (devModeFilter) devModeFilter.value = "all";
    if (sortFilter) sortFilter.value = "default";
    renderProjectDirectory();
  }

  function openSearchPanel() {
    const panel = $("#project-search-panel");
    const trigger = document.querySelector('[data-project-view="search"]');
    if (!panel || !trigger) return;
    panel.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    trigger.classList.add("is-active");
    const projectsBtn = document.querySelector('[data-project-view="projects"]');
    if (projectsBtn) {
      projectsBtn.classList.remove("is-active");
      projectsBtn.removeAttribute("aria-current");
    }
    const searchInput = $("#pd-search-input");
    if (searchInput) searchInput.focus();
  }

  function closeSearchPanel() {
    const panel = $("#project-search-panel");
    const trigger = document.querySelector('[data-project-view="search"]');
    if (!panel || !trigger) return;
    panel.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    trigger.classList.remove("is-active");
    const projectsBtn = document.querySelector('[data-project-view="projects"]');
    if (projectsBtn) {
      projectsBtn.classList.add("is-active");
      projectsBtn.setAttribute("aria-current", "page");
    }
  }

  function updateProjectNavLabels() {
    $("#nav-projects").textContent = t("projectStatus");
    $("#nav-search-filter").textContent = t("searchFilter");
    $("#project-search-title").textContent = t("searchFilter");
    $("#pd-reset-filter").textContent = t("reset");
    $("#pd-search-input").placeholder = t("searchPlaceholder");
    $("#project-search-close").setAttribute("aria-label", t("closePanel"));
    $("#pd-stage-filter option[value='all']").textContent = t("all");
    $("#pd-stage-filter option[value='live']").textContent = stageLabel("live");
    $("#pd-stage-filter option[value='building']").textContent = stageLabel("building");
    $("#pd-stage-filter option[value='review']").textContent = stageLabel("review");
    $("#pd-stage-filter option[value='planned']").textContent = stageLabel("planned");
    $("#pd-stage-filter option[value='paused']").textContent = stageLabel("paused");
    $("#pd-dev-mode-filter option[value='all']").textContent = t("all");
    $("#pd-dev-mode-filter option[value='not-started']").textContent = developmentModeLabel("not-started");
    $("#pd-dev-mode-filter option[value='active-development']").textContent = developmentModeLabel("active-development");
    $("#pd-dev-mode-filter option[value='needs-improvement']").textContent = developmentModeLabel("needs-improvement");
    $("#pd-dev-mode-filter option[value='maintenance']").textContent = developmentModeLabel("maintenance");
    $("#pd-dev-mode-filter option[value='complete']").textContent = developmentModeLabel("complete");
    $("#pd-dev-mode-filter option[value='paused']").textContent = developmentModeLabel("paused");
    $("#pd-sort-filter option[value='default']").textContent = t("sortDefault");
    $("#pd-sort-filter option[value='progress-desc']").textContent = t("sortProgressDesc");
    $("#pd-sort-filter option[value='progress-asc']").textContent = t("sortProgressAsc");
  }

  function updateStaticLabels() {
    $("#topbar-title").textContent = t("businessOperations");
    $("#project-directory-heading").textContent = t("projectDirectory");
    $("#registry-heading").textContent = t("businessRegistry");
    $("#activity-heading").textContent = t("priorityActions");
    $("#pd-search-label").textContent = t("search");
    $("#pd-stage-label").textContent = t("stage");
    $("#pd-detail-repo-label").textContent = t("repository");
    $("#pd-detail-workspace-label").textContent = t("workspace");
    $("#pd-detail-page-label").textContent = t("page");
    $("#pd-detail-mode-label").textContent = t("devMode");
    $("#pd-detail-milestone-label").textContent = t("milestone");
    $("#pd-detail-basis-label").textContent = t("progressBasis");
    $("#pd-detail-progress-label").textContent = t("progress");
    $("#pd-detail-done-label").textContent = t("doneTasks");
    $("#pd-detail-remaining-label").textContent = t("remainingTasks");
    $("#pd-detail-blockers-label").textContent = t("blockersLabel");
    $("#pd-detail-current-label").textContent = t("currentWork");
    $("#pd-detail-verified-label").textContent = t("lastVerified");
    $("#pd-next-action-label").textContent = t("nextAction");
    $("#pd-page-link").textContent = t("openPage");
    $("#pd-repo-link").textContent = t("openRepository");
    $("#pd-copy-workspace").textContent = t("copyWorkspace");
    $("#all-projects-label").textContent = t("allProjects");
    $("#pd-stage-filter option[value='all']").textContent = t("all");
    $("#pd-stage-filter option[value='live']").textContent = stageLabel("live");
    $("#pd-stage-filter option[value='building']").textContent = stageLabel("building");
    $("#pd-stage-filter option[value='review']").textContent = stageLabel("review");
    $("#pd-stage-filter option[value='planned']").textContent = stageLabel("planned");
    $("#pd-stage-filter option[value='paused']").textContent = stageLabel("paused");
    $("#search-label").textContent = t("search");
    $("#state-label").textContent = t("state");
    $("#sort-label").textContent = t("sort");
    $("#state-filter option[value='all']").textContent = t("allStates");
    $("#state-filter option[value='running']").textContent = t("running");
    $("#state-filter option[value='review']").textContent = t("reviewBuild");
    $("#state-filter option[value='planning']").textContent = t("planning");
    $("#state-filter option[value='reserved']").textContent = t("reserved");
    $("#sort-control option[value='number-asc']").textContent = t("numberAsc");
    $("#sort-control option[value='number-desc']").textContent = t("numberDesc");
    $("#sort-control option[value='priority']").textContent = t("actionPriority");
    $("#sort-control option[value='progress']").textContent = t("progressSort");
    $("#th-business").textContent = t("business");
    $("#th-state").textContent = t("state");
    $("#th-progress").textContent = t("progress");
    $("#th-surface").textContent = t("surface");
    $("#th-github").textContent = t("github");
    $("#th-next-action").textContent = t("nextActionCol");
    $("#detail-progress-label").textContent = t("demoReadiness");
    $("#detail-lifecycle-label").textContent = t("lifecycle");
    $("#detail-workspace-label").textContent = t("workspace");
    $("#detail-deployment-label").textContent = t("deployment");
    $("#detail-github-label").textContent = t("github");
    $("#detail-verified-label").textContent = t("lastVerified");
    $("#detail-next-action-label").textContent = t("nextAction");
    $("#surface-link").textContent = t("openSurface");
    $("#github-link").textContent = t("openGithub");
    $("#issue-link").textContent = t("openIssue");
    $("#metric-tracked-label").textContent = t("tracked");
    $("#metric-demo-label").textContent = t("demoSurfaces");
    $("#metric-action-label").textContent = t("needsAction");
    $("#metric-open-label").textContent = t("openSlots");
    $("#metric-tracked-desc").textContent = t("trackedDesc");
    $("#metric-demo-desc").textContent = t("demoDesc");
    $("#metric-action-desc").textContent = t("actionDesc");
    $("#metric-open-desc").textContent = t("openDesc");
    $("#sidebar-mode-label").textContent = t("mode");
    $("#sidebar-source-label").textContent = t("source");
    $("#sidebar-range-label").textContent = t("range");
    $("#sidebar-mode-value").textContent = t("manual");
    $("#sidebar-source-value").textContent = t("staticRegistry");
    $("#private-admin-label").textContent = t("privateAdmin");
    $("#nav-businesses").textContent = t("businesses");
    $("#nav-deployments").textContent = t("deployments");
    $("#nav-models").textContent = t("modelsCost");
    $("#nav-registry").textContent = t("registry");
    $("#sync-state-text").textContent = t("registryLoaded");
    $("#lang-ko").textContent = t("langKo");
    $("#lang-en").textContent = t("langEn");
    updateProjectNavLabels();
  }

  function setLanguage(lang) {
    currentLang = lang;
    document.documentElement.lang = lang === "en" ? "en" : "ko";
    $("#lang-ko").classList.toggle("is-active", lang === "ko");
    $("#lang-en").classList.toggle("is-active", lang === "en");
    updateStaticLabels();
    renderTable();
    renderPriorityActions();
    renderProjectDirectory();
    if (selectedNumber) selectBusiness(selectedNumber);
    if (selectedProjectId) selectProject(selectedProjectId);
  }

  $("#refresh-button").addEventListener("click", () => window.location.reload());
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach((nav) => nav.classList.remove("is-active"));
      item.classList.add("is-active");
      if (item.dataset.view !== "businesses") {
        $("#action-note").textContent = `${item.textContent.trim()} 화면은 다음 단계에서 연결할 수 있습니다.`;
      }
    });
  });

  $("#lang-ko").addEventListener("click", () => setLanguage("ko"));
  $("#lang-en").addEventListener("click", () => setLanguage("en"));

  const navProjectsBtn = document.querySelector('[data-project-view="projects"]');
  const navSearchBtn = document.querySelector('[data-project-view="search"]');
  const closePanelBtn = $("#project-search-close");

  if (navProjectsBtn) {
    navProjectsBtn.addEventListener("click", () => {
      closeSearchPanel();
      resetFilters();
    });
  }

  if (navSearchBtn) {
    navSearchBtn.addEventListener("click", () => {
      openSearchPanel();
    });
  }

  if (closePanelBtn) {
    closePanelBtn.addEventListener("click", () => {
      closeSearchPanel();
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      const panel = $("#project-search-panel");
      if (panel && !panel.hidden) {
        closeSearchPanel();
        if (navSearchBtn) navSearchBtn.focus();
      }
    }
  });

  updateMetrics();
  updateStaticLabels();
  renderTable();
  renderPriorityActions();
  renderProjectDirectory();
  initProjectDirectory();
  const firstAction = businesses.find((item) => item.priority === Math.max(...businesses.map((entry) => entry.priority)));
  if (firstAction) selectBusiness(firstAction.number);
  const firstProject = projects[0];
  if (firstProject) selectProject(firstProject.id);
})();
