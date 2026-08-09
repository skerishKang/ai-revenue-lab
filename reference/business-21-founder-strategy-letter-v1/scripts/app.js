(() => {
  'use strict';
  const states = ['weekly','situation','evidence','tensions','options','decision','mobile'];
  const buttons = [...document.querySelectorAll('[data-state]')];
  const views = [...document.querySelectorAll('[data-view]')];
  const thread = document.querySelector('#argument-thread');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');

  function installGuideLink() {
    if (document.querySelector('[data-first-use-guide]')) return;
    const guide = document.createElement('a');
    guide.href = './guide.html';
    guide.dataset.firstUseGuide = 'true';
    guide.setAttribute('aria-label', '대표 전략 편지 30초 사용법 열기');
    if (window.matchMedia('(max-width:600px)').matches) {
      guide.textContent = '30초 사용법';
      guide.style.cssText = 'position:fixed;right:10px;top:8px;z-index:60;display:inline-flex;align-items:center;min-height:26px;padding:3px 7px;border:1px solid #827c72;background:#f1ede2;color:#1b211e;text-decoration:none;font:700 9px/1.2 system-ui;white-space:nowrap';
      document.body.append(guide);
      return;
    }
    const titleWrap = document.querySelector('.review-header > div');
    if (!titleWrap) return;
    guide.textContent = '30초 사용법 / Guide';
    guide.style.cssText = 'display:inline-flex;width:max-content;max-width:100%;min-height:24px;align-items:center;margin-top:5px;padding:3px 7px;border:1px solid #8f877b;color:inherit;text-decoration:none;font:700 9px/1.2 system-ui;white-space:normal';
    titleWrap.append(guide);
  }

  function replayThread() {
    if (!thread) return;
    thread.classList.remove('is-threading');
    if (reduced.matches) {
      thread.classList.add('is-threading');
      return;
    }
    requestAnimationFrame(() => requestAnimationFrame(() => thread.classList.add('is-threading')));
  }

  function setState(state, updateUrl = true) {
    const next = states.includes(state) ? state : 'weekly';
    buttons.forEach((button) => button.setAttribute('aria-current', button.dataset.state === next ? 'page' : 'false'));
    views.forEach((view) => view.classList.toggle('is-active', view.dataset.view === next));
    if (updateUrl) {
      const url = new URL(location.href);
      url.searchParams.set('state', next);
      history.replaceState(null, '', url);
    }
    if (next === 'tensions') replayThread();
  }

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

  document.querySelector('[data-motion-replay]')?.addEventListener('click', replayThread);
  reduced.addEventListener?.('change', replayThread);
  installGuideLink();
  const initial = new URL(location.href).searchParams.get('state');
  setState(initial || (innerWidth <= 420 ? 'mobile' : 'weekly'), false);
})();
