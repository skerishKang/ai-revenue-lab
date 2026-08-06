(() => {
  'use strict';
  const controls = [...document.querySelectorAll('[data-state-control]')];
  const states = [...document.querySelectorAll('[data-state]')];
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  function selectState(name, focusControl = false) {
    controls.forEach((control) => {
      const selected = control.dataset.stateControl === name;
      control.setAttribute('aria-selected', String(selected));
      control.tabIndex = selected ? 0 : -1;
      if (selected && focusControl) control.focus({ preventScroll: true });
    });
    states.forEach((state) => {
      const selected = state.dataset.state === name;
      state.hidden = !selected;
      state.classList.toggle('is-active', selected);
    });
  }

  controls.forEach((control, index) => {
    control.addEventListener('click', () => selectState(control.dataset.stateControl));
    control.addEventListener('keydown', (event) => {
      let target = null;
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') target = (index + 1) % controls.length;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') target = (index - 1 + controls.length) % controls.length;
      if (event.key === 'Home') target = 0;
      if (event.key === 'End') target = controls.length - 1;
      if (target === null) return;
      event.preventDefault();
      selectState(controls[target].dataset.stateControl, true);
    });
  });

  const replay = document.querySelector('[data-motion-replay]');
  const line = document.querySelector('[data-delivery-line]');
  const seal = document.querySelector('.software-delivery-seal');
  const status = document.querySelector('[data-motion-status]');

  function complete() {
    line.classList.remove('is-running');
    line.classList.add('is-complete');
    line.dataset.motionState = 'complete';
    status.textContent = 'HUMAN-VERIFIED SOFTWARE DELIVERY PACKAGE · complete';
  }

  function replayMotion() {
    const focusBefore = document.activeElement;
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    line.classList.remove('is-running', 'is-complete');
    line.dataset.motionState = 'idle';
    void line.offsetWidth;
    if (reducedMotion.matches) {
      complete();
    } else {
      line.classList.add('is-running');
      line.dataset.motionState = 'running';
      status.textContent = 'Production trace · running';
    }
    if (focusBefore && typeof focusBefore.focus === 'function') focusBefore.focus({ preventScroll: true });
    window.scrollTo(scrollX, scrollY);
  }

  seal.addEventListener('animationend', (event) => {
    if (event.animationName === 'deliveryPackageComplete') complete();
  });
  replay.addEventListener('click', replayMotion);
  reducedMotion.addEventListener?.('change', () => {
    if (reducedMotion.matches && line.dataset.motionState === 'running') complete();
  });
  selectState('cover');
})();
