(() => {
  const version = 'personal-meaning-map-20260726-1';
  const stateButtons = [...document.querySelectorAll('[data-review-state-button]')];
  const states = [...document.querySelectorAll('[data-review-state]')];
  const explanationToggle = document.querySelector('[data-explanation-toggle]');
  const explanationDrawer = document.querySelector('[data-explanation-drawer]');
  const rippleSheet = document.querySelector('[data-ripple-sheet]');
  const rippleReplay = document.querySelector('[data-ripple-replay]');
  const selectedCopy = document.querySelector('[data-selected-copy]');
  const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  let activeIndex = 0;
  let rippleTimer = 0;

  function setState(index, { moveFocus = false } = {}) {
    activeIndex = (index + states.length) % states.length;

    document.body.dataset.activeState = states[activeIndex]?.dataset.reviewState || '';

    states.forEach((state, stateIndex) => {
      const active = stateIndex === activeIndex;
      state.hidden = !active;
      state.setAttribute('aria-hidden', String(!active));
    });

    stateButtons.forEach((button, buttonIndex) => {
      const active = buttonIndex === activeIndex;
      button.setAttribute('aria-selected', String(active));
      button.tabIndex = active ? 0 : -1;
    });

    if (moveFocus) {
      stateButtons[activeIndex].focus();
    }

    if (states[activeIndex]?.dataset.reviewState === 'ripple') {
      playRipple();
    }
  }

  function playRipple() {
    if (!rippleSheet) return;
    window.clearTimeout(rippleTimer);
    rippleSheet.classList.remove('is-rippling');
    void rippleSheet.offsetWidth;
    rippleSheet.classList.add('is-rippling');
    rippleSheet.dataset.motionMode = motionQuery.matches ? 'reduced' : 'full';
    rippleTimer = window.setTimeout(() => {
      rippleSheet.classList.add('is-settled');
    }, motionQuery.matches ? 20 : 720);
  }

  stateButtons.forEach((button, index) => {
    button.addEventListener('click', () => setState(index));
  });

  document.addEventListener('keydown', (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      setState(activeIndex + 1, { moveFocus: true });
    }
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      setState(activeIndex - 1, { moveFocus: true });
    }
    if (event.key === 'Home') {
      event.preventDefault();
      setState(0, { moveFocus: true });
    }
    if (event.key === 'End') {
      event.preventDefault();
      setState(states.length - 1, { moveFocus: true });
    }
  });

  document.querySelectorAll('[data-select-item]').forEach((item) => {
    item.addEventListener('click', () => {
      const group = item.closest('[data-selection-group]') || document;
      group.querySelectorAll('[data-select-item]').forEach((candidate) => {
        candidate.classList.toggle('is-selected', candidate === item);
        candidate.setAttribute('aria-pressed', String(candidate === item));
      });
      if (selectedCopy && item.dataset.selectionCopy) {
        selectedCopy.textContent = item.dataset.selectionCopy;
      }
      if (item.closest('[data-ripple-sheet]')) playRipple();
    });
  });

  if (explanationToggle && explanationDrawer) {
    explanationToggle.addEventListener('click', () => {
      const open = explanationToggle.getAttribute('aria-expanded') !== 'true';
      explanationToggle.setAttribute('aria-expanded', String(open));
      explanationDrawer.hidden = !open;
      if (open) explanationDrawer.focus();
    });
  }

  if (rippleReplay) {
    rippleReplay.addEventListener('click', playRipple);
  }

  motionQuery.addEventListener?.('change', () => {
    if (states[activeIndex]?.dataset.reviewState === 'ripple') playRipple();
  });

  window.__PMM_REVIEW__ = {
    version,
    stateCount: states.length,
    getActiveState: () => states[activeIndex]?.dataset.reviewState,
    setStateByName(name) {
      const index = states.findIndex((state) => state.dataset.reviewState === name);
      if (index >= 0) setState(index);
      return index >= 0;
    },
    playRipple,
    reducedMotion: () => motionQuery.matches
  };

  setState(0);
})();
