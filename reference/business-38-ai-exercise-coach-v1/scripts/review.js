
(() => {
  'use strict';
  const tabs = [...document.querySelectorAll('[data-state-tab]')];
  const panels = [...document.querySelectorAll('[data-state-panel]')];
  const motionTrack = document.querySelector('#motion-track');
  const replay = document.querySelector('#replay-motion');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  function activateState(name, {focus = false} = {}) {
    document.body.dataset.currentState = name;
    tabs.forEach((tab) => {
      const active = tab.dataset.stateTab === name;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      if (active && focus) tab.focus({preventScroll: true});
    });
    panels.forEach((panel) => { panel.hidden = panel.dataset.statePanel !== name; });
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activateState(tab.dataset.stateTab));
    tab.addEventListener('keydown', (event) => {
      let next = index;
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      else return;
      event.preventDefault();
      activateState(tabs[next].dataset.stateTab, {focus: true});
    });
  });

  function finishMotion(authority) {
    motionTrack.classList.remove('is-running');
    motionTrack.classList.add('is-complete');
    motionTrack.dataset.completionAuthority = authority;
  }

  function runMotion() {
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    motionTrack.classList.remove('is-running', 'is-complete');
    motionTrack.dataset.completionAuthority = 'pending';
    void motionTrack.offsetWidth;
    if (reduceMotion.matches) {
      finishMotion('reduced-motion-immediate');
      window.scrollTo(scrollX, scrollY);
      return;
    }
    const finalElement = motionTrack.querySelector('.motion-final');
    const onFinalAnimationEnd = (event) => {
      if (event.target !== finalElement || event.animationName !== 'motionFinal') return;
      finalElement.removeEventListener('animationend', onFinalAnimationEnd);
      finishMotion('animationend:motionFinal');
      window.scrollTo(scrollX, scrollY);
    };
    finalElement.addEventListener('animationend', onFinalAnimationEnd);
    motionTrack.classList.add('is-running');
  }

  replay.addEventListener('click', runMotion);
  reduceMotion.addEventListener?.('change', () => {
    if (reduceMotion.matches && motionTrack.dataset.completionAuthority === 'pending') {
      finishMotion('reduced-motion-immediate');
    }
  });

  activateState('cover');
  window.__B38_REVIEW__ = { activateState, runMotion, tabs, panels, motionTrack };
})();
