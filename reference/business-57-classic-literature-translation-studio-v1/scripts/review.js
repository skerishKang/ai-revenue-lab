(() => {
  'use strict';

  const states = Array.from(document.querySelectorAll('.visual-state'));
  const tabs = Array.from(document.querySelectorAll('.state-tab'));
  const count = document.getElementById('state-count');
  const sourceReveal = document.querySelector('.source-reveal');
  const phoneSource = document.querySelector('.phone-source');
  const weaveBoard = document.getElementById('weave-board');
  const replayButton = document.getElementById('replay-weave');
  const weaveStatus = document.getElementById('weave-status');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  let activeIndex = 0;
  let replayTimer = null;

  function activateState(nextIndex, focusTab = false) {
    const bounded = (nextIndex + states.length) % states.length;
    activeIndex = bounded;

    states.forEach((state, index) => {
      const active = index === bounded;
      state.classList.toggle('is-active', active);
      state.hidden = !active;
    });

    tabs.forEach((tab, index) => {
      const active = index === bounded;
      tab.classList.toggle('is-active', active);
      if (active) {
        tab.setAttribute('aria-current', 'page');
        if (focusTab) tab.focus();
      } else {
        tab.removeAttribute('aria-current');
      }
    });

    if (count) count.textContent = `${bounded + 1} / ${states.length}`;

    if (states[bounded]?.dataset.state === 'weave') {
      requestAnimationFrame(() => replayWeave(false));
    }
  }

  function replayWeave(announce = true) {
    if (!weaveBoard) return;
    if (replayTimer) window.clearTimeout(replayTimer);

    weaveBoard.classList.remove('is-replaying');
    void weaveBoard.offsetWidth;

    if (!reducedMotion.matches) {
      weaveBoard.classList.add('is-replaying');
      replayTimer = window.setTimeout(() => {
        weaveBoard.classList.remove('is-replaying');
      }, 980);
    }

    if (announce && weaveStatus) {
      weaveStatus.textContent = reducedMotion.matches
        ? '동작 줄이기 설정에 따라 완성된 연결 상태를 즉시 표시했습니다.'
        : '원문 표현과 번역 판단을 다시 연결했습니다.';
    }
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activateState(index));
  });

  document.addEventListener('keydown', (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      activateState(activeIndex + 1, true);
    }
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      activateState(activeIndex - 1, true);
    }
  });

  if (sourceReveal && phoneSource) {
    sourceReveal.addEventListener('click', () => {
      const expanded = sourceReveal.getAttribute('aria-expanded') === 'true';
      sourceReveal.setAttribute('aria-expanded', String(!expanded));
      sourceReveal.textContent = expanded ? '원문 한 문장 보기' : '원문 접기';
      phoneSource.hidden = expanded;
    });
  }

  if (replayButton) {
    replayButton.addEventListener('click', () => replayWeave(true));
  }

  if (typeof reducedMotion.addEventListener === 'function') {
    reducedMotion.addEventListener('change', () => {
      if (states[activeIndex]?.dataset.state === 'weave') replayWeave(false);
    });
  }

  activateState(0);
})();
