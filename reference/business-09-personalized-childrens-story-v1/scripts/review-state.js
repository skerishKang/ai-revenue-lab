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
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  let activeIndex = 0;
  let bloomFrameIds = [];

  function updatePositionLabels() {
    const label = `${activeIndex + 1} / ${stateNames.length}`;
    positionLabel.textContent = label;
    mobilePositionLabel.textContent = label;
  }

  function cancelBloomFrames() {
    bloomFrameIds.forEach((frameId) => window.cancelAnimationFrame(frameId));
    bloomFrameIds = [];
  }

  function resetBloomLayers() {
    if (!bloomStage) return;
    cancelBloomFrames();
    bloomStage.dataset.bloomReady = 'false';
  }

  function startBloomAfterFrames(frameCount) {
    if (!bloomStage) return;
    if (reducedMotion.matches) {
      cancelBloomFrames();
      bloomStage.dataset.bloomReady = 'true';
      return;
    }

    resetBloomLayers();
    void bloomStage.offsetWidth;

    const advance = (remaining) => {
      const frameId = window.requestAnimationFrame(() => {
        bloomFrameIds = bloomFrameIds.filter((id) => id !== frameId);
        if (remaining > 1) {
          advance(remaining - 1);
        } else {
          bloomStage.dataset.bloomReady = 'true';
        }
      });
      bloomFrameIds.push(frameId);
    };

    advance(frameCount);
  }

  function replayBloom() {
    startBloomAfterFrames(1);
  }

  function showState(nextIndex, shouldFocus = false) {
    const normalizedIndex = (nextIndex + stateNames.length) % stateNames.length;
    activeIndex = normalizedIndex;
    const activeName = stateNames[activeIndex];

    if (activeName === 'bloom') resetBloomLayers();

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
      startBloomAfterFrames(2);
    } else {
      resetBloomLayers();
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
