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
    document.documentElement.lang = lang === 'en' ? 'en' : 'ko';
    $$('.lang-btn').forEach(b => b.classList.toggle('is-active', b.dataset.lang === lang));
    // Update nav labels
    $$('.nav-label').forEach(el => {
      const label = el.dataset[`label${lang === 'ko' ? 'Ko' : 'En'}`];
      if (label) el.textContent = label;
    });
    // Update misc labels
    const searchLabel = $('.search-label');
    if (searchLabel) searchLabel.textContent = t('search');
    $$('.filter-label').forEach(el => {
      if (el.parentElement?.querySelector('#sf-stage-filter')) el.textContent = t('stage');
      else if (el.parentElement?.querySelector('#sf-devmode-filter')) el.textContent = t('devMode');
      else if (el.parentElement?.querySelector('#sf-sort-filter')) el.textContent = t('sort');
    });
    const searchInput = $('#sf-search-input');
    if (searchInput) searchInput.placeholder = t('search');
    const resetBtn = $('#sf-reset-filter');
    if (resetBtn) resetBtn.textContent = t('reset');
    const prefix = $('#header-prefix');
    if (prefix) {
      prefix.textContent = prefix.dataset[`prefix${lang === 'ko' ? 'Ko' : 'En'}`] || prefix.textContent;
    }
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
    // Business state filter
    const bsF = $('#biz-state-filter');
    if (bsF) {
      bsF.options[0].textContent = t('allStates');
      bsF.options[1].textContent = t('running');
      bsF.options[2].textContent = t('reviewBuild');
      bsF.options[3].textContent = t('planning');
      bsF.options[4].textContent = t('reserved');
    }
    // Business sort
    const bSort = $('#biz-sort');
    if (bSort) {
      bSort.options[0].textContent = t('numberAsc');
      bSort.options[1].textContent = t('numberDesc');
      bSort.options[2].textContent = t('actionPriority');
      bSort.options[3].textContent = t('progressSort');
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
    const count = activeView === 'search'
      ? t('searchCount', { n: projects.length, m: filteredProjects().length })
      : activeView === 'work'
        ? `${t('workInProgress')} ${wipProjects().length}`
        : activeView === 'business'
          ? `${t('bizLabel')} ${businesses.length}`
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
    const state = $('#biz-state-filter')?.value || 'all';
    const sort = $('#biz-sort')?.value || 'number-asc';

    let result = businesses.filter(b => {
      const haystack = `${b.number} ${pad(b.number)} ${b.title} ${b.koreanTitle} ${b.slug}`.toLowerCase();
      return (!query || haystack.includes(query)) && (state === 'all' || b.state === state);
    });

    result = result.slice().sort((a, b) => {
      if (sort === 'number-desc') return b.number - a.number;
      if (sort === 'priority') return (b.priority || 0) - (a.priority || 0) || a.number - b.number;
      if (sort === 'progress') return (b.progress || 0) - (a.progress || 0) || a.number - b.number;
      return a.number - b.number;
    });
    return result;
  }

  function renderBusinessIndex() {
    const list = $('#biz-list');
    if (!list) return;
    const visible = filteredBusinesses();

    list.innerHTML = visible.map(b => {
      const reserved = b.state === 'reserved' ? ' is-reserved' : '';
      const stateCls = `status-${b.state}`;
      return `
        <div class="biz-item${reserved}" data-biz-number="${b.number}" tabindex="0">
          <span class="biz-number">${pad(b.number)}</span>
          <div class="biz-title-group">
            <span class="biz-title">${b.title}</span>
            <span class="biz-korean">${b.koreanTitle}</span>
          </div>
          <span class="biz-state status-badge ${stateCls}">${stateLabel(b.state)}</span>
          <div class="biz-progress">
            <span>${b.progress}%</span>
            <div class="biz-progress-bar"><i style="width:${b.progress}%"></i></div>
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
    const stateCls = `status-${biz.state}`;
    return `
      <div class="dialog-biznumber">B${pad(biz.number)}</div>
      <div class="dialog-name">${biz.title}</div>
      <div class="dialog-korean">${biz.koreanTitle}</div>
      <hr class="dialog-divider">
      <div class="dialog-section">
        <span class="dialog-section-label">${t('statusLabel')}</span>
        <span class="dialog-section-value"><span class="status-badge ${stateCls}">${stateLabel(biz.state)}</span></span>
      </div>
      <div class="dialog-section">
        <span class="dialog-section-label">${t('progressLabel')}</span>
        <span class="dialog-section-value">${biz.progress}%</span>
      </div>
      <div class="dialog-section">
        <span class="dialog-section-label">${t('nextAction')}</span>
        <span class="dialog-section-value">${biz.nextAction || '—'}</span>
      </div>
      <div class="dialog-section">
        <span class="dialog-section-label">${t('lastVerified')}</span>
        <span class="dialog-section-value">${biz.lastVerified || '—'}</span>
      </div>
      <hr class="dialog-divider">
      <div class="dialog-links">
        ${biz.surfaceUrl ? `<a class="dialog-link" href="${biz.surfaceUrl}" target="_blank" rel="noopener noreferrer">${t('openService')}</a>` : ''}
        ${biz.githubUrl ? `<a class="dialog-link" href="${biz.githubUrl}" target="_blank" rel="noopener noreferrer">GitHub</a>` : ''}
      </div>
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
    const bizState = $('#biz-state-filter');
    const bizSort = $('#biz-sort');
    [bizSearch, bizState, bizSort].forEach(el => {
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
