/* Business 32 · AI Skill Studio — Phase 2 browser app.
 * Browser-only. Wires the deterministic machine to the DOM with keyboard,
 * role handoff, and deterministic focus restoration. Browser-memory state only.
 */
(function (global) {
  'use strict';

  const Machine = global.B32Machine;
  const Templates = global.B32Templates;
  const Nav = global.B32Nav;
  const Fixture = global.B32Fixture;

  if (!Machine || !Templates || !Nav || !Fixture) {
    throw new Error('B32 app: missing modules');
  }

  const viewEl = document.querySelector('#app-view');
  const feedbackEl = document.querySelector('#feedback-region');
  const stateChipEl = document.querySelector('#state-chip');
  const trustEl = document.querySelector('#trust-label');
  const drawerEl = document.querySelector('#evidence-drawer');
  const memoryNoteEl = document.querySelector('#memory-note');

  const ERROR_STATES = ['validation-error', 'system-error', 'retry', 'cancelled'];

  const store = {
    evidenceOpen: false,
    memory: {
      saved: false,
      note: '브라우저 메모리 상태 · 저장되지 않음 · 외부 런타임 요청 0'
    }
  };

  const focus = {
    lastKey: null,
    lastTarget: null
  };

  let machine = null;
  let focusables = [];

  function announce(text, assertive) {
    if (!feedbackEl) return;
    feedbackEl.setAttribute('aria-live', assertive ? 'assertive' : 'polite');
    feedbackEl.textContent = text || '';
  }

  function renderFeedback(feedback) {
    if (!feedback) {
      announce('');
      return;
    }
    const parts = [];
    if (feedback.inProgress) parts.push('진행 중: ' + feedback.inProgress);
    if (feedback.completed) parts.push('완료: ' + feedback.completed);
    if (feedback.notSaved) parts.push('저장 안 됨: ' + feedback.notSaved);
    if (feedback.reviewReason) parts.push('검토 필요: ' + feedback.reviewReason);
    if (feedback.failure) parts.push('실패: ' + feedback.failure);
    if (feedback.retry) parts.push('재시도: ' + feedback.retry);
    if (feedback.cancel) parts.push('취소: ' + feedback.cancel);
    if (feedback.next) parts.push('다음 행동: ' + feedback.next);
    const assertive = feedback.failure || feedback.retry ? true : false;
    announce(parts.join(' · '), assertive);
  }

  function updateTrustLabels(state) {
    if (!stateChipEl || !trustEl) return;
    stateChipEl.textContent = 'STATE · ' + state;
    const labels = Machine.HERO_LABELS;
    trustEl.textContent = 'TRUST · ' + labels.join(' / ');
  }

  function updateMemoryNote() {
    if (!memoryNoteEl) return;
    store.memory.saved = machine.state === 'skill-saved' || machine.state === 'completed';
    memoryNoteEl.textContent = store.memory.saved
      ? '스킬 카드 저장됨(브라우저 메모리) · 영구 저장 없음'
      : store.memory.note;
  }

  function collectFocusables() {
    const viewButtons = Array.prototype.slice.call(
      viewEl.querySelectorAll('button[data-action], button[data-scenario]')
    );
    const drawerButtons = drawerEl
      ? Array.prototype.slice.call(drawerEl.querySelectorAll('button[data-action]'))
      : [];
    focusables = viewButtons.concat(drawerButtons);
    focusables.forEach(function (el, index) {
      el.tabIndex = index === 0 ? 0 : -1;
    });
  }

  function syncDrawerAria() {
    const opener = viewEl ? viewEl.querySelector('[data-action="toggle-evidence"]') : null;
    if (opener) opener.setAttribute('aria-expanded', String(store.evidenceOpen));
  }

  function openDrawer() {
    store.evidenceOpen = true;
    if (drawerEl) drawerEl.hidden = false;
    renderDrawer();
    collectFocusables();
    syncDrawerAria();
    announce('증거 패널이 열렸습니다. SOURCE EVIDENCE');
    applyFocus(machine, { drawerOpened: true });
  }

  function closeDrawer() {
    if (!store.evidenceOpen) return;
    store.evidenceOpen = false;
    if (drawerEl) drawerEl.hidden = true;
    renderDrawer();
    collectFocusables();
    syncDrawerAria();
    applyFocus(machine, { drawerClosed: true });
  }

  function focusElement(el) {
    if (el && typeof el.focus === 'function') {
      el.focus();
      focus.lastKey = el.dataset.focusKey || null;
      focus.lastTarget = el;
      return true;
    }
    return false;
  }

  function applyFocus(machine, meta) {
    const view = viewEl;
    let target = null;
    if (meta.validationError) {
      target = view.querySelector('[data-focus-key="error-summary"]');
    } else if (meta.drawerOpened) {
      target = drawerEl.querySelector('[data-focus-key="drawer-heading"]');
    } else if (meta.drawerClosed) {
      target = view.querySelector('[data-action="toggle-evidence"]');
    } else if (meta.roleChanged) {
      target = view.querySelector('[data-focus-key="role-banner"]');
      if (!target) target = view.querySelector('.bench-actions [data-action]');
    } else if (meta.recovery) {
      target = focus.lastKey
        ? view.querySelector('[data-focus-key="' + focus.lastKey + '"]')
        : null;
    }
    if (!target) target = view.querySelector('[data-focus-key="view-heading"]');
    if (!target) target = view.querySelector('[data-action]');
    focusElement(target);
  }

  function renderDrawer() {
    if (drawerEl && store.evidenceOpen && machine) {
      drawerEl.innerHTML = Templates.renderEvidenceDrawer(machine);
    }
  }

  function render(meta) {
    if (!viewEl || !machine) return;
    viewEl.innerHTML = Templates.render(machine);
    renderDrawer();
    collectFocusables();
    updateTrustLabels(machine.state);
    updateMemoryNote();
    renderFeedback(machine.feedback);
    syncDrawerAria();
    applyFocus(machine, meta || {});
  }

  function transition(action, payload) {
    const prevState = machine ? machine.state : null;
    const prevRole = machine ? machine.context.activeRole : null;
    focus.lastKey = document.activeElement && document.activeElement.dataset
      ? document.activeElement.dataset.focusKey || null
      : null;
    try {
      machine = Machine.transition(machine, action, payload || {});
    } catch (error) {
      announce('이동이 차단되었습니다: ' + action + ' (허용되지 않는 전환) · ' + machine.state, true);
      return;
    }
    const nextState = machine.state;
    const nextRole = machine.context.activeRole;
    const meta = {
      validationError: nextState === 'validation-error',
      roleChanged: prevRole !== null && prevRole !== nextRole,
      recovery: ERROR_STATES.indexOf(prevState) !== -1 && ERROR_STATES.indexOf(nextState) === -1
    };
    render(meta);
  }

  function simulateBoot() {
    machine = Machine.createMachine(Fixture, 'standard');
    transition('load-ok');
  }

  function handleActionClick(button) {
    const action = button.dataset.action;
    if (!action) return;
    if (action === 'toggle-evidence') {
      if (store.evidenceOpen) {
        closeDrawer();
      } else {
        openDrawer();
      }
      return;
    }
    if (action === 'load-tasks') {
      transition('load-tasks');
      return;
    }
    const payload = {};
    if (button.dataset.inputId) payload.inputId = button.dataset.inputId;
    if (button.dataset.decision) payload.decision = button.dataset.decision;
    transition(action, payload);
  }

  function handleScenario(button) {
    const scenario = button.dataset.scenario;
    machine = Machine.createMachine(Fixture, scenario);
    render({});
    if (scenario === 'fault') {
      transition('load-error');
    } else {
      transition('load-ok');
    }
    document.querySelectorAll('button[data-scenario]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.scenario === scenario));
    });
  }

  function handleKeydown(event) {
    if (event.key === 'Escape' && store.evidenceOpen) {
      closeDrawer();
      return;
    }
    const index = focusables.indexOf(document.activeElement);
    if (index === -1) return;
    if (event.key === 'Enter' || event.key === ' ') {
      return;
    }
    const next = Nav.nextIndex(focusables.length, index, event.key);
    if (next !== index) {
      event.preventDefault();
      focusables[next].focus();
      focus.lastKey = focusables[next].dataset.focusKey || null;
    }
  }

  function bindEvents() {
    document.addEventListener('click', function (event) {
      const button = event.target.closest ? event.target.closest('button[data-action], button[data-scenario]') : null;
      if (!button) return;
      if (button.dataset.scenario) {
        handleScenario(button);
      } else {
        handleActionClick(button);
      }
    });
    document.addEventListener('keydown', handleKeydown);
    const scenarioButtons = document.querySelectorAll('button[data-scenario]');
    scenarioButtons.forEach(function (button) {
      button.setAttribute('aria-pressed', String(button.dataset.scenario === 'standard'));
    });
  }

  function init() {
    bindEvents();
    simulateBoot();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
