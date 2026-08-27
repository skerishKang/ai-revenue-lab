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
  const finalMotionElement = weaveBoard?.querySelector('.rendering-3');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  let activeIndex = 0;
  let pendingMotionEnd = null;

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
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
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

  function clearPendingMotionEnd() {
    if (pendingMotionEnd && finalMotionElement) {
      finalMotionElement.removeEventListener('animationend', pendingMotionEnd);
    }
    pendingMotionEnd = null;
  }

  function setWeaveComplete(message) {
    if (!weaveBoard) return;
    weaveBoard.dataset.motionState = 'complete';
    if (message && weaveStatus) weaveStatus.textContent = message;
  }

  function replayWeave(announce = true) {
    if (!weaveBoard) return;
    clearPendingMotionEnd();

    setWeaveComplete();
    void weaveBoard.offsetWidth;

    if (reducedMotion.matches || !finalMotionElement) {
      setWeaveComplete(
        announce
          ? '동작 줄이기 설정에 따라 완성된 연결 상태를 즉시 표시했습니다.'
          : '원문 표현 3개와 번역 판단 3개가 연결되었습니다.'
      );
      return;
    }

    pendingMotionEnd = (event) => {
      if (event.animationName !== 'settle-rendering') return;
      clearPendingMotionEnd();
      setWeaveComplete('원문 표현 3개와 번역 판단 3개가 연결되었습니다.');
    };
    finalMotionElement.addEventListener('animationend', pendingMotionEnd);
    weaveBoard.dataset.motionState = 'running';

    if (announce && weaveStatus) {
      weaveStatus.textContent = '원문 표현과 번역 판단을 다시 연결하고 있습니다.';
    }
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activateState(index));
    tab.addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
      event.preventDefault();
      activateState(index + (event.key === 'ArrowRight' ? 1 : -1), true);
    });
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
