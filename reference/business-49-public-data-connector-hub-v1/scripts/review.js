(() => {
  const controls = [...document.querySelectorAll('[data-state-control]')];
  const states = [...document.querySelectorAll('[data-state]')];
  const replay = document.querySelector('[data-motion-replay]');
  const line = document.querySelector('[data-connector-line]');
  const seal = document.querySelector('.connector-spec-seal');
  const status = document.querySelector('[data-motion-status]');
  const panelsByKey = new Map(states.map((panel) => [panel.dataset.state, panel]));

  controls.forEach((button) => {
    const key = button.dataset.stateControl;
    const panel = panelsByKey.get(key);
    if (!panel) return;
    const tabId = `state-tab-${key}`;
    const panelId = `state-panel-${key}`;
    button.id = tabId;
    button.setAttribute('aria-controls', panelId);
    panel.id = panelId;
    panel.setAttribute('aria-labelledby', tabId);
  });

  function selectState(key, focus = false) {
    controls.forEach((button) => {
      const selected = button.dataset.stateControl === key;
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
      if (selected && focus) button.focus({ preventScroll: true });
    });
    states.forEach((panel) => {
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
    });
  });

  function complete() {
    line.classList.remove('is-running');
    line.classList.add('is-complete');
    line.dataset.motionState = 'complete';
    status.textContent = 'HUMAN-REVIEWED PUBLIC DATA CONNECTOR SPEC · complete';
  }

  if (seal) {
    seal.addEventListener('animationend', (event) => {
      if (event.animationName === 'connectorSpecComplete') complete();
    });
  }

  if (replay) {
    replay.addEventListener('click', () => {
      const focusTarget = document.activeElement;
      const scrollX = window.scrollX;
      const scrollY = window.scrollY;
      line.classList.remove('is-running', 'is-complete');
      line.dataset.motionState = 'idle';
      status.textContent = 'Source-to-Public-Data-Connector-Spec · running';
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
