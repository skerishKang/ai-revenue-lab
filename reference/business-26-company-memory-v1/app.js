(() => {
  const VERSION = 'company-memory-20260728-1';
  const tabs = [...document.querySelectorAll('[data-state-target]')];
  const states = [...document.querySelectorAll('[data-state]')];
  const stage = document.querySelector('#visual-stage');
  const reconstruction = document.querySelector('[data-reconstruction]');
  const replayButton = document.querySelector('[data-motion-replay]');
  const stateNames = new Set(states.map((state) => state.dataset.state));

  function completeReconstruction() {
    if (!reconstruction) return;
    reconstruction.classList.remove('is-running');
    reconstruction.classList.add('is-complete');
    reconstruction.dataset.motionState = 'complete';
  }

  function replayReconstruction() {
    if (!reconstruction) return;
    reconstruction.classList.remove('is-running', 'is-complete');
    reconstruction.dataset.motionState = 'idle';
    void reconstruction.offsetWidth;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      completeReconstruction();
      return;
    }
    reconstruction.dataset.motionState = 'running';
    reconstruction.classList.add('is-running');
  }

  function setState(name, { focus = false, updateUrl = true } = {}) {
    const next = stateNames.has(name) ? name : 'cover';
    states.forEach((state) => {
      const active = state.dataset.state === next;
      state.hidden = !active;
      state.classList.toggle('is-active', active);
    });
    tabs.forEach((tab) => {
      const active = tab.dataset.stateTarget === next;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    if (next === 'reconstruction') replayReconstruction();
    if (focus) stage.focus({ preventScroll: true });
    if (updateUrl) history.replaceState(null, '', `?state=${next}`);
    document.documentElement.dataset.reviewState = next;
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => setState(tab.dataset.stateTarget, { focus: true }));
    tab.addEventListener('keydown', (event) => {
      let nextIndex = index;
      if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === 'Home') nextIndex = 0;
      else if (event.key === 'End') nextIndex = tabs.length - 1;
      else return;
      event.preventDefault();
      tabs[nextIndex].focus();
      setState(tabs[nextIndex].dataset.stateTarget);
    });
  });

  replayButton?.addEventListener('click', replayReconstruction);
  reconstruction?.addEventListener('animationend', (event) => {
    if (event.target.matches('[data-motion-step="human-review"]')) completeReconstruction();
  });

  const initial = new URLSearchParams(location.search).get('state') || 'cover';
  setState(initial, { updateUrl: false });
  window.__companyMemoryReview = { setState, replayReconstruction, completeReconstruction, version: VERSION };
})();
