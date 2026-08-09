(() => {
  'use strict';
  const states = Array.from(document.querySelectorAll('.visual-state'));
  const tabs = Array.from(document.querySelectorAll('.state-tab'));
  const count = document.getElementById('state-count');
  const counterPage = document.getElementById('counter-page');
  const replayButton = document.getElementById('replay-counter');
  const motionStatus = document.getElementById('motion-status');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let activeIndex = 0;
  let replaying = false;

  function installGuideLink() {
    const meta = document.querySelector('.rail-meta');
    if (!meta || meta.querySelector('[data-first-use-guide]')) return;
    const guide = document.createElement('a');
    guide.href = './guide.html';
    guide.dataset.firstUseGuide = 'true';
    guide.textContent = '30초 사용법 / Guide';
    guide.setAttribute('aria-label', '우리 가게 매거진 30초 사용법 열기');
    guide.style.cssText = 'display:inline-flex;width:90px;max-width:100%;min-height:32px;align-items:center;justify-content:center;padding:5px 2px;border:1px solid currentColor;color:inherit;text-decoration:none;text-align:center;font:700 10px/1.2 system-ui;white-space:normal;overflow-wrap:anywhere';
    meta.prepend(guide);
  }

  function activate(index, focusTab = false) {
    const bounded = (index + states.length) % states.length;
    activeIndex = bounded;
    states.forEach((state, stateIndex) => {
      const active = stateIndex === bounded;
      state.hidden = !active;
      state.classList.toggle('is-active', active);
    });
    tabs.forEach((tab, tabIndex) => {
      const active = tabIndex === bounded;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      if (active && focusTab) tab.focus();
    });
    if (count) count.textContent = `${bounded + 1} / ${states.length}`;
  }

  function completeMotion(message) {
    if (!counterPage) return;
    counterPage.classList.remove('is-replaying');
    counterPage.dataset.motionState = 'complete';
    replaying = false;
    if (motionStatus) motionStatus.textContent = message;
  }

  function replayCounter() {
    if (!counterPage || replaying) return;
    if (reducedMotion.matches) {
      completeMotion('동작 줄이기 설정에 따라 완성된 지면을 즉시 표시했습니다.');
      return;
    }
    replaying = true;
    counterPage.classList.remove('is-replaying');
    counterPage.dataset.motionState = 'idle';
    void counterPage.offsetWidth;
    counterPage.classList.add('is-replaying');
    counterPage.dataset.motionState = 'running';
    if (motionStatus) motionStatus.textContent = '카운터 조각을 지면으로 엮고 있습니다.';
  }

  tabs.forEach((tab, index) => tab.addEventListener('click', () => activate(index)));
  document.addEventListener('keydown', (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      activate(activeIndex + 1, true);
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      activate(activeIndex - 1, true);
    }
  });

  if (replayButton && counterPage) {
    replayButton.addEventListener('click', replayCounter);
    counterPage.addEventListener('animationend', (event) => {
      if (event.animationName === 'revealQuote') {
        completeMotion('영수증, 라벨, 상품 사진과 점주 인용이 완성된 지면으로 정렬되었습니다.');
      }
    });
  }
  if (typeof reducedMotion.addEventListener === 'function') {
    reducedMotion.addEventListener('change', () => completeMotion('완성된 지면 상태입니다.'));
  }
  installGuideLink();
  activate(0);
  completeMotion('완성된 표지 상태입니다.');
})();
