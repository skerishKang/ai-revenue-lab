(() => {
  'use strict';
  const VERSION = 'business-40-v1-20260729';
  const STATES = ['cover','report','indicators','conflicts','review','handoff','mobile'];
  const tabs = [...document.querySelectorAll('[role="tab"][data-state-target]')];
  const panels = [...document.querySelectorAll('[role="tabpanel"][data-state]')];
  const track = document.getElementById('motion-track');
  const replay = document.getElementById('replay-motion');
  const status = document.getElementById('motion-status');
  const finalStep = track.querySelector('[data-motion-final]');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let replayCount = 0;
  let motionRunning = false;

  document.documentElement.dataset.assetVersion = VERSION;

  function selectState(name, moveFocus = false) {
    if (!STATES.includes(name)) return;
    document.body.dataset.activeState = name;
    tabs.forEach((tab) => {
      const selected = tab.dataset.stateTarget === name;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && moveFocus) tab.focus({preventScroll:true});
    });
    panels.forEach((panel) => { panel.hidden = panel.dataset.state !== name; });
    try { history.replaceState(null, '', `#${name}`); } catch (_) { /* inline/file review fallback */ }
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectState(tab.dataset.stateTarget));
    tab.addEventListener('keydown', (event) => {
      let next = index;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectState(tab.dataset.stateTarget); return; }
      else return;
      event.preventDefault();
      selectState(tabs[next].dataset.stateTarget, true);
    });
  });

  function markComplete(mode) {
    track.classList.remove('is-replaying');
    track.classList.add('is-complete');
    track.dataset.replayCount = String(replayCount);
    track.dataset.completionAuthority = mode;
    status.textContent = `Complete · replay ${replayCount} · ${mode}`;
    motionRunning = false;
    replay.removeAttribute('aria-disabled');
    replay.removeAttribute('aria-busy');
  }

  function replayMotion() {
    if (motionRunning) return;
    motionRunning = true;
    replayCount += 1;
    const activeBefore = document.activeElement;
    const scrollBefore = {x: window.scrollX, y: window.scrollY};
    track.classList.remove('is-replaying', 'is-complete');
    void track.offsetWidth;
    replay.setAttribute('aria-disabled', 'true');
    replay.setAttribute('aria-busy', 'true');
    status.textContent = `Running · replay ${replayCount}`;

    if (reducedMotion.matches) {
      track.classList.add('is-complete');
      [...track.children].forEach((step) => { step.style.opacity = '1'; step.style.transform = 'none'; });
      track.dataset.focusStable = String(document.activeElement === activeBefore);
      track.dataset.scrollStable = String(window.scrollX === scrollBefore.x && window.scrollY === scrollBefore.y);
      markComplete('reduced-motion immediate information-complete');
      return;
    }

    const onFinalAnimationEnd = (event) => {
      if (event.target !== finalStep || event.animationName !== 'motion-reveal') return;
      finalStep.removeEventListener('animationend', onFinalAnimationEnd);
      track.dataset.focusStable = String(document.activeElement === activeBefore || activeBefore === replay);
      track.dataset.scrollStable = String(window.scrollX === scrollBefore.x && window.scrollY === scrollBefore.y);
      markComplete('final-element animationend');
    };
    finalStep.addEventListener('animationend', onFinalAnimationEnd);
    track.classList.add('is-replaying');
  }

  replay.addEventListener('click', replayMotion);
  const initial = location.hash.slice(1);
  selectState(STATES.includes(initial) ? initial : 'cover');
  window.__BUSINESS40__ = { version: VERSION, states: [...STATES], selectState, replayMotion };
})();
