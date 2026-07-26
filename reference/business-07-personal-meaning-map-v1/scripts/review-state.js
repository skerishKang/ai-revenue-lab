(() => {
  const version = 'personal-meaning-map-20260726-2';
  const stateButtons = [...document.querySelectorAll('[data-review-state-button]')];
  const states = [...document.querySelectorAll('[data-review-state]')];
  const rippleSheet = document.querySelector('[data-ripple-sheet]');
  const rippleReplay = rippleSheet?.querySelector('[data-ripple-replay]');
  const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  let activeIndex = 0;
  let rippleTimer = 0;

  function drawerForToggle(toggle) {
    const state = toggle.closest('[data-review-state]');
    return state?.querySelector('[data-explanation-drawer]') || null;
  }

  function closeStateDrawers(state) {
    state.querySelectorAll('[data-explanation-toggle]').forEach((toggle) => {
      const drawer = drawerForToggle(toggle);
      if (!drawer) return;
      toggle.setAttribute('aria-expanded', 'false');
      drawer.hidden = true;
    });
  }

  function setState(index, { moveFocus = false } = {}) {
    activeIndex = (index + states.length) % states.length;
    const nextState = states[activeIndex];
    const focusWasInHiddenState = states.some((state, stateIndex) => (
      stateIndex !== activeIndex && state.contains(document.activeElement)
    ));

    document.body.dataset.activeState = nextState?.dataset.reviewState || '';

    states.forEach((state, stateIndex) => {
      const active = stateIndex === activeIndex;
      if (!active) closeStateDrawers(state);
      state.hidden = !active;
      state.setAttribute('aria-hidden', String(!active));
    });

    stateButtons.forEach((button, buttonIndex) => {
      const active = buttonIndex === activeIndex;
      button.setAttribute('aria-selected', String(active));
      button.tabIndex = active ? 0 : -1;
    });

    if (moveFocus || focusWasInHiddenState) {
      stateButtons[activeIndex].focus({ preventScroll: true });
    }

    if (nextState?.dataset.reviewState === 'ripple') {
      playRipple();
    }
  }

  function playRipple() {
    if (!rippleSheet) return;
    window.clearTimeout(rippleTimer);
    rippleSheet.classList.remove('is-rippling', 'is-settled');
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

  document.querySelectorAll('[data-selection-group]').forEach((group) => {
    const selectedCopy = group.querySelector('[data-selected-copy]');
    group.querySelectorAll('[data-select-item]').forEach((item) => {
      item.addEventListener('click', () => {
        group.querySelectorAll('[data-select-item]').forEach((candidate) => {
          const selected = candidate === item;
          candidate.classList.toggle('is-selected', selected);
          candidate.setAttribute('aria-pressed', String(selected));
        });
        if (selectedCopy && item.dataset.selectionCopy) {
          selectedCopy.textContent = item.dataset.selectionCopy;
        }
        if (group.matches('[data-ripple-sheet]')) playRipple();
      });
    });
  });

  document.querySelectorAll('[data-explanation-toggle]').forEach((toggle) => {
    const drawer = drawerForToggle(toggle);
    if (!drawer) return;

    toggle.setAttribute('aria-expanded', String(!drawer.hidden));
    toggle.addEventListener('click', () => {
      const open = drawer.hidden;
      const focusWasInDrawer = drawer.contains(document.activeElement);
      toggle.setAttribute('aria-expanded', String(open));
      drawer.hidden = !open;

      if (open && !drawer.closest('[hidden]')) {
        drawer.focus({ preventScroll: true });
      } else if (!open && focusWasInDrawer) {
        toggle.focus({ preventScroll: true });
      }
    });
  });

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
