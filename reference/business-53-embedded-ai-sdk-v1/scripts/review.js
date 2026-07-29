(() => {
  const tabs = [...document.querySelectorAll('[data-state-control]')];
  const panels = [...document.querySelectorAll('[data-state]')];
  const replay = document.querySelector('[data-motion-replay]');
  const trace = document.querySelector('[data-embed-trace]');
  const binder = document.querySelector('.integration-contract-binder');
  const status = document.querySelector('[data-motion-status]');

  function selectState(key, focus = false) {
    tabs.forEach((tab) => {
      const selected = tab.dataset.stateControl === key;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus({ preventScroll: true });
    });
    panels.forEach((panel) => {
      const active = panel.dataset.state === key;
      panel.hidden = !active;
      panel.classList.toggle('is-active', active);
    });
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectState(tab.dataset.stateControl));
    tab.addEventListener('keydown', (event) => {
      let next = null;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next !== null) {
        event.preventDefault();
        selectState(tabs[next].dataset.stateControl, true);
      }
    });
  });

  function completeMotion() {
    trace.classList.remove('is-running');
    trace.classList.add('is-complete');
    trace.dataset.motionState = 'complete';
    status.textContent = 'HUMAN-APPROVED EMBEDDED AI INTEGRATION CONTRACT · complete';
  }

  binder?.addEventListener('animationend', (event) => {
    if (event.animationName === 'embedContractComplete') completeMotion();
  });

  replay?.addEventListener('click', () => {
    const focusTarget = document.activeElement;
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    trace.classList.remove('is-running', 'is-complete');
    trace.dataset.motionState = 'idle';
    status.textContent = 'Host-Surface-to-Approved-Embed-Contract · running';
    void trace.offsetWidth;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      completeMotion();
    } else {
      trace.classList.add('is-running');
      trace.dataset.motionState = 'running';
    }
    focusTarget?.focus?.({ preventScroll: true });
    window.scrollTo(scrollX, scrollY);
  });

  selectState('cover');
})();
