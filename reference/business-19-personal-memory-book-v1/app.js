(() => {
  'use strict';
  const allowed = ['cover','chapter','sources','recollections','timeline','review','mobile'];
  const buttons = [...document.querySelectorAll('[data-state]')];
  const views = [...document.querySelectorAll('[data-view]')];
  const motionTarget = document.querySelector('#provenance-sequence');
  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)');

  const installGuideLink = () => {
    const identityCopy = document.querySelector('.identity > div');
    if (!identityCopy || identityCopy.querySelector('[data-first-use-guide]')) return;
    const guide = document.createElement('a');
    guide.href = './guide.html';
    guide.dataset.firstUseGuide = 'true';
    guide.textContent = '30초 사용법 / Guide';
    guide.setAttribute('aria-label', '나의 기억책 30초 사용법 열기');
    guide.style.cssText = 'display:inline-flex;width:max-content;max-width:100%;min-height:24px;align-items:center;margin-top:4px;padding:3px 7px;border:1px solid #8e867a;color:inherit;text-decoration:none;font:700 9px/1.2 system-ui;white-space:normal';
    identityCopy.append(guide);
  };

  const setState = (state, {updateUrl = true} = {}) => {
    const next = allowed.includes(state) ? state : 'cover';
    buttons.forEach((button) => button.setAttribute('aria-current', button.dataset.state === next ? 'page' : 'false'));
    views.forEach((view) => view.classList.toggle('is-active', view.dataset.view === next));
    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set('state', next);
      history.replaceState(null, '', url);
    }
    if (next === 'chapter') replayMotion();
  };

  const replayMotion = () => {
    if (!motionTarget) return;
    motionTarget.classList.remove('is-revealing');
    if (prefersReduced.matches) {
      motionTarget.classList.add('is-revealing');
      return;
    }
    requestAnimationFrame(() => requestAnimationFrame(() => motionTarget.classList.add('is-revealing')));
  };

  buttons.forEach((button, index) => {
    button.addEventListener('click', () => setState(button.dataset.state));
    button.addEventListener('keydown', (event) => {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      let target = index;
      if (event.key === 'ArrowRight') target = (index + 1) % buttons.length;
      if (event.key === 'ArrowLeft') target = (index - 1 + buttons.length) % buttons.length;
      if (event.key === 'Home') target = 0;
      if (event.key === 'End') target = buttons.length - 1;
      buttons[target].focus();
      setState(buttons[target].dataset.state);
    });
  });
  document.querySelector('[data-motion-replay]')?.addEventListener('click', replayMotion);
  prefersReduced.addEventListener?.('change', replayMotion);

  installGuideLink();
  const initial = new URL(window.location.href).searchParams.get('state');
  setState(initial || (window.innerWidth <= 420 ? 'mobile' : 'cover'), {updateUrl:false});
})();
