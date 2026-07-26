(() => {
  'use strict';

  const stateNames = [
    'cover',
    'spread',
    'transformation',
    'branch',
    'parent-note',
    'mobile',
    'bloom'
  ];

  const stateSections = Array.from(document.querySelectorAll('[data-state]'));
  const stateTabs = Array.from(document.querySelectorAll('[data-state-target]'));
  const positionLabel = document.getElementById('state-position');
  const mobilePositionLabel = document.getElementById('mobile-state-position');
  const previousButton = document.getElementById('previous-state');
  const nextButton = document.getElementById('next-state');
  const replayButton = document.getElementById('replay-bloom');
  const bloomStage = document.getElementById('bloom-stage');

  let activeIndex = 0;

  function updatePositionLabels() {
    const label = `${activeIndex + 1} / ${stateNames.length}`;
    positionLabel.textContent = label;
    mobilePositionLabel.textContent = label;
  }

  function replayBloom() {
    if (!bloomStage) return;
    bloomStage.dataset.bloomReady = 'false';
    void bloomStage.offsetWidth;
    bloomStage.dataset.bloomReady = 'true';
  }

  function showState(nextIndex, shouldFocus = false) {
    const normalizedIndex = (nextIndex + stateNames.length) % stateNames.length;
    activeIndex = normalizedIndex;
    const activeName = stateNames[activeIndex];

    stateSections.forEach((section) => {
      const isActive = section.dataset.state === activeName;
      section.hidden = !isActive;
      section.classList.toggle('is-active', isActive);
    });

    stateTabs.forEach((tab) => {
      const isActive = tab.dataset.stateTarget === activeName;
      tab.classList.toggle('is-active', isActive);
      if (isActive) {
        tab.setAttribute('aria-current', 'page');
        if (shouldFocus) tab.focus();
      } else {
        tab.removeAttribute('aria-current');
      }
    });

    updatePositionLabels();
    document.body.dataset.reviewState = activeName;

    if (activeName === 'bloom') {
      window.setTimeout(replayBloom, 30);
    }

    window.dispatchEvent(new CustomEvent('review-state-change', {
      detail: { state: activeName, index: activeIndex }
    }));
  }

  stateTabs.forEach((tab, index) => {
    tab.addEventListener('click', () => showState(index));
  });

  previousButton.addEventListener('click', () => showState(activeIndex - 1));
  nextButton.addEventListener('click', () => showState(activeIndex + 1));
  replayButton.addEventListener('click', replayBloom);

  document.addEventListener('keydown', (event) => {
    const target = event.target;
    const isEditable = target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement ||
      target.isContentEditable;

    if (isEditable) return;

    if (event.key === 'ArrowRight') {
      event.preventDefault();
      showState(activeIndex + 1, true);
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      showState(activeIndex - 1, true);
    } else if (event.key === 'Home') {
      event.preventDefault();
      showState(0, true);
    } else if (event.key === 'End') {
      event.preventDefault();
      showState(stateNames.length - 1, true);
    }
  });

  window.__PERSONALIZED_STORY_REVIEW__ = {
    states: [...stateNames],
    showStateByName(name) {
      const index = stateNames.indexOf(name);
      if (index >= 0) showState(index);
    },
    replayBloom,
    getActiveState() {
      return stateNames[activeIndex];
    }
  };

  showState(0);
})();
