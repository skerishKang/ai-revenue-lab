(() => {
  const controls = [...document.querySelectorAll('[data-state-control]')];
  const panels = [...document.querySelectorAll('[data-state]')];
  const replay = document.querySelector('[data-motion-replay]');
  const line = document.querySelector('[data-integration-line]');
  const seal = document.querySelector('.integration-spec-seal');
  const status = document.querySelector('[data-motion-status]');

  function selectState(key, focus = false) {
    controls.forEach((button) => {
      const selected = button.dataset.stateControl === key;
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
      if (selected && focus) button.focus({ preventScroll: true });
    });
    panels.forEach((panel) => {
      const active = panel.dataset.state === key;
      panel.hidden = !active;
      panel.classList.toggle('is-active', active);
    });
  }

  controls.forEach((button, index) => {
    button.addEventListener('click', () => selectState(button.dataset.stateControl));
    button.addEventListener('keydown', (event) => {
      let next = null;
      if (event.key === 'ArrowRight') next = (index + 1) % controls.length;
      if (event.key === 'ArrowLeft') next = (index - 1 + controls.length) % controls.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = controls.length - 1;
      if (next !== null) {
        event.preventDefault();
        selectState(controls[next].dataset.stateControl, true);
      }
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        selectState(button.dataset.stateControl, true);
      }
    });
  });

  function complete() {
    line.classList.remove('is-running');
    line.classList.add('is-complete');
    line.dataset.motionState = 'complete';
    status.textContent = 'HUMAN-APPROVED EMBEDDED AI INTEGRATION SPEC · complete';
  }

  if (seal) {
    seal.addEventListener('animationend', (event) => {
      if (event.animationName === 'integrationSpecComplete') complete();
    });
  }

  if (replay) {
    replay.addEventListener('click', () => {
      const focusTarget = document.activeElement;
      const scrollX = window.scrollX;
      const scrollY = window.scrollY;
      line.classList.remove('is-running', 'is-complete');
      line.dataset.motionState = 'idle';
      status.textContent = 'Capability-to-Embedded-Integration-Spec · running';
      void line.offsetWidth;
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        complete();
      } else {
        line.classList.add('is-running');
        line.dataset.motionState = 'running';
      }
      if (focusTarget && focusTarget.focus) focusTarget.focus({ preventScroll: true });
      window.scrollTo(scrollX, scrollY);
    });
  }

  selectState('cover');
})();
