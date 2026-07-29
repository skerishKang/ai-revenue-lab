(() => {
  "use strict";

  // ── Data ──
  const projects = Array.isArray(window.ARL_PROJECTS) ? window.ARL_PROJECTS : [];
  const businesses = Array.isArray(window.ARL_BUSINESSES) ? window.ARL_BUSINESSES : [];

  // ── DOM refs ──
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);
  const views = ['projects', 'search', 'work', 'business'];

  // ── State ──
  let currentLang = 'ko';
  let activeView = 'projects';
  let selectedProjectId = null;
  let selectedBusinessNumber = null;

  // ── Label helpers ──
  const L = {
    ko: {
      topbar: '내 비즈니스 관리',
      topbarEn: 'Business Operations',
      search: '검색',
      stage: '단계',
      devMode: '개발 모드',
      sort: '정렬',
      all: '전체',
      live: '운영 중',
      building: '개발 중',
      review: '검토 중',
      planned: '계획',
      paused: '일시 중지',
      notStarted: '시작 전',
      activeDev: '개발 중',
      needsImprove: '개선 필요',
      maintenance: '유지보수',
      complete: '완료',
      sortDefault: '기본순',
      sortProgressDesc: '진행률 높은 순',
      sortProgressAsc: '진행률 낮은 순',
      reset: '초기화',
      workSummary: '작업 중 {total} · 보완/검토 {review} · 계속 개발 {active}',
      project: 'PROJECT',
      detail: '자세히 보기',
      openService: '서비스 열기',
      bizSearch: '번호, 제목 검색',
      allStates: '전체 상태',
      running: '운영 중',
      reviewBuild: '검토 / 개발',
      planning: '계획',
      reserved: '예약',
      numberAsc: '번호 ↑',
      numberDesc: '번호 ↓',
      actionPriority: '우선순위',
      authorityLabel: '번호 권한',
      phaseLabel: '단계',
      lifecycleLabel: '생애주기',
      priorityLabel: '우선순위',
      authCanonical: '정식',
      authProposed: '제안 번호',
      authCandidate: '후보',
      authExisting: '기존 프로젝트',
      authReserved: '예약',
      authReconciliation: '번호 조정 필요',
      phaseNotStarted: '미시작',
      phaseInProgress: '진행 중',
      phaseNotReady: '미완료',
      phaseConditionallyReady: '조건부 승인',
      phaseApproved: '승인',
      phaseBlockedByUi: 'UI 승인 대기',
      phaseFrozen: '동결',
      phaseDecisionPending: '결정 대기',
      phaseAuthorized: '승인됨',
      phaseImplemented: '구현됨',
      phaseNotApplicable: '해당 없음',
      phaseDeferred: '연기',
      progressSort: '진행률',
      viewDetail: '자세히 보기',
      notDeployed: '미배포',
      bizLabel: '비즈니스',
      purpose: '목적',
      milestone: '마일스톤',
      currentWork: '현재 작업',
      nextAction: '다음 작업',
      repo: '저장소',
      workspace: '폴더',
      page: '페이지',
      stageLabel: '단계',
      devModeLabel: '개발 모드',
      progressLabel: '진행 상황',
      progressUndefined: '진척도 미정',
      goalDefNeeded: '목표 정의 필요',
      statusLabel: '상태',
      nextActionLabel: '다음 작업',
      lastVerified: '마지막 확인',
      blocks: '차단 사항',
      projectCount: '{n}개 프로젝트',
      searchCount: '{n}개 중 {m}개',
      workInProgress: '작업 중',
      copyWorkspace: '복사',
      githubStatus: 'GitHub 상태',
      githubCardDisconnected: 'GitHub 자동 동기화 미연결',
      githubDisconnected: '자동 동기화 미연결',
      progressBasis: '진척 기준',
      completedTasks: '완료 작업',
      remainingTasks: '남은 작업',
      noCompletedTasks: '완료된 작업 없음',
      noRemainingTasks: '남은 작업 없음',
      repository: '저장소',
    },
    en: {
      topbar: 'Business Operations',
      topbarEn: 'Business Operations',
      search: 'SEARCH',
      stage: 'STAGE',
      devMode: 'DEV MODE',
      sort: 'SORT',
      all: 'ALL',
      live: 'LIVE',
      building: 'BUILDING',
      review: 'REVIEW',
      planned: 'PLANNED',
      paused: 'PAUSED',
      notStarted: 'NOT STARTED',
      activeDev: 'ACTIVE DEV',
      needsImprove: 'NEEDS IMPROVEMENT',
      maintenance: 'MAINTENANCE',
      complete: 'COMPLETE',
      sortDefault: 'DEFAULT',
      sortProgressDesc: 'PROGRESS DESC',
      sortProgressAsc: 'PROGRESS ASC',
      reset: 'RESET',
      workSummary: 'WIP {total} · Review {review} · Active {active}',
      project: 'PROJECT',
      detail: 'VIEW DETAIL',
      openService: 'OPEN SERVICE',
      bizSearch: 'Search by number, title',
      allStates: 'ALL STATES',
      running: 'RUNNING',
      reviewBuild: 'REVIEW / BUILD',
      planning: 'PLANNING',
      reserved: 'RESERVED',
      numberAsc: 'NUMBER ↑',
      numberDesc: 'NUMBER ↓',
      actionPriority: 'PRIORITY',
      authorityLabel: 'NUMBER AUTHORITY',
      phaseLabel: 'PHASE',
      lifecycleLabel: 'LIFECYCLE',
      priorityLabel: 'PRIORITY',
      authCanonical: 'CANONICAL',
      authProposed: 'PROPOSED NUMBER',
      authCandidate: 'CANDIDATE',
      authExisting: 'EXISTING PROJECT',
      authReserved: 'RESERVED',
      authReconciliation: 'RECONCILIATION REQUIRED',
      phaseNotStarted: 'NOT STARTED',
      phaseInProgress: 'IN PROGRESS',
      phaseNotReady: 'NOT READY',
      phaseConditionallyReady: 'CONDITIONALLY READY',
      phaseApproved: 'APPROVED',
      phaseBlockedByUi: 'BLOCKED BY UI',
      phaseFrozen: 'FROZEN',
      phaseDecisionPending: 'DECISION PENDING',
      phaseAuthorized: 'AUTHORIZED',
      phaseImplemented: 'IMPLEMENTED',
      phaseNotApplicable: 'NOT APPLICABLE',
      phaseDeferred: 'DEFERRED',
      progressSort: 'PROGRESS',
      viewDetail: 'VIEW DETAIL',
      notDeployed: 'NOT DEPLOYED',
      bizLabel: 'BIZ',
      purpose: 'PURPOSE',
      milestone: 'MILESTONE',
      currentWork: 'CURRENT WORK',
      nextAction: 'NEXT ACTION',
      repo: 'REPOSITORY',
      workspace: 'WORKSPACE',
      page: 'PAGE',
      stageLabel: 'STAGE',
      devModeLabel: 'DEV MODE',
      progressLabel: 'PROGRESS',
      progressUndefined: 'PROGRESS UNDEFINED',
      goalDefNeeded: 'GOAL DEFINITION NEEDED',
      statusLabel: 'STATE',
      nextActionLabel: 'NEXT ACTION',
      lastVerified: 'LAST VERIFIED',
      blocks: 'BLOCKERS',
      projectCount: '{n} projects',
      searchCount: '{m} of {n} projects',
      workInProgress: 'IN PROGRESS',
      copyWorkspace: 'COPY',
      githubStatus: 'GITHUB STATUS',
      githubCardDisconnected: 'GITHUB LIVE SYNC NOT CONNECTED',
      githubDisconnected: 'GITHUB LIVE SYNC NOT CONNECTED',
      progressBasis: 'PROGRESS BASIS',
      completedTasks: 'COMPLETED TASKS',
      remainingTasks: 'REMAINING TASKS',
      noCompletedTasks: 'NO COMPLETED TASKS',
      noRemainingTasks: 'NO REMAINING TASKS',
      repository: 'REPOSITORY',
    }
  };

  function t(key, vars = {}) {
    let str = L[currentLang][key] || L.ko[key] || key;
    for (const [k, v] of Object.entries(vars)) str = str.replace(`{${k}}`, v);
    return str;
  }

  // ── Stage labels ──
  const stageL = {
    live: { ko: '운영 중', en: 'LIVE' },
    building: { ko: '개발 중', en: 'BUILDING' },
    review: { ko: '검토 중', en: 'REVIEW' },
    planned: { ko: '계획', en: 'PLANNED' },
    paused: { ko: '일시 중지', en: 'PAUSED' }
  };
  function stageLabel(s) { return stageL[s]?.[currentLang] || s; }

  // ── Dev mode labels ──
  const devL = {
    'not-started': { ko: '시작 전', en: 'NOT STARTED' },
    'active-development': { ko: '개발 중', en: 'ACTIVE DEV' },
    'needs-improvement': { ko: '개선 필요', en: 'NEEDS IMPROVEMENT' },
    'maintenance': { ko: '유지보수', en: 'MAINTENANCE' },
    'complete': { ko: '완료', en: 'COMPLETE' },
    'paused': { ko: '일시 중지', en: 'PAUSED' }
  };
  function devLabel(m) { return devL[m]?.[currentLang] || m; }

  // ── State labels (businesses) ──
  const stateL = {
    running: { ko: '운영 중', en: 'RUNNING' },
    review: { ko: '검토 중', en: 'REVIEW' },
    planning: { ko: '계획', en: 'PLANNING' },
    reserved: { ko: '예약', en: 'RESERVED' }
  };
  function stateLabel(s) { return stateL[s]?.[currentLang] || s; }

  // ── Progress helper ──
  function computeProgress(tasks) {
    if (!Array.isArray(tasks) || tasks.length === 0) return null;
    const done = tasks.filter(t => t.done).length;
    return { done, total: tasks.length, pct: Math.round((done / tasks.length) * 100) };
  }

  // ── Pad ──
  function pad(n) { return String(n).padStart(2, '0'); }

  // ── Business number display ──
  function bizDisplay(project) {
    if (project.businessNumber != null) return `B${pad(project.businessNumber)}`;
    return t('project');
  }
  const cardBizNumber = bizDisplay;

  function formatProjectUnitCount(count) {
    return currentLang === 'ko' ? `${count}개` : `${count} projects`;
  }

  function formatResultCount(total, visible) {
    if (currentLang === 'ko') return `${total}개 중 ${visible}개`;
    return `${visible} of ${total} projects`;
  }

  function isWIP(p) {
    return ['building', 'review'].includes(p.stage) || ['active-development', 'needs-improvement'].includes(p.developmentMode);
  }
  function isReviewGroup(p) {
    return p.developmentMode === 'needs-improvement' || p.stage === 'review';
  }
  function isActiveGroup(p) {
    if (isReviewGroup(p)) return false;
    return ['active-development', 'building'].includes(p.developmentMode) || p.stage === 'building';
  }

  // ── Theme ──
  function initTheme() {
    const stored = localStorage.getItem('arl-portfolio-theme');
    const theme = (stored === 'dark' || stored === 'light') ? stored : 'dark';
    document.documentElement.setAttribute('data-theme', theme);
    const btn = $('#theme-toggle');
    if (btn) btn.textContent = theme === 'dark' ? '🌙' : '☀️';
    return theme;
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem("arl-portfolio-theme", next);
    const btn = $('#theme-toggle');
    if (btn) btn.textContent = next === 'dark' ? '🌙' : '☀️';
  }

  // ── Language ──
  function setLanguage(lang) {
    currentLang = lang;
    document.documentElement.lang = lang === 'ko' ? 'ko' : 'en';
    // Update data-label-ko / data-label-en elements
    $$('[data-label-ko][data-label-en]').forEach(function(el) {
      el.textContent = el.getAttribute('data-label-' + lang);
    });
    // Update filter option text for business filters
    var authFilter = $('#biz-auth-filter');
    if (authFilter) {
      var authOpts = {
        'all': lang === 'ko' ? '전체' : 'ALL',
        'canonical': lang === 'ko' ? '정식' : 'CANONICAL',
        'proposed-number': lang === 'ko' ? '제안 번호' : 'PROPOSED NUMBER',
        'candidate': lang === 'ko' ? '후보' : 'CANDIDATE',
        'existing-project': lang === 'ko' ? '기존 프로젝트' : 'EXISTING PROJECT',
        'reserved': lang === 'ko' ? '예약' : 'RESERVED',
        'number-reconciliation-required': lang === 'ko' ? '번호 조정 필요' : 'RECONCILIATION REQUIRED',
      };
      Array.from(authFilter.options).forEach(function(o) { if (authOpts[o.value]) o.textContent = authOpts[o.value]; });
    }
    var uiFilter = $('#biz-ui-filter');
    if (uiFilter) {
      var uiOpts = {
        'all': lang === 'ko' ? '전체' : 'ALL',
        'NOT_STARTED': lang === 'ko' ? '미시작' : 'NOT STARTED',
        'IN_PROGRESS': lang === 'ko' ? '진행 중' : 'IN PROGRESS',
        'UI_NOT_READY': lang === 'ko' ? '미완료' : 'NOT READY',
        'UI_CONDITIONALLY_READY': lang === 'ko' ? '조건부 승인' : 'CONDITIONALLY READY',
        'UI_APPROVED': lang === 'ko' ? '승인' : 'APPROVED',
        'BLOCKED_BY_UI': lang === 'ko' ? 'UI 승인 대기' : 'BLOCKED BY UI',
      };
      Array.from(uiFilter.options).forEach(function(o) { if (uiOpts[o.value]) o.textContent = uiOpts[o.value]; });
    }
    var uxFilter = $('#biz-ux-filter');
    if (uxFilter) {
      var uxOpts = {
        'all': lang === 'ko' ? '전체' : 'ALL',
        'NOT_STARTED': lang === 'ko' ? '미시작' : 'NOT STARTED',
        'IN_PROGRESS': lang === 'ko' ? '진행 중' : 'IN PROGRESS',
        'BLOCKED_BY_UI': lang === 'ko' ? 'UI 대기' : 'BLOCKED BY UI',
        'UX_APPROVED': lang === 'ko' ? '승인' : 'APPROVED',
      };
      Array.from(uxFilter.options).forEach(function(o) { if (uxOpts[o.value]) o.textContent = uxOpts[o.value]; });
    }
    var beFilter = $('#biz-be-filter');
    if (beFilter) {
      var beOpts = {
        'all': lang === 'ko' ? '전체' : 'ALL',
        'FROZEN': lang === 'ko' ? '동결' : 'FROZEN',
        'DECISION_PENDING': lang === 'ko' ? '결정 대기' : 'DECISION PENDING',
        'AUTHORIZED': lang === 'ko' ? '승인됨' : 'AUTHORIZED',
        'IN_PROGRESS': lang === 'ko' ? '진행 중' : 'IN PROGRESS',
        'IMPLEMENTED': lang === 'ko' ? '구현됨' : 'IMPLEMENTED',
        'NOT_APPLICABLE': lang === 'ko' ? '해당 없음' : 'NOT APPLICABLE',
        'DEFERRED': lang === 'ko' ? '연기' : 'DEFERRED',
      };
      Array.from(beFilter.options).forEach(function(o) { if (beOpts[o.value]) o.textContent = beOpts[o.value]; });
    }
    applyTranslations();
    updateActiveView();
  }

  function applyTranslations() {
    const bizSearch = $('#biz-search-input');
    if (bizSearch) bizSearch.placeholder = t('bizSearch');
    // Update selects
    updateSelectLabels();
    // Re-render
    renderProjects();
    renderWorkView();
    renderBusinessIndex();
    updateActiveView();
    updateHeaderCount();
    // Re-render open dialog without closing
    const projectDialog = $('#project-dialog');
    if (projectDialog?.open && selectedProjectId) {
      const item = projects.find(p => p.id === selectedProjectId);
      if (item) {
        const body = $('#dialog-body');
        const title = $('#dialog-title');
        if (body && title) {
          title.textContent = item.name;
          body.innerHTML = dialogContentHTML(item);
        }
        const copyBtn = projectDialog.querySelector('#dlg-copy-workspace');
        if (copyBtn) {
          copyBtn.addEventListener('click', () => {
            const ws = copyBtn.dataset.workspace;
            if (navigator.clipboard?.writeText) {
              navigator.clipboard.writeText(ws);
            }
          });
        }
      }
    }
    // Re-render open business dialog without closing
    const businessDialog = $('#business-dialog');
    if (businessDialog?.open && selectedBusinessNumber != null) {
      const biz = businesses.find(b => b.number === selectedBusinessNumber);
      if (biz) {
        const body = $('#biz-dialog-body');
        const title = $('#biz-dialog-title');
        if (body && title) {
          title.textContent = biz.title;
          body.innerHTML = businessDialogContentHTML(biz);
        }
      }
    }
  }

  function updateSelectLabels() {
    // Stage filter
    const stageF = $('#sf-stage-filter');
    if (stageF) {
      stageF.options[0].textContent = t('all');
      stageF.options[1].textContent = stageLabel('live');
      stageF.options[2].textContent = stageLabel('building');
      stageF.options[3].textContent = stageLabel('review');
      stageF.options[4].textContent = stageLabel('planned');
      stageF.options[5].textContent = stageLabel('paused');
    }
    // Dev mode filter
    const devF = $('#sf-devmode-filter');
    if (devF) {
      devF.options[0].textContent = t('all');
      devF.options[1].textContent = devLabel('not-started');
      devF.options[2].textContent = devLabel('active-development');
      devF.options[3].textContent = devLabel('needs-improvement');
      devF.options[4].textContent = devLabel('maintenance');
      devF.options[5].textContent = devLabel('complete');
      devF.options[6].textContent = devLabel('paused');
    }
    // Sort filter
    const sortF = $('#sf-sort-filter');
    if (sortF) {
      sortF.options[0].textContent = t('sortDefault');
      sortF.options[1].textContent = t('sortProgressDesc');
      sortF.options[2].textContent = t('sortProgressAsc');
    }
    // Business sort (only 2 options: number-asc, number-desc)
    const bSort = $('#biz-sort');
    if (bSort) {
      bSort.options[0].textContent = t('numberAsc');
      bSort.options[1].textContent = t('numberDesc');
    }
  }

  // ── View navigation ──
  function switchView(view) {
    if (!views.includes(view)) return;
    activeView = view;
    // Hide all views
    views.forEach(v => {
      const el = $(`#view-${v}`);
      if (el) el.hidden = v !== view;
    });
    // Clear search grid when leaving search view
    if (view !== 'search') {
      const searchGrid = $('#search-grid');
      if (searchGrid) searchGrid.innerHTML = '';
    }
    // Update nav buttons
    $$('.view-nav-item').forEach(btn => {
      const isActive = btn.dataset.view === view;
      btn.classList.toggle('is-active', isActive);
      if (isActive) btn.setAttribute('aria-current', 'page');
      else btn.removeAttribute('aria-current');
    });
    const viewMap = { projects: renderProjects, search: renderSearchView, work: renderWorkView, business: renderBusinessIndex };
    const renderFn = viewMap[view];
    if (renderFn) renderFn();
    updateCounts();
    closeDrawer();
  }

  function updateActiveView() {
    views.forEach(v => {
      const el = $(`#view-${v}`);
      if (el) el.hidden = v !== activeView;
    });
  }

  // ── Update counts ──
  function updateHeaderCount() {
    const badge = $('#header-count');
    if (!badge) return;
    const isMobile = window.innerWidth <= 820;
    const count = activeView === 'search'
      ? t('searchCount', { n: projects.length, m: filteredProjects().length })
      : activeView === 'work'
        ? `${t('workInProgress')} ${wipProjects().length}`
        : activeView === 'business'
          ? `${t('bizLabel')} ${businesses.length}`
          : isMobile
            ? `${projects.length}${currentLang === 'ko' ? '개' : ''}`
            : t('projectCount', { n: projects.length });
    badge.textContent = count;
  }
  const updateCounts = updateHeaderCount;

  // ── Project card ──
  function projectCardHTML(item) {
    const biz = bizDisplay(item);
    const isProject = item.businessNumber == null;
    const progress = computeProgress(item.milestoneTasks);
    const hasPage = Boolean(item.pageUrl);
    const stageCls = `pd-card-stage-${item.stage}`;

    return `
      <article class="pd-card" data-project-id="${item.id}" tabindex="0" aria-label="${item.name}">
        <div class="pd-card-biznumber ${isProject ? 'project-label' : ''}">${biz}</div>
        <div class="pd-card-top">
          <span class="pd-card-name">${item.name}</span>
          <span class="pd-card-stage status-badge ${stageCls}">${stageLabel(item.stage)}</span>
        </div>
        <span class="pd-card-korean">${item.koreanName}</span>
        <span class="pd-card-purpose">${item.purpose || ''}</span>
        <span class="pd-card-milestone ${!progress ? 'pd-card-milestone-undefined' : ''}">
          ${progress ? `${item.currentMilestone || ''} — ${progress.pct}%` : `${t('progressUndefined')} · ${t('goalDefNeeded')}`}
        </span>
        <span class="pd-card-currentwork">${item.currentWork || ''}</span>
        <div class="pd-card-github-state">${t('githubCardDisconnected')}</div>
        <div class="pd-card-meta">
          <span class="pd-card-devmode">${devLabel(item.developmentMode)}</span>
        </div>
        <div class="pd-card-actions">
          <button type="button" class="pd-card-detail-btn" data-project-id="${item.id}" data-label-detail="${t('viewDetail')}">${t('viewDetail')}</button>
          ${hasPage ? `<a class="pd-card-service-link" href="${item.pageUrl}" target="_blank" rel="noopener noreferrer">${t('openService')}</a>` : ''}
        </div>
      </article>
    `;
  }

  // ── Filter helpers ──
  function filteredProjects() {
    const query = ($('#sf-search-input')?.value || '').trim().toLowerCase();
    const stage = $('#sf-stage-filter')?.value || 'all';
    const devMode = $('#sf-devmode-filter')?.value || 'all';
    const sort = $('#sf-sort-filter')?.value || 'default';

    let result = projects.filter(p => {
      const haystack = `${p.name} ${p.koreanName} ${p.businessNumber || ''} ${p.purpose || ''} ${p.repositoryLabel || ''} ${p.workspace || ''} ${p.currentWork || ''} ${p.nextAction || ''}`.toLowerCase();
      return (!query || haystack.includes(query)) &&
        (stage === 'all' || p.stage === stage) &&
        (devMode === 'all' || p.developmentMode === devMode);
    });

    if (sort === 'progress-desc' || sort === 'progress-asc') {
      result = result.slice().sort((a, b) => {
        const pa = computeProgress(a.milestoneTasks);
        const pb = computeProgress(b.milestoneTasks);
        const va = pa ? pa.pct : -1;
        const vb = pb ? pb.pct : -1;
        return sort === 'progress-desc' ? vb - va : va - vb;
      });
    }
    return result;
  }

  function wipProjects() {
    return projects.filter(isWIP);
  }

  // ── Render projects ──
  function renderProjects() {
    const gridId = activeView === 'search' ? 'search-grid' : 'pd-grid';
    const grid = $(`#${gridId}`);
    if (!grid) return;
    const visible = activeView === 'search' ? filteredProjects() : projects;
    grid.innerHTML = visible.map(projectCardHTML).join('');
    attachCardEvents(grid);
  }

  function renderSearchView() {
    renderProjects();
  }

  function attachCardEvents(grid) {
    grid.querySelectorAll('.pd-card').forEach(card => {
      card.addEventListener('click', (e) => {
        if (e.target.closest('.pd-card-detail-btn') || e.target.closest('.pd-card-service-link')) return;
        const id = card.dataset.projectId;
        openProjectDialog(id);
      });
      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          const id = card.dataset.projectId;
          openProjectDialog(id);
        }
      });
    });
    grid.querySelectorAll('.pd-card-detail-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        openProjectDialog(btn.dataset.projectId);
      });
    });
  }

  // ── Work view ──
  function renderWorkView() {
    const queue = $('#work-queue');
    if (!queue) return;
    const wip = wipProjects();
    const review = wip.filter(isReviewGroup);
    const active = wip.filter(isActiveGroup);
    const summary = $('#work-summary-text');
    if (summary) summary.textContent = t('workSummary', { total: wip.length, review: review.length, active: active.length });

    function wipItemHTML(item) {
      const progress = computeProgress(item.milestoneTasks);
      const stageCls = `pd-card-stage-${item.stage}`;
      return `
        <div class="work-item" data-project-id="${item.id}">
          <div class="work-item-top">
            <span class="work-item-name">${item.name}</span>
            <span class="pd-card-stage status-badge ${stageCls}">${stageLabel(item.stage)}</span>
            <span class="pd-card-devmode">${devLabel(item.developmentMode)}</span>
          </div>
          <span class="work-item-korean">${item.koreanName}</span>
          <span class="work-item-purpose">${item.purpose || ''}</span>
          <span class="work-item-current">${item.currentWork || ''}</span>
          <span class="work-item-progress">${progress ? `— ${progress.pct}% (${progress.done}/${progress.total})` : ''}</span>
          <div class="work-item-actions">
            <button type="button" class="work-item-btn work-detail-btn" data-project-id="${item.id}">${t('viewDetail')}</button>
            ${item.pageUrl ? `<a class="work-item-btn" href="${item.pageUrl}" target="_blank" rel="noopener noreferrer" style="text-decoration:none">${t('openService')}</a>` : ''}
          </div>
        </div>
      `;
    }

    queue.innerHTML = wip.map(wipItemHTML).join('');
    queue.querySelectorAll('.work-detail-btn').forEach(btn => {
      btn.addEventListener('click', () => openProjectDialog(btn.dataset.projectId));
    });
  }

  // ── Business view ──
  function filteredBusinesses() {
    const query = ($('#biz-search-input')?.value || '').trim().toLowerCase();
    const authority = $('#biz-auth-filter')?.value || 'all';
    const uiFilter = $('#biz-ui-filter')?.value || 'all';
    const uxFilter = $('#biz-ux-filter')?.value || 'all';
    const beFilter = $('#biz-be-filter')?.value || 'all';
    const sort = $('#biz-sort')?.value || 'number-asc';

    let result = businesses.filter(b => {
      const haystack = `${b.number} ${pad(b.number)} ${b.title} ${b.koreanTitle} ${b.slug}`.toLowerCase();
      if (query && !haystack.includes(query)) return false;
      if (authority !== 'all' && b.numberAuthority !== authority) return false;
      if (uiFilter !== 'all' && b.uiStatus !== uiFilter) return false;
      if (uxFilter !== 'all' && b.uxStatus !== uxFilter) return false;
      if (beFilter !== 'all' && b.backendStatus !== beFilter) return false;
      return true;
    });

    result = result.slice().sort((a, b) => {
      if (sort === 'number-desc') return b.number - a.number;
      return a.number - b.number;
    });
    return result;
  }

  function renderBusinessIndex() {
    const list = $('#biz-list');
    if (!list) return;
    const visible = filteredBusinesses();

    list.innerHTML = visible.map(b => {
      const authCls = 'biz-auth-' + (b.numberAuthority === 'proposed-number' ? 'proposed' : b.numberAuthority === 'existing-project' ? 'existing-project' : b.numberAuthority === 'number-reconciliation-required' ? 'reconciliation' : b.numberAuthority || 'candidate');
      const uiCls = phaseBadgeClass(b.uiStatus, 'ui');
      const uxCls = phaseBadgeClass(b.uxStatus, 'ux');
      const beCls = phaseBadgeClass(b.backendStatus, 'be');
      return `
        <div class="biz-item" data-biz-number="${b.number}" tabindex="0">
          <span class="biz-number">${pad(b.number)}</span>
          <div class="biz-title-group">
            <span class="biz-title">${b.title}</span>
            <span class="biz-korean">${b.koreanTitle}</span>
            <span data-live-discovery style="font:8px/1 var(--mono);color:var(--quiet)"></span>
          </div>
          <span class="biz-auth status-badge ${authCls}">${authorityLabel(b.numberAuthority)}</span>
          <div class="biz-phase-group" style="display:flex;gap:3px;flex-wrap:wrap">
            <span class="biz-phase-badge ${uiCls}">${phaseStatusLabel(b.uiStatus)}</span>
            <span class="biz-phase-badge ${uxCls}">${phaseStatusLabel(b.uxStatus)}</span>
            <span class="biz-phase-badge ${beCls}">${phaseStatusLabel(b.backendStatus)}</span>
          </div>
        </div>
      `;
    }).join('');

    list.querySelectorAll('.biz-item').forEach(item => {
      item.addEventListener('click', () => {
        const num = Number(item.dataset.bizNumber);
        const biz = businesses.find(b => b.number === num);
        if (biz) openBusinessDialog(biz);
      });
      item.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          const num = Number(item.dataset.bizNumber);
          const biz = businesses.find(b => b.number === num);
          if (biz) openBusinessDialog(biz);
        }
      });
    });

    const headerBadge = $('#header-count');
    if (headerBadge) headerBadge.textContent = `${t('bizLabel')} ${visible.length}`;
  }

  function phaseBadgeClass(status, prefix) {
    var s = String(status || '');
    if (s === 'NOT_STARTED') return 'phase-ns';
    if (s === 'IN_PROGRESS') return 'phase-ip';
    if (s === (prefix === 'ui' ? 'UI_NOT_READY' : prefix === 'ux' ? 'UX_NOT_READY' : 'NOT_APPLICABLE') || s === (prefix === 'be' ? 'DEFERRED' : '') && prefix === 'be') return 'phase-nr';
    if (s === 'UI_CONDITIONALLY_READY' || s === 'UX_CONDITIONALLY_READY') return 'phase-cr';
    if (s === 'UI_APPROVED' || s === 'UX_APPROVED' || s === 'IMPLEMENTED') return 'phase-ap';
    if (s === 'NOT_APPLICABLE') return 'phase-na';
    if (s === 'BLOCKED_BY_UI') return 'phase-bu';
    if (s === 'FROZEN') return 'phase-fr';
    if (s === 'DECISION_PENDING') return 'phase-dp';
    if (s === 'AUTHORIZED') return 'phase-au';
    if (s === 'IN_PROGRESS' || s === 'DEFERRED') return 'phase-ip';
    return 'phase-ns';
  }

  function authorityLabel(a) {
    var labels = {
      'canonical': t('authCanonical'),
      'proposed-number': t('authProposed'),
      'candidate': t('authCandidate'),
      'existing-project': t('authExisting'),
      'reserved': t('authReserved'),
      'number-reconciliation-required': t('authReconciliation'),
    };
    return labels[a] || a;
  }

  function phaseStatusLabel(s) {
    var labels = {
      'NOT_STARTED': t('phaseNotStarted'),
      'IN_PROGRESS': t('phaseInProgress'),
      'UI_NOT_READY': t('phaseNotReady'),
      'UX_NOT_READY': t('phaseNotReady'),
      'UI_CONDITIONALLY_READY': t('phaseConditionallyReady'),
      'UX_CONDITIONALLY_READY': t('phaseConditionallyReady'),
      'BLOCKED_BY_UI': t('phaseBlockedByUi'),
      'FROZEN': t('phaseFrozen'),
      'DECISION_PENDING': t('phaseDecisionPending'),
      'AUTHORIZED': t('phaseAuthorized'),
      'IMPLEMENTED': t('phaseImplemented'),
      'NOT_APPLICABLE': t('phaseNotApplicable'),
      'DEFERRED': t('phaseDeferred'),
      'UI_APPROVED': t('phaseApproved'),
      'UX_APPROVED': t('phaseApproved'),
    };
    return labels[s] || s;
  }

  // ── Dialog ──
  let lastFocused = null;

  function dialogContentHTML(item) {
    const progress = computeProgress(item.milestoneTasks);
    const isProject = item.businessNumber == null;
    const biz = isProject ? t('project') : `B${pad(item.businessNumber)}`;
    const doneTasks = (item.milestoneTasks || []).filter(t => t.done);
    const remainingTasks = (item.milestoneTasks || []).filter(t => !t.done);

    function taskListHTML(tasks, emptyKey) {
      if (!tasks.length) return `<span class="dialog-section-value">${t(emptyKey)}</span>`;
      return `<ul class="dialog-task-list">${tasks.map(t => `<li class="dialog-task-item">${t.label}</li>`).join('')}</ul>`;
    }

    let linksHTML = '';
    if (item.pageUrl) linksHTML += `<a class="dialog-link" href="${item.pageUrl}" target="_blank" rel="noopener noreferrer">${t('openService')}</a>`;
    if (item.repositoryUrl) linksHTML += `<a class="dialog-link" href="${item.repositoryUrl}" target="_blank" rel="noopener noreferrer">${t('repository')}</a>`;
    if (item.workspace && item.workspace !== '확인 필요' && item.workspace !== '—') {
      linksHTML += `<button type="button" class="dialog-link" id="dlg-copy-workspace" data-workspace="${item.workspace}">${t('copyWorkspace')}</button>`;
    }

    return `
      <div class="dialog-biznumber">${biz}</div>
      <div class="dialog-name">${item.name}</div>
      <div class="dialog-korean">${item.koreanName}</div>
      <hr class="dialog-divider">
      <div class="dialog-section">
        <span class="dialog-section-label">${t('purpose')}</span>
        <span class="dialog-section-value">${item.purpose || '—'}</span>
      </div>
      <div class="dialog-section">
        <span class="dialog-section-label">${t('stageLabel')}</span>
        <span class="dialog-section-value"><span class="pd-card-stage pd-card-stage-${item.stage}">${stageLabel(item.stage)}</span> · ${devLabel(item.developmentMode)}</span>
      </div>
      <div class="dialog-section">
        <span class="dialog-section-label">${t('milestone')}</span>
        <span class="dialog-section-value">${item.currentMilestone || t('progressUndefined')} ${progress ? `— ${progress.pct}% (${progress.done}/${progress.total})` : ''}</span>
      </div>
      ${item.progressBasis ? `<div class="dialog-section"><span class="dialog-section-label">${t('progressBasis')}</span><span class="dialog-section-value">${item.progressBasis}</span></div>` : ''}
      <div class="dialog-section">
        <span class="dialog-section-label">${t('currentWork')}</span>
        <span class="dialog-section-value">${item.currentWork || '—'}</span>
      </div>
      <div class="dialog-section">
        <span class="dialog-section-label">${t('nextAction')}</span>
        <span class="dialog-section-value">${item.nextAction || '—'}</span>
      </div>
      <div class="dialog-section">
        <span class="dialog-section-label">${t('completedTasks')}</span>
        ${taskListHTML(doneTasks, 'noCompletedTasks')}
      </div>
      <div class="dialog-section">
        <span class="dialog-section-label">${t('remainingTasks')}</span>
        ${taskListHTML(remainingTasks, 'noRemainingTasks')}
      </div>
      ${item.blockers?.length ? `<div class="dialog-section"><span class="dialog-section-label">${t('blocks')}</span><span class="dialog-section-value">${item.blockers.join(', ')}</span></div>` : ''}
      <div class="dialog-section">
        <span class="dialog-section-label">${t('githubStatus')}</span>
        <span class="dialog-section-value">${t('githubDisconnected')}</span>
      </div>
      <hr class="dialog-divider">
      <div class="dialog-section">
        <span class="dialog-section-label">${t('repository')}</span>
        <span class="dialog-section-value">${item.repositoryLabel || '—'}</span>
      </div>
      <div class="dialog-section">
        <span class="dialog-section-label">${t('workspace')}</span>
        <span class="dialog-section-value">${item.workspace || '—'}</span>
      </div>
      <div class="dialog-section">
        <span class="dialog-section-label">${t('page')}</span>
        <span class="dialog-section-value">${item.pageUrl || t('notDeployed')}</span>
      </div>
      <div class="dialog-section">
        <span class="dialog-section-label">${t('lastVerified')}</span>
        <span class="dialog-section-value">${item.lastVerified || '—'}</span>
      </div>
      <hr class="dialog-divider">
      <div class="dialog-links">${linksHTML}</div>
    `;
  }

  function openProjectDialog(projectId) {
    const item = projects.find(p => p.id === projectId);
    if (!item) return;
    selectedProjectId = projectId;
    lastFocused = document.activeElement;
    const dialog = $('#project-dialog');
    if (!dialog) return;

    const body = $('#dialog-body');
    const title = $('#dialog-title');
    if (!body || !title) return;

    title.textContent = item.name;
    body.innerHTML = dialogContentHTML(item);

    // Add workspace copy handler
    const copyBtn = dialog.querySelector('#dlg-copy-workspace');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        const ws = copyBtn.dataset.workspace;
        if (navigator.clipboard?.writeText) {
          navigator.clipboard.writeText(ws);
        }
      });
    }

    dialog.showModal();
    dialog.querySelector('.dialog-close-btn')?.focus();
    document.body.style.overflow = 'hidden';
  }

  function businessDialogContentHTML(biz) {
    const authCls = 'biz-auth-' + (biz.numberAuthority === 'proposed-number' ? 'proposed' : biz.numberAuthority === 'existing-project' ? 'existing-project' : biz.numberAuthority === 'number-reconciliation-required' ? 'reconciliation' : biz.numberAuthority || 'candidate');
    const uiCls = phaseBadgeClass(biz.uiStatus, 'ui');
    const uxCls = phaseBadgeClass(biz.uxStatus, 'ux');
    const beCls = phaseBadgeClass(biz.backendStatus, 'be');
    return `
      <div class="dialog-biznumber">B${pad(biz.number)}</div>
      <div class="dialog-name">${biz.title}</div>
      <div class="dialog-korean">${biz.koreanTitle}</div>
      <hr class="dialog-divider">
      <div class="dialog-section">
        <span class="dialog-section-label">${t('authorityLabel')}</span>
        <span class="dialog-section-value"><span class="status-badge ${authCls}">${authorityLabel(biz.numberAuthority)}</span></span>
      </div>
      <div class="dialog-section">
        <span class="dialog-section-label">${t('phaseLabel')}</span>
        <span class="dialog-section-value">
          <span class="biz-phase-badge ${uiCls}">UI: ${phaseStatusLabel(biz.uiStatus)}</span>
          <span class="biz-phase-badge ${uxCls}">UX: ${phaseStatusLabel(biz.uxStatus)}</span>
          <span class="biz-phase-badge ${beCls}">BE: ${phaseStatusLabel(biz.backendStatus)}</span>
        </span>
      </div>
      <div class="dialog-section">
        <span class="dialog-section-label">${t('lifecycleLabel')}</span>
        <span class="dialog-section-value">${biz.lifecycle || '—'}</span>
      </div>
      <div class="dialog-section">
        <span class="dialog-section-label">${t('priorityLabel')}</span>
        <span class="dialog-section-value">${biz.priority || '—'}</span>
      </div>
      <hr class="dialog-divider">
      <div class="dialog-links">
        ${biz.surfaceUrl ? `<a class="dialog-link" href="${biz.surfaceUrl}" target="_blank" rel="noopener noreferrer">${t('openService')}</a>` : ''}
      </div>
      <div data-verdict-block></div>
    `;
  }

  function openBusinessDialog(biz) {
    lastFocused = document.activeElement;
    selectedBusinessNumber = biz.number;
    const dialog = $('#business-dialog');
    if (!dialog) return;
    const body = $('#biz-dialog-body');
    const title = $('#biz-dialog-title');
    if (!body || !title) return;

    title.textContent = biz.title;
    body.innerHTML = businessDialogContentHTML(biz);

    dialog.showModal();
    dialog.querySelector('#biz-dialog-close-btn')?.focus();
    document.body.style.overflow = 'hidden';
  }

  function closeDialog(dialogId) {
    const dialog = $(`#${dialogId || 'project-dialog'}`);
    if (!dialog || !dialog.open) return;
    dialog.close();
    document.body.style.overflow = '';
    // Restore focus
    if (lastFocused && lastFocused.focus) {
      setTimeout(() => lastFocused.focus(), 50);
    }
  }

  // ── Mobile drawer ──
  function openDrawer() {
    const sidebar = $('#sidebar');
    const overlay = $('#drawer-overlay');
    if (sidebar) sidebar.classList.add('is-open');
    if (overlay) overlay.classList.add('is-visible');
  }

  function closeDrawer() {
    const sidebar = $('#sidebar');
    const overlay = $('#drawer-overlay');
    if (sidebar) sidebar.classList.remove('is-open');
    if (overlay) overlay.classList.remove('is-visible');
  }

  // ── Init ──
  function init() {
    // Theme
    initTheme();

    // Language
    setLanguage('ko');

    // View navigation
    $$('.view-nav-item').forEach(btn => {
      btn.addEventListener('click', () => switchView(btn.dataset.view));
    });

    // Theme toggle
    const themeBtn = $('#theme-toggle');
    if (themeBtn) themeBtn.addEventListener('click', toggleTheme);

    // Language toggle
    $$('.lang-btn').forEach(btn => {
      btn.addEventListener('click', () => setLanguage(btn.dataset.lang));
    });

    // Dialogs
    function setupDialog(dialogId, closeBtnId) {
      const dialog = $(`#${dialogId}`);
      if (!dialog) return;
      dialog.addEventListener('close', () => {
        document.body.style.overflow = '';
        if (lastFocused && lastFocused.focus) {
          setTimeout(() => lastFocused.focus(), 50);
        }
      });
      dialog.addEventListener('click', (e) => {
        if (e.target === dialog) closeDialog(dialogId);
      });
      const closeBtn = $(`#${closeBtnId}`);
      if (closeBtn) closeBtn.addEventListener('click', () => closeDialog(dialogId));
    }
    setupDialog('project-dialog', 'dialog-close-btn');
    setupDialog('business-dialog', 'biz-dialog-close-btn');
    // Reset selected business on dialog close
    const bizDialog = $('#business-dialog');
    if (bizDialog) {
      bizDialog.addEventListener('close', () => {
        selectedBusinessNumber = null;
      });
    }

    // Search / filter events
    const searchInput = $('#sf-search-input');
    const filterStage = $('#sf-stage-filter');
    const filterDevMode = $('#sf-devmode-filter');
    const filterSort = $('#sf-sort-filter');
    const resetBtn = $('#sf-reset-filter');

    [searchInput, filterStage, filterDevMode, filterSort].forEach(el => {
      if (!el) return;
      el.addEventListener(el.type === 'search' ? 'input' : 'change', () => {
        if (activeView === 'search') renderSearchView();
        updateCounts();
      });
    });

    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        if (searchInput) searchInput.value = '';
        if (filterStage) filterStage.value = 'all';
        if (filterDevMode) filterDevMode.value = 'all';
        if (filterSort) filterSort.value = 'default';
        if (activeView === 'search') renderSearchView();
        updateCounts();
      });
    }

    // Business filters
    const bizSearch = $('#biz-search-input');
    const bizAuth = $('#biz-auth-filter');
    const bizUi = $('#biz-ui-filter');
    const bizUx = $('#biz-ux-filter');
    const bizBe = $('#biz-be-filter');
    const bizSort = $('#biz-sort');
    [bizSearch, bizAuth, bizUi, bizUx, bizBe, bizSort].forEach(el => {
      if (!el) return;
      el.addEventListener(el.type === 'search' ? 'input' : 'change', () => {
        if (activeView === 'business') renderBusinessIndex();
      });
    });

    // Mobile drawer
    const menuToggle = $('#menu-toggle');
    if (menuToggle) menuToggle.addEventListener('click', openDrawer);
    const drawerClose = $('#drawer-close');
    if (drawerClose) drawerClose.addEventListener('click', closeDrawer);
    const drawerOverlay = $('#drawer-overlay');
    if (drawerOverlay) drawerOverlay.addEventListener('click', closeDrawer);

    // Initial render
    switchView('projects');
  }

  document.addEventListener('DOMContentLoaded', init);
  if (document.readyState !== 'loading') init();
})();
