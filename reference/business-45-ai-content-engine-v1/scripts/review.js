(() => {
  const states = [...document.querySelectorAll('[data-state]')];
  const controls = [...document.querySelectorAll('[data-state-control]')];
  const stage = document.querySelector('#review-stage');
  const stateKeys = ['cover', 'brief', 'structure', 'variants', 'quality', 'kit', 'mobile'];

  function selectState(key, { updateHash = true } = {}) {
    if (!stateKeys.includes(key)) key = 'cover';
    states.forEach((panel) => {
      const active = panel.dataset.state === key;
      panel.hidden = !active;
      panel.classList.toggle('is-active', active);
    });
    controls.forEach((control) => {
      const active = control.dataset.stateControl === key;
      control.setAttribute('aria-selected', String(active));
      control.tabIndex = active ? 0 : -1;
    });
    if (updateHash) history.replaceState(null, '', `#${key}`);
  }

  controls.forEach((control, index) => {
    control.addEventListener('click', () => selectState(control.dataset.stateControl));
    control.addEventListener('keydown', (event) => {
      if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      let target = index;
      if (event.key === 'ArrowRight') target = (index + 1) % controls.length;
      if (event.key === 'ArrowLeft') target = (index - 1 + controls.length) % controls.length;
      if (event.key === 'Home') target = 0;
      if (event.key === 'End') target = controls.length - 1;
      controls[target].focus({ preventScroll: true });
      selectState(controls[target].dataset.stateControl);
    });
  });

  const initial = location.hash.slice(1);
  selectState(stateKeys.includes(initial) ? initial : 'cover', { updateHash: false });

  const motion = document.querySelector('[data-kit-motion]');
  const replay = document.querySelector('[data-motion-replay]');
  const finalElement = motion?.querySelector('.final-element');
  const motionStatus = document.querySelector('[data-motion-status]');

  function completeMotion() {
    motion.classList.remove('is-running');
    motion.classList.add('is-complete');
    motion.dataset.motionState = 'complete';
    motionStatus.textContent = 'HUMAN-APPROVED CONTENT PRODUCTION KIT · complete';
  }

  function runMotion() {
    const focused = document.activeElement;
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    motion.classList.remove('is-running', 'is-complete');
    motion.dataset.motionState = 'idle';
    void motion.offsetWidth;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      completeMotion();
    } else {
      motion.classList.add('is-running');
      motion.dataset.motionState = 'running';
      motionStatus.textContent = 'Brief-to-Content-Production-Kit · running';
    }
    requestAnimationFrame(() => {
      window.scrollTo(scrollX, scrollY);
      if (focused instanceof HTMLElement) focused.focus({ preventScroll: true });
    });
  }

  replay?.addEventListener('click', runMotion);
  finalElement?.addEventListener('animationend', (event) => {
    if (event.animationName === 'kitComplete' && motion.dataset.motionState === 'running') completeMotion();
  });

  window.__ACE_REVIEW__ = { selectState, runMotion, completeMotion, stateKeys, stage };
})();
