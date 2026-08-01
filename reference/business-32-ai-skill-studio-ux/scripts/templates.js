/* Business 32 · AI Skill Studio — Phase 2 deterministic synthetic view templates.
 * Pure render functions returning HTML strings. All data is the synthetic fixture.
 * Roles: operator(업무 실행자) / reviewer(합성 운영 책임자 · 사람 검토자).
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.B32Templates = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const V = 'b32-ux-static-v1';

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function img(name, alt) {
    return '<img src="assets/images/' + esc(name) + '?v=' + V + '" alt="' + esc(alt) + '">';
  }

  function roleLabel(machine) {
    const role = machine.context.activeRole;
    const name = role === 'reviewer' ? '합성 운영 책임자 · 사람 검토자' : '업무 실행자';
    return '<span class="role-label" data-focus-key="role-banner" tabindex="-1">역할 · ' + esc(name) + '</span>';
  }

  function metaRow(machine) {
    const section = sectionFor(machine.state);
    return (
      '<div class="view-meta">' +
      '<span class="ia-label">' + esc(section) + '</span>' +
      '<span class="state-label">' + esc(machine.state) + '</span>' +
      '<span class="phase-label">PHASE 2 · DETERMINISTIC SYNTHETIC UX</span>' +
      roleLabel(machine) +
      '</div>'
    );
  }

  function actionsBar(actions) {
    if (!actions || actions.length === 0) return '';
    const buttons = actions
      .map(function (a, index) {
        const hint = a.hint ? ' <small>' + esc(a.hint) + '</small>' : '';
        return (
          '<button type="button" class="bench-btn" data-action="' + esc(a.name) + '"' +
          ' data-focus-key="primary">' +
          esc(a.label) + hint +
          '</button>'
        );
      })
      .join('');
    return '<div class="bench-actions" role="group" aria-label="다음 행동">' + buttons + '</div>';
  }

  function stepLedger(machine, currentId) {
    const steps = machine.fixture.steps;
    const li = steps
      .map(function (step) {
        const isCurrent = step.id === currentId;
        const isDone = machine.context.evidence.verified.some(function (v) {
          return v.stepId === step.id;
        });
        const cls = isDone ? 'done' : isCurrent ? 'current' : '';
        const badge = isDone ? '완료' : isCurrent ? '진행' : '대기';
        return (
          '<li class="' + cls + '">' +
          '<span class="step-no">0' + step.number + '</span>' +
          '<div>' +
          '<b>' + esc(step.title) + '</b>' +
          '<small>' + esc(step.kind) + ' · ' + esc(step.detail) + '</small>' +
          '<span class="step-badge">' + badge + '</span>' +
          '</div>' +
          '</li>'
        );
      })
      .join('');
    return '<ol class="step-ledger">' + li + '</ol>';
  }

  function evidencePanel(machine) {
    const fx = machine.fixture;
    const quotes = fx.suppliers
      .map(function (s) {
        return '<figure class="quote-card">' + img(s.source, '합성 공급업체 견적 ' + s.id) + '<figcaption>SOURCE EVIDENCE · SYNTHETIC · 견적 ' + s.id + '</figcaption></figure>';
      })
      .join('');
    const missing = machine.context.evidence.missing
      .map(function (m) {
        return '<div class="flag flag-missing"><span>MISSING EVIDENCE</span><p>' + esc(m.text) + '</p></div>';
      })
      .join('');
    const conflicts = machine.context.evidence.conflicts
      .map(function (c) {
        return '<div class="flag flag-conflict"><span>CONFLICTING EVIDENCE</span><p>' + esc(c.text) + '</p></div>';
      })
      .join('');
    const defaults = fx.exceptions
      .filter(function (e) {
        return e.label !== 'MISSING EVIDENCE' || machine.context.evidence.missing.length === 0;
      })
      .map(function (e) {
        return '<div class="flag flag-exception"><span>' + esc(e.label) + '</span><p>' + esc(e.text) + '</p></div>';
      })
      .join('');
    return (
      '<section class="evidence-drawer-content" aria-label="증거 패널">' +
      '<header class="section-head"><div><span>SOURCE EVIDENCE</span><h2 id="evidence-drawer-title" data-focus-key="drawer-heading" tabindex="-1">세 견적을 같은 원장 위에서 비교합니다.</h2></div><p>SYNTHETIC · UNVERIFIED MATERIAL</p></header>' +
      '<button type="button" class="bench-btn ghost" data-action="toggle-evidence" data-focus-key="drawer-close">증거 패널 닫기</button>' +
      '<div class="quote-rack">' + quotes + '</div>' +
      '<div class="evidence-bottom">' + img('comparison-ledger.svg', '합성 비교 원장') +
      '<div class="flag-stack">' + missing + conflicts + defaults + '</div></div>' +
      '</section>'
    );
  }

  function exceptionFlags(machine) {
    const flags = machine.context.exceptions
      .map(function (e) {
        return '<div class="flag"><span>' + esc(e.label) + '</span><p>' + esc(e.text) + '</p></div>';
      })
      .join('');
    return '<div class="exception-strip" aria-label="예외 목록"><h3>EXCEPTIONS</h3>' + flags + '</div>';
  }

  function sectionFor(state) {
    const map = {
      initial: '업무 브리프',
      empty: '업무 브리프',
      'task-selected': '업무 브리프',
      'input-incomplete': '입력자료',
      ready: '입력자료',
      running: '실행 단계',
      'step-complete': '실행 단계',
      'missing-evidence': '증거',
      'conflicting-evidence': '증거',
      stopped: '실행 단계',
      resume: '실행 단계',
      cancelled: '업무 브리프',
      'draft-result': '결과 초안',
      'review-requested': '사람 검토',
      'correction-required': '사람 검토',
      revised: '사람 검토',
      'approval-pending': '승인',
      approved: '승인',
      'skill-saved': '스킬 카드',
      completed: '버전 이력',
      loading: '업무 브리프',
      'validation-error': '입력자료',
      'system-error': '실행 단계',
      retry: '실행 단계'
    };
    return map[state] || '업무 브리프';
  }

  function renderLoading() {
    return (
      '<section class="view loading-view">' + metaRow({ state: 'loading', context: { activeRole: 'operator' } }) +
      '<div class="skeleton" data-focus-key="view-heading" tabindex="-1"><span>업무 실습대 불러오는 중</span><div class="skeleton-bar" role="progressbar" aria-label="불러오는 중"></div></div>' +
      '</section>'
    );
  }

  function renderBench(machine) {
    const fx = machine.fixture;
    const empty = machine.state === 'empty';
    let body;
    if (empty) {
      body =
        '<div class="empty-panel"><span>EMPTY</span><h2 data-focus-key="view-heading" tabindex="-1">업무대가 비어 있습니다.</h2>' +
        '<p>실행할 합성 업무가 아직 배치되지 않았습니다.</p></div>' +
        actionsBar([{ name: 'load-tasks', label: '합성 업무 불러오기' }]);
    } else {
      const task = fx.task;
      body =
        '<div class="task-card">' +
        '<span class="task-id">' + esc(task.id) + ' · SYNTHETIC WORK TASK</span>' +
        '<h2 data-focus-key="view-heading" tabindex="-1">' + esc(task.title) + '</h2>' +
        '<p>검토자: ' + esc(task.reviewer.role) + ' · 조직: ' + esc(fx.organization.name) + ' (fictional)</p>' +
        '<ul>' +
        task.scope.map(function (s) {
          return '<li>' + esc(s) + '</li>';
        }).join('') +
        '</ul>' +
        '</div>' +
        actionsBar([{ name: 'select-task', label: '업무 시작', hint: 'Enter · Space' }]);
    }
    return (
      '<section class="view bench-view">' + metaRow(machine) +
      '<div class="bench-hero"><div>' +
      '<span class="kicker">BUSINESS 32 · OPERATIONAL TRAINING BENCH</span>' +
      '<h1 data-focus-key="view-heading" tabindex="-1">AI 업무 실습실</h1>' +
      '<p>한 번의 업무를 증거와 검토를 거쳐 재사용 가능한 조직 기술로 보존합니다.</p>' +
      '</div>' + img('training-bench-cover.svg', '업무 실습대 위에 놓인 합성 작업지와 검증 도장 일러스트') + '</div>' +
      body +
      '<div class="bench-note"><span>HUMAN ACTION</span><p>최종 추천과 예외 수용 여부는 사람이 확인합니다. AI가 대신 승인하지 않습니다.</p></div>' +
      '</section>'
    );
  }

  function renderBrief(machine) {
    const fx = machine.fixture;
    const task = fx.task;
    return (
      '<section class="view brief-view">' + metaRow(machine) +
      '<header class="section-head"><div><span>REQUIRED INPUT</span><h2 data-focus-key="view-heading" tabindex="-1">먼저 작업의 경계를 고정합니다.</h2></div><p>' + esc(task.id) + '</p></header>' +
      '<div class="brief-grid">' +
      img('task-brief-sheet.svg', '합성 업무 브리프') +
      '<div class="brief-ledger">' +
      '<ol>' +
      task.scope.map(function (s) {
        return '<li><b>범위</b><small>' + esc(s) + '</small></li>';
      }).join('') +
      task.prohibited.map(function (p) {
        return '<li><b>금지</b><small>' + esc(p) + '</small></li>';
      }).join('') +
      '</ol>' +
      '<div class="human-box"><span>HUMAN ACTION</span><p>최종 추천과 예외 수용 여부는 사람이 확인합니다.</p></div>' +
      '</div></div>' +
      actionsBar([
        { name: 'check-inputs', label: '필수 입력자료 확인', hint: '다음: 입력 확인' },
        { name: 'list-tasks', label: '업무 변경' }
      ]) +
      '</section>'
    );
  }

  function renderInputs(machine) {
    const fx = machine.fixture;
    const complete = machine.state === 'ready';
    const inputs = fx.task.requiredInputs
      .map(function (input) {
        const confirmed = machine.context.inputs.some(function (i) {
          return i.id === input.id && i.confirmed;
        });
        return (
          '<li class="' + (confirmed ? 'confirmed' : 'pending') + '">' +
          '<span class="input-state">' + (confirmed ? '확인됨' : '미확인') + '</span>' +
          '<b>' + esc(input.label) + '</b>' +
          (confirmed ? '' : '<button type="button" class="bench-btn small" data-action="supplement" data-input-id="' + esc(input.id) + '" data-focus-key="primary">확인으로 보완</button>') +
          '</li>'
        );
      })
      .join('');
    return (
      '<section class="view inputs-view">' + metaRow(machine) +
      '<header class="section-head"><div><span>REQUIRED INPUT</span><h2 data-focus-key="view-heading" tabindex="-1">' + (complete ? '입력자료가 모두 확인되었습니다.' : '필수 입력자료를 확인합니다.') + '</h2></div><p>' + (complete ? 'READY' : 'INPUT INCOMPLETE') + '</p></header>' +
      '<div class="inputs-panel"><ul class="inputs-list">' + inputs + '</ul></div>' +
      actionsBar(
        complete
          ? [{ name: 'begin-run', label: '단계별 실행 시작', hint: 'Enter · Space' }]
          : [{ name: 'check-inputs', label: '입력자료 다시 확인' }]
      ) +
      '</section>'
    );
  }

  function renderRun(machine) {
    const fx = machine.fixture;
    const state = machine.state;
    const step = machine.context.steps[machine.context.stepIndex];
    const scen = fx.scenarios.standard;
    let extra = '';
    let actions = [];
    if (state === 'running') {
      actions = [{ name: 'complete-step', label: '단계 완료', hint: step.kind === 'HUMAN ACTION' ? '사람 행동' : 'AI 보조 확인' }];
    } else if (state === 'step-complete') {
      actions = [{ name: 'next-step', label: '다음 단계로' }];
    } else if (state === 'missing-evidence') {
      extra =
        '<div class="flag flag-missing"><span>MISSING EVIDENCE</span><p>' + esc(scen.missingEvidence.text) + '</p>' +
        '<div class="missing-control"><b>누락 자료: ' + esc(scen.missingEvidence.field) + '</b>' +
        '<button type="button" class="bench-btn" data-action="request-supplement" data-focus-key="primary">보완 요청 기록</button></div></div>';
      actions = [{ name: 'stop-run', label: '실행 중단' }];
    } else if (state === 'conflicting-evidence') {
      extra =
        '<div class="flag flag-conflict"><span>CONFLICTING EVIDENCE</span><p>' + esc(scen.conflict.text) + '</p>' +
        '<div class="conflict-control"><span>사람 판단</span>' +
        '<button type="button" class="bench-btn" data-action="resolve-conflict" data-decision="C" data-focus-key="primary">견적 C 조건부 판단</button>' +
        '<button type="button" class="bench-btn" data-action="resolve-conflict" data-decision="B">견적 B 우선 검토</button>' +
        '</div></div>';
      actions = [{ name: 'stop-run', label: '실행 중단' }];
    } else if (state === 'stopped') {
      extra = '<div class="flag flag-stop"><span>STOPPED</span><p>' + esc(machine.context.cancelledResult || '실행을 중단했습니다. 진행 상황은 유지됩니다.') + '</p></div>';
      actions = [
        { name: 'resume-run', label: '재개' },
        { name: 'cancel', label: '취소' }
      ];
    } else if (state === 'resume') {
      extra = '<div class="flag flag-stop"><span>RESUME</span><p>중단 지점에서 이어집니다. 진행 기록은 유지됩니다.</p></div>';
      actions = [{ name: 'resume-confirm', label: '재개 확인' }];
    }
    return (
      '<section class="view run-view">' + metaRow(machine) +
      '<header class="section-head"><div><span>' + (state === 'running' ? 'AI-ASSISTED STEP · HUMAN ACTION' : 'NO LIVE EXECUTION') + '</span><h2 data-focus-key="view-heading" tabindex="-1">Guided Run · 보이는 순서와 멈춤 조건</h2></div><p>SYNTHETIC WORK TASK</p></header>' +
      '<div class="run-layout">' +
      stepLedger(machine, state === 'running' || state === 'step-complete' || state === 'missing-evidence' || state === 'conflicting-evidence' ? step.id : null) +
      '<aside class="stop-board">' +
      '<h3>STOP CONDITIONS</h3>' +
      '<div><span>MISSING EVIDENCE</span><p>보증기간 또는 반품 조건이 없으면 추천 확정 금지</p></div>' +
      '<div><span>EXCEPTION</span><p>긴급 납기 요구가 생기면 비교 규칙 재검토</p></div>' +
      '</aside>' +
      '</div>' +
      extra +
      '<div class="run-actions-row">' +
      actionsBar(actions) +
      '<button type="button" class="bench-btn ghost" data-action="toggle-evidence" data-focus-key="primary" aria-controls="evidence-drawer" aria-expanded="false">증거 열기</button>' +
      '</div>' +
      exceptionFlags(machine) +
      '</section>'
    );
  }

  function renderDraft(machine) {
    const fx = machine.fixture;
    const d = fx.draft.initial;
    const role = machine.context.activeRole;
    const isReviewer = role === 'reviewer';
    const actions = isReviewer
      ? [{ name: 'handoff-to-operator', label: '실행자에게 반환' }]
      : [
          { name: 'request-review', label: '사람 검토 요청', hint: '합성 운영 책임자' },
          { name: 'handoff-to-reviewer', label: '검토자에게 인계' }
        ];
    return (
      '<section class="view draft-view">' + metaRow(machine) +
      '<header class="section-head"><div><span>DRAFT RESULT</span><h2 data-focus-key="view-heading" tabindex="-1">추천 메모 초안을 확인합니다.</h2></div><p>NOT YET APPROVED</p></header>' +
      '<div class="draft-paper">' +
      '<h3>' + esc(d.title) + '</h3>' +
      '<p class="draft-text">초안: "' + esc(machine.context.draft.text) + '"</p>' +
      '<p class="draft-note">근거: ' + esc(machine.context.draft.note) + '</p>' +
      '<p class="draft-disclaimer">이 초안은 DRAFT RESULT입니다. 확정이 아니며 실제 구매 추천이 아닙니다. 사람 검토와 승인이 필요합니다.</p>' +
      '</div>' +
      exceptionFlags(machine) +
      actionsBar(actions) +
      '</section>'
    );
  }

  function renderReview(machine) {
    const fx = machine.fixture;
    const d = fx.draft.initial;
    const state = machine.state;
    const role = machine.context.activeRole;
    const isReviewer = role === 'reviewer';
    let status;
    let actions;
    if (state === 'review-requested') {
      status =
        '<div class="flag flag-stop"><span>NOT YET APPROVED</span><p>검토를 기다리는 중입니다. 합성 운영 책임자가 판단합니다.</p></div>';
      if (isReviewer) {
        actions = [
          { name: 'approve-review', label: '검토 승인', hint: '승인 의사만 밝힘' },
          { name: 'reject-review', label: '수정 요청', hint: 'REVIEW CORRECTION' }
        ];
      } else {
        actions = [{ name: 'handoff-to-reviewer', label: '검토자에게 인계' }];
      }
    } else if (state === 'correction-required') {
      status =
        '<div class="flag flag-conflict"><span>REVIEW CORRECTION</span><p>' + esc(machine.context.draft.note) + '</p></div>' +
        '<div class="flag flag-conflict"><span>REJECTED STEP</span><p>"' + esc(d.rejected) + '" — ' + esc(d.rejectedReason) + '</p></div>';
      actions = isReviewer
        ? [{ name: 'handoff-to-operator', label: '실행자에게 반환' }]
        : [{ name: 'apply-correction', label: '수정 사항 반영' }];
    } else {
      status =
        '<div class="flag flag-stop"><span>REVISED</span><p>수정 사항이 반영되었습니다. 절차를 재실행하거나 다시 검토를 요청합니다.</p></div>';
      actions = isReviewer
        ? [{ name: 'handoff-to-operator', label: '실행자에게 반환' }]
        : [
            { name: 're-run', label: '수정된 절차 재실행' },
            { name: 'request-review', label: '다시 검토 요청' },
            { name: 'handoff-to-reviewer', label: '검토자에게 인계' }
          ];
    }
    return (
      '<section class="view review-view">' + metaRow(machine) +
      '<header class="section-head"><div><span>' + (state === 'review-requested' ? 'NOT YET APPROVED' : 'REVIEW CORRECTION') + '</span><h2 data-focus-key="view-heading" tabindex="-1">약한 추천을 지우고 근거가 있는 판단으로 수정합니다.</h2></div><p>fictional operations lead</p></header>' +
      '<div class="review-grid">' +
      img('review-correction.svg', '합성 검토 수정 기록') +
      '<div class="review-notes">' +
      '<article><span>REJECTED STEP</span><h3>"' + esc(d.rejected) + '"</h3><p>' + esc(d.rejectedReason) + '</p></article>' +
      '<article class="corrected"><span>REVIEW CORRECTION</span><h3>"' + esc(d.corrected) + '"</h3><p>' + esc(d.correctedReason) + '</p></article>' +
      '<article class="exception"><span>EXCEPTION</span><h3>긴급 납기 시 규칙 재검토</h3><p>예외는 승인 후에도 기술 카드에 유지됩니다.</p></article>' +
      '</div></div>' +
      status +
      actionsBar(actions) +
      '</section>'
    );
  }

  function renderApproval(machine) {
    const state = machine.state;
    const approved = state === 'approved';
    const role = machine.context.activeRole;
    const isReviewer = role === 'reviewer';
    let actions;
    if (approved) {
      actions = isReviewer
        ? [{ name: 'handoff-to-operator', label: '실행자에게 반환' }]
        : [{ name: 'save-skill', label: '스킬 카드 저장', hint: 'VERIFIED ORGANIZATIONAL AI SKILL' }];
    } else {
      actions = isReviewer
        ? [{ name: 'approve', label: '사람 최종 승인', hint: 'HUMAN ACTION · 검토자' }]
        : [
            { name: 'handoff-to-reviewer', label: '검토자에게 인계' },
            { name: 'save-skill', label: '스킬 저장 시도(차단 확인)' }
          ];
    }
    return (
      '<section class="view approval-view">' + metaRow(machine) +
      '<header class="section-head"><div><span>' + (approved ? 'HUMAN-APPROVED' : 'NOT YET APPROVED') + '</span><h2 data-focus-key="view-heading" tabindex="-1">' + (approved ? '사람이 최종 승인했습니다.' : '사람 최종 승인을 확인합니다.') + '</h2></div><p>fictional operations lead</p></header>' +
      '<div class="approval-panel">' +
      '<div class="flag ' + (approved ? 'flag-ok' : 'flag-stop') + '"><span>' + (approved ? 'HUMAN-APPROVED' : 'NOT YET APPROVED') + '</span>' +
      '<p>' + (approved ? '검토자가 추천과 예외 수용을 최종 확인했습니다.' : 'AI나 실행자는 승인할 수 없습니다. 검토자 역할의 사람만 승인할 수 있습니다.') + '</p></div>' +
      (approved
        ? ''
        : '<div class="approval-seal">NOT YET APPROVED</div>') +
      '</div>' +
      exceptionFlags(machine) +
      actionsBar(actions) +
      '</section>'
    );
  }

  function renderSkill(machine) {
    const fx = machine.fixture;
    const skill = machine.context.skill;
    const completed = machine.state === 'completed';
    const exceptions = skill
      ? skill.exceptions.map(function (e) {
          return '<li><span>' + esc(e.label) + '</span>' + esc(e.text) + '</li>';
        }).join('')
      : '';
    const versions = machine.context.versions.length
      ? machine.context.versions.map(function (v) {
          return '<li><b>' + esc(v.version) + '</b><span>' + esc(v.savedAt) + ' · ' + esc(v.owner) + '</span></li>';
        }).join('')
      : '<li class="empty-version">저장된 버전이 없습니다.</li>';
    return (
      '<section class="view skill-view">' + metaRow(machine) +
      '<header class="section-head"><div><span>TASK-TO-VERIFIED-SKILL</span><h2 data-focus-key="view-heading" tabindex="-1">업무에서 검증된 기술로</h2></div><p>' + (completed ? '버전·담당자·다음 검토일 확인' : 'VERIFIED ORGANIZATIONAL AI SKILL') + '</p></header>' +
      (skill
        ? '<div class="skill-output">' +
          img('skill-card.svg', '합성 조직 기술 카드') +
          '<div class="verified-authority">' +
          '<span class="verified-authority-label">' + esc(skill.authority) + '</span>' +
          '<strong>' + esc(skill.name) + '</strong>' +
          '<dl><div><dt>VERSION</dt><dd>' + esc(skill.version) + '</dd></div>' +
          '<div><dt>OWNER</dt><dd>' + esc(skill.owner) + '</dd></div>' +
          '<div><dt>REVIEW</dt><dd>' + esc(skill.reviewDate) + '</dd></div>' +
          '<div><dt>NEXT REVIEW</dt><dd>' + esc(skill.nextReview) + '</dd></div></dl>' +
          '</div></div>' +
          '<div class="skill-exceptions"><h3>RETAINED EXCEPTIONS</h3><ul>' + exceptions + '</ul></div>'
        : '<div class="empty-panel"><span>EMPTY</span><h2>아직 저장된 스킬이 없습니다.</h2></div>') +
      '<div class="version-history"><h3>VERSION HISTORY · 버전 이력</h3><ul>' + versions + '</ul></div>' +
      actionsBar(
        completed
          ? [{ name: 'list-tasks', label: '새 업무 시작' }]
          : [{ name: 'complete', label: '버전·담당자·다음 검토일 확인' }]
      ) +
      '</section>'
    );
  }

  function renderError(machine) {
    const state = machine.state;
    const fb = machine.feedback || {};
    let panel;
    if (state === 'system-error') {
      panel =
        '<div class="flag flag-conflict" data-focus-key="error-summary" tabindex="-1"><span>SYSTEM-ERROR</span><p>' + esc(fb.failure || '오류가 발생했습니다.') + '</p>' +
        '<p class="error-retry">재시도 방법: ' + esc(fb.retry || '재시도를 누릅니다.') + '</p></div>';
    } else if (state === 'retry') {
      panel =
        '<div class="flag flag-stop" data-focus-key="error-summary" tabindex="-1"><span>RETRY</span><p>' + esc(fb.completed || '재시도를 준비했습니다.') + '</p></div>';
    } else if (state === 'validation-error') {
      panel =
        '<div class="flag flag-conflict" data-focus-key="error-summary" tabindex="-1"><span>VALIDATION-ERROR</span><p>' + esc(fb.failure || '입력이 유효하지 않습니다.') + '</p>' +
        '<p class="error-retry">재시도 방법: ' + esc(fb.retry || '입력을 고친 뒤 다시 제출합니다.') + '</p></div>';
    } else {
      panel =
        '<div class="flag flag-stop" data-focus-key="error-summary" tabindex="-1"><span>CANCELLED</span><p>' + esc(fb.completed || '실행을 취소했습니다.') + '</p>' +
        '<p class="error-retry">취소 결과: ' + esc(fb.cancel || '진행 기록은 유지됩니다.') + '</p></div>';
    }
    let actions =
      state === 'cancelled'
        ? [
            { name: 'select-task', label: '업무 다시 선택' },
            { name: 'list-tasks', label: '업무 실습대로' }
          ]
        : [{ name: state === 'retry' ? 'retry-confirm' : 'retry', label: '재시도' }];
    if (state === 'validation-error') actions = [{ name: 'ack', label: '오류 확인 후 복귀' }];
    return (
      '<section class="view error-view">' + metaRow(machine) +
      '<header class="section-head"><div><span>' + esc(state.toUpperCase()) + '</span><h2 data-focus-key="view-heading" tabindex="-1">상태 복구</h2></div><p>DETERMINISTIC · SYNTHETIC</p></header>' +
      panel +
      actionsBar(actions) +
      '</section>'
    );
  }

  function renderEvidenceDrawer(machine) {
    return evidencePanel(machine);
  }

  function render(machine) {
    const state = machine.state;
    const map = {
      loading: renderLoading,
      initial: renderBench,
      empty: renderBench,
      'task-selected': renderBrief,
      'input-incomplete': renderInputs,
      ready: renderInputs,
      running: renderRun,
      'step-complete': renderRun,
      'missing-evidence': renderRun,
      'conflicting-evidence': renderRun,
      stopped: renderRun,
      resume: renderRun,
      cancelled: renderError,
      'draft-result': renderDraft,
      'review-requested': renderReview,
      'correction-required': renderReview,
      revised: renderReview,
      'approval-pending': renderApproval,
      approved: renderApproval,
      'skill-saved': renderSkill,
      completed: renderSkill,
      'validation-error': renderError,
      'system-error': renderError,
      retry: renderError
    };
    const renderer = map[state] || renderLoading;
    return renderer(machine);
  }

  return {
    render: render,
    renderEvidenceDrawer: renderEvidenceDrawer,
    esc: esc,
    sectionFor: sectionFor,
    roleLabel: roleLabel
  };
});
