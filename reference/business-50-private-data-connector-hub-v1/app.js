(() => {
  'use strict';

  const tabs = Array.from(document.querySelectorAll('[role="tab"][data-state]'));
  const panels = new Map(Array.from(document.querySelectorAll('[role="tabpanel"][data-state-panel]')).map(panel => [panel.dataset.statePanel, panel]));
  const motionBoard = document.getElementById('motion-board');
  const replayButton = document.getElementById('motion-replay');
  const motionStatus = document.getElementById('motion-status');
  const finalMotionNode = motionBoard?.querySelector('[data-motion-final]');
  const reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  let motionStart = 0;
  let motionRunId = 0;

  function activateState(state, options = {}) {
    const targetTab = tabs.find(tab => tab.dataset.state === state);
    const targetPanel = panels.get(state);
    if (!targetTab || !targetPanel) return;

    tabs.forEach(tab => {
      const selected = tab === targetTab;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });

    panels.forEach((panel, panelState) => {
      panel.hidden = panelState !== state;
    });

    document.documentElement.dataset.activeState = state;
    if (options.focus) targetTab.focus({ preventScroll: true });
  }

  function onTabKeydown(event) {
    const currentIndex = tabs.indexOf(event.currentTarget);
    let nextIndex = null;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') nextIndex = (currentIndex + 1) % tabs.length;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = tabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    activateState(tabs[nextIndex].dataset.state, { focus: true });
  }

  tabs.forEach(tab => {
    tab.addEventListener('click', () => activateState(tab.dataset.state));
    tab.addEventListener('keydown', onTabKeydown);
  });

  function finalizeMotion(runId, elapsed, activeElementId, scrollX, scrollY) {
    if (runId !== motionRunId || !motionBoard) return;
    motionBoard.classList.remove('is-running');
    motionBoard.classList.add('is-complete');
    motionBoard.dataset.motionStatus = 'complete';
    motionBoard.dataset.motionElapsedMs = String(Math.round(elapsed));
    motionBoard.dataset.motionRun = String(runId);
    motionStatus.textContent = `모션 완료, ${Math.round(elapsed)}밀리초`;
    if (activeElementId) {
      const previousFocus = document.getElementById(activeElementId);
      if (previousFocus && document.activeElement !== previousFocus) previousFocus.focus({ preventScroll: true });
    }
    window.scrollTo(scrollX, scrollY);
    window.dispatchEvent(new CustomEvent('private-data-motion-complete', { detail: { runId, elapsed } }));
  }

  function replayMotion() {
    if (!motionBoard || !finalMotionNode) return;
    motionRunId += 1;
    const runId = motionRunId;
    const activeElementId = document.activeElement?.id || '';
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;

    motionBoard.classList.remove('is-running', 'is-complete');
    motionBoard.dataset.motionStatus = 'reset';
    motionBoard.dataset.motionElapsedMs = '';
    void motionBoard.offsetWidth;

    if (reducedMotionQuery.matches) {
      finalizeMotion(runId, 0, activeElementId, scrollX, scrollY);
      return;
    }

    motionStart = performance.now();
    motionBoard.dataset.motionStatus = 'running';
    motionBoard.classList.add('is-running');
    motionStatus.textContent = '접근 요청에서 사람 승인 명세로 변환 중';

    const onFinalAnimationEnd = event => {
      if (event.target !== finalMotionNode || event.animationName !== 'motion-reveal') return;
      finalMotionNode.removeEventListener('animationend', onFinalAnimationEnd);
      finalizeMotion(runId, performance.now() - motionStart, activeElementId, scrollX, scrollY);
    };
    finalMotionNode.addEventListener('animationend', onFinalAnimationEnd);
  }

  replayButton?.addEventListener('click', replayMotion);
  reducedMotionQuery.addEventListener?.('change', () => {
    if (reducedMotionQuery.matches && motionBoard?.dataset.motionStatus === 'running') {
      finalizeMotion(motionRunId, 0, document.activeElement?.id || '', window.scrollX, window.scrollY);
    }
  });

  activateState('cover');
  requestAnimationFrame(replayMotion);
})();
