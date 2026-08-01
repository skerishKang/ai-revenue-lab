(() => {
  'use strict';

  const stateOrder = ['cover', 'sources', 'spine', 'suite', 'adaptation', 'trace', 'mobile'];
  const tabs = Array.from(document.querySelectorAll('[role="tab"][data-state-target]'));
  const panels = Array.from(document.querySelectorAll('[role="tabpanel"][data-state]'));
  const folio = document.querySelector('.folio');
  const relay = document.querySelector('[data-relay]');
  const replayButton = document.querySelector('[data-action="replay"]');
  const reviewStep = relay?.querySelector('.step-review');
  let activeState = 'cover';
  let relayCompletionHandler = null;

  function normalizeState(candidate) {
    return stateOrder.includes(candidate) ? candidate : 'cover';
  }

  function setState(nextState, options = {}) {
    const state = normalizeState(nextState);
    activeState = state;
    panels.forEach((panel) => {
      const isActive = panel.dataset.state === state;
      panel.hidden = !isActive;
      panel.classList.toggle('is-active', isActive);
    });
    tabs.forEach((tab) => {
      const selected = tab.dataset.stateTarget === state;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && options.focusTab) tab.focus({ preventScroll: true });
    });
    const index = stateOrder.indexOf(state) + 1;
    if (folio) folio.textContent = `SET ${String(index).padStart(2, '0')} / 07`;
    const url = new URL(window.location.href);
    url.searchParams.set('state', state);
    window.history.replaceState({ state }, '', url);
    if (state === 'adaptation' && relay && !options.skipRelay) runRelay();
  }

  function restoreRelayView(focused, scrollX, scrollY) {
    window.scrollTo(scrollX, scrollY);
    if (focused && typeof focused.focus === 'function') focused.focus({ preventScroll: true });
  }

  function clearRelayCompletionHandler() {
    if (relay && relayCompletionHandler) {
      relay.removeEventListener('animationend', relayCompletionHandler);
      relayCompletionHandler = null;
    }
  }

  function completeRelay(focused, scrollX, scrollY) {
    if (!relay) return;
    clearRelayCompletionHandler();
    relay.dataset.motionState = 'complete';
    restoreRelayView(focused, scrollX, scrollY);
  }

  function runRelay() {
    if (!relay) return;
    const focused = document.activeElement;
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    clearRelayCompletionHandler();
    relay.classList.remove('relay-running');
    relay.dataset.motionState = 'running';

    if (!reduced && reviewStep) {
      relayCompletionHandler = (event) => {
        if (event.target === reviewStep && event.animationName === 'relayReview') {
          completeRelay(focused, scrollX, scrollY);
        }
      };
      relay.addEventListener('animationend', relayCompletionHandler);
    }

    void relay.offsetWidth;
    relay.classList.add('relay-running');

    window.requestAnimationFrame(() => restoreRelayView(focused, scrollX, scrollY));

    if (reduced || !reviewStep) completeRelay(focused, scrollX, scrollY);
  }

  function moveTab(currentIndex, direction) {
    let nextIndex;
    if (direction === 'home') nextIndex = 0;
    else if (direction === 'end') nextIndex = tabs.length - 1;
    else nextIndex = (currentIndex + direction + tabs.length) % tabs.length;
    setState(tabs[nextIndex].dataset.stateTarget, { focusTab: true });
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => setState(tab.dataset.stateTarget));
    tab.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') { event.preventDefault(); moveTab(index, 1); }
      else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') { event.preventDefault(); moveTab(index, -1); }
      else if (event.key === 'Home') { event.preventDefault(); moveTab(index, 'home'); }
      else if (event.key === 'End') { event.preventDefault(); moveTab(index, 'end'); }
    });
  });

  document.querySelector('[data-action="previous"]')?.addEventListener('click', () => {
    const current = stateOrder.indexOf(activeState);
    setState(stateOrder[(current - 1 + stateOrder.length) % stateOrder.length]);
  });
  document.querySelector('[data-action="next"]')?.addEventListener('click', () => {
    const current = stateOrder.indexOf(activeState);
    setState(stateOrder[(current + 1) % stateOrder.length]);
  });
  replayButton?.addEventListener('click', runRelay);
  window.addEventListener('popstate', () => {
    const state = new URL(window.location.href).searchParams.get('state');
    setState(normalizeState(state), { skipRelay: true });
  });
  const initialState = normalizeState(new URL(window.location.href).searchParams.get('state'));
  setState(initialState, { skipRelay: initialState !== 'adaptation' });
  window.__B22_REVIEW__ = { getState: () => activeState, setState, runRelay, states: [...stateOrder] };
})();
