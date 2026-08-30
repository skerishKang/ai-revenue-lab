(() => {
  'use strict';

  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  const panels = Array.from(document.querySelectorAll('[role="tabpanel"]'));
  const motionBoard = document.getElementById('motion-board');
  const motionFinal = document.getElementById('motion-final');
  const replayButton = document.getElementById('replay-motion');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  function selectTab(tab, focus = true) {
    tabs.forEach((candidate) => {
      const selected = candidate === tab;
      candidate.setAttribute('aria-selected', String(selected));
      candidate.tabIndex = selected ? 0 : -1;
    });

    panels.forEach((panel) => {
      panel.hidden = panel.id !== tab.getAttribute('aria-controls');
    });

    if (focus) tab.focus({ preventScroll: true });
    document.documentElement.dataset.activeState = tab.dataset.state;

    if (tab.dataset.state === 'listing') runMotion();
  }

  function onTabKeydown(event) {
    const currentIndex = tabs.indexOf(event.currentTarget);
    let nextIndex = currentIndex;

    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') nextIndex = (currentIndex + 1) % tabs.length;
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = tabs.length - 1;
    else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      selectTab(event.currentTarget);
      return;
    } else return;

    event.preventDefault();
    selectTab(tabs[nextIndex]);
  }

  function runMotion() {
    if (!motionBoard || !motionFinal) return;

    motionBoard.classList.remove('is-running');
    motionBoard.dataset.motionComplete = 'false';
    motionBoard.dataset.motionStartedAt = String(performance.now());
    void motionBoard.offsetWidth;

    if (reducedMotion.matches) {
      motionBoard.dataset.motionComplete = 'true';
      motionBoard.dataset.motionDuration = '0';
      return;
    }

    motionBoard.classList.add('is-running');
  }

  motionFinal?.addEventListener('animationend', (event) => {
    if (event.animationName !== 'final-listing') return;
    const startedAt = Number(motionBoard.dataset.motionStartedAt || performance.now());
    motionBoard.dataset.motionDuration = String(performance.now() - startedAt);
    motionBoard.dataset.motionComplete = 'true';
  });

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => selectTab(tab, false));
    tab.addEventListener('keydown', onTabKeydown);
  });

  replayButton?.addEventListener('click', runMotion);
  reducedMotion.addEventListener?.('change', () => {
    if (document.documentElement.dataset.activeState === 'listing') runMotion();
  });

  document.documentElement.dataset.activeState = 'cover';
})();
