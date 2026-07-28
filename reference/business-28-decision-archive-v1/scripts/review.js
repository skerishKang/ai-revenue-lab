(() => {
  const keys = ['cover', 'index', 'dossier', 'rationale', 'dissent', 'followup', 'mobile'];
  const tabs = [...document.querySelectorAll('[role="tab"][data-state]')];
  const panels = new Map(keys.map((key) => [key, document.querySelector(`[data-state-key="${key}"]`)]));
  const stage = document.querySelector('#review-stage');
  const chain = document.querySelector('#reason-chain');
  const replay = document.querySelector('#replay-reason');
  const seal = document.querySelector('#decision-seal');
  const status = document.querySelector('#motion-status');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');

  function activate(key, focus = false) {
    if (!panels.has(key)) return;
    stage.dataset.currentState = key;
    tabs.forEach((tab) => {
      const selected = tab.dataset.state === key;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    });
    panels.forEach((panel, panelKey) => {
      const active = panelKey === key;
      panel.hidden = !active;
      panel.classList.toggle('is-active', active);
    });
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activate(tab.dataset.state));
    tab.addEventListener('keydown', (event) => {
      const horizontal = ['ArrowRight', 'ArrowLeft', 'Home', 'End'];
      if (!horizontal.includes(event.key)) return;
      event.preventDefault();
      let next = index;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      activate(tabs[next].dataset.state, true);
    });
  });

  function setMotionState(value) {
    chain.dataset.motionState = value;
    chain.classList.toggle('running', value === 'running');
    chain.classList.toggle('complete', value === 'complete');
    status.textContent = `상태: ${value}`;
  }

  function replayReasonChain() {
    activate('rationale');
    setMotionState(reduced.matches ? 'complete' : 'idle');
    if (reduced.matches) return;
    void chain.offsetWidth;
    requestAnimationFrame(() => setMotionState('running'));
  }

  seal.addEventListener('animationend', (event) => {
    if (event.animationName !== 'reasonSeal' || chain.dataset.motionState !== 'running') return;
    setMotionState('complete');
  });

  replay.addEventListener('click', replayReasonChain);
  reduced.addEventListener?.('change', () => setMotionState(reduced.matches ? 'complete' : 'idle'));
  window.__decisionArchiveReview = { activate, replayReasonChain, keys };
  activate('cover');
})();
