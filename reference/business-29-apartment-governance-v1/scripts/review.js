(() => {
  const tabs = [...document.querySelectorAll('[data-state-target]')];
  const states = [...document.querySelectorAll('[data-state]')];
  const stage = document.querySelector('#review-stage');
  const motion = document.querySelector('[data-agenda-resolution]');
  const replay = document.querySelector('[data-motion-replay]');
  const names = new Set(states.map((item) => item.dataset.state));

  function completeMotion() {
    if (!motion) return;
    motion.classList.remove('is-running');
    motion.classList.add('is-complete');
    motion.dataset.motionState = 'complete';
  }

  function replayMotion() {
    if (!motion) return;
    motion.classList.remove('is-running', 'is-complete');
    motion.dataset.motionState = 'idle';
    void motion.offsetWidth;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) completeMotion();
    else {
      motion.classList.add('is-running');
      motion.dataset.motionState = 'running';
    }
  }

  function setState(name, { focus = false, updateUrl = true } = {}) {
    const next = names.has(name) ? name : 'cover';
    states.forEach((item) => {
      const active = item.dataset.state === next;
      item.hidden = !active;
      item.classList.toggle('is-active', active);
    });
    tabs.forEach((tab) => {
      const active = tab.dataset.stateTarget === next;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    if (next === 'meeting') replayMotion();
    if (focus) stage.focus({ preventScroll: true });
    if (updateUrl) history.replaceState(null, '', `?state=${next}`);
    document.documentElement.dataset.reviewState = next;
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => setState(tab.dataset.stateTarget, { focus: true }));
    tab.addEventListener('keydown', (event) => {
      let target = index;
      if (event.key === 'ArrowRight') target = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') target = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === 'Home') target = 0;
      else if (event.key === 'End') target = tabs.length - 1;
      else return;
      event.preventDefault();
      tabs[target].focus();
      setState(tabs[target].dataset.stateTarget);
    });
  });

  replay?.addEventListener('click', replayMotion);
  motion?.querySelector('.public-notice-complete')?.addEventListener('animationend', (event) => {
    if (event.animationName === 'publicNoticeComplete') completeMotion();
  });

  const initial = new URLSearchParams(location.search).get('state') || 'cover';
  setState(initial, { updateUrl: false });
  window.__apartmentGovernanceReview = { setState, replayMotion, completeMotion, version: 'apartment-governance-20260728-1' };
})();
