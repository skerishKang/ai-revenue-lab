(() => {
  'use strict';

  const states = ['matchday', 'preview', 'notes', 'review', 'player', 'season', 'mobile'];
  const buttons = [...document.querySelectorAll('[data-state-target]')];
  const panels = [...document.querySelectorAll('[data-state]')];
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let activeIndex = 0;

  function setState(name, { focus = false, replaceUrl = true } = {}) {
    const nextIndex = states.indexOf(name);
    if (nextIndex < 0) return;
    activeIndex = nextIndex;

    panels.forEach((panel) => {
      const active = panel.dataset.state === name;
      panel.hidden = !active;
      panel.classList.toggle('is-active', active);
    });

    buttons.forEach((button) => {
      const active = button.dataset.stateTarget === name;
      button.setAttribute('aria-selected', String(active));
      button.tabIndex = active ? 0 : -1;
      if (active && focus) button.focus({ preventScroll: true });
    });

    document.body.dataset.reviewState = name;
    if (replaceUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set('state', name);
      history.replaceState(null, '', url);
    }
  }

  function replayTurningPoint() {
    const review = document.querySelector('[data-state="review"]');
    if (!review) return;
    if (review.classList.contains('motion-complete') || review.classList.contains('motion-running')) return;

    review.classList.remove('motion-complete', 'motion-running');
    void review.offsetWidth;

    if (reducedMotion.matches) {
      review.classList.add('motion-complete');
      return;
    }

    let sweepDone = false;
    let safetyTimer = null;

    function onSweepComplete() {
      if (sweepDone) return;
      sweepDone = true;
      if (safetyTimer) { clearTimeout(safetyTimer); safetyTimer = null; }
      review.classList.remove('motion-running');
      review.classList.add('motion-complete');
      const btn = document.querySelector('.motion-replay');
      if (btn) btn.setAttribute('aria-pressed', 'false');
    }

    const noteEl = review.querySelector('.player-review-note');
    if (noteEl) {
      noteEl.addEventListener('animationend', onSweepComplete, { once: true });
    }

    safetyTimer = setTimeout(() => { if (!sweepDone) onSweepComplete(); }, 2000);

    review.classList.add('motion-running');
    const btn = document.querySelector('.motion-replay');
    if (btn) btn.setAttribute('aria-pressed', 'true');
  }

  buttons.forEach((button) => {
    button.addEventListener('click', () => setState(button.dataset.stateTarget));
    button.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      event.stopPropagation();
      if (event.key === 'Home') activeIndex = 0;
      else if (event.key === 'End') activeIndex = states.length - 1;
      else activeIndex = (activeIndex + (event.key === 'ArrowRight' ? 1 : -1) + states.length) % states.length;
      setState(states[activeIndex], { focus: true });
    });
  });

  document.addEventListener('keydown', (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '')) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      activeIndex = (activeIndex + (event.key === 'ArrowRight' ? 1 : -1) + states.length) % states.length;
      setState(states[activeIndex]);
    }
  });

  document.querySelector('.motion-replay')?.addEventListener('click', replayTurningPoint);

  const initial = new URLSearchParams(window.location.search).get('state');
  setState(states.includes(initial) ? initial : states[0], { replaceUrl: false });
  if (initial === 'review' && new URLSearchParams(window.location.search).get('motion') === 'play') {
    requestAnimationFrame(replayTurningPoint);
  }

  window.personalSportsReview = { setState, replayTurningPoint, states: [...states] };
})();
