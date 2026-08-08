(() => {
  'use strict';
  const states = ['weekly','situation','evidence','tensions','options','decision','mobile'];
  const buttons = [...document.querySelectorAll('[data-state]')];
  const views = [...document.querySelectorAll('[data-view]')];
  const thread = document.querySelector('#argument-thread');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');

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
  const initial = new URL(location.href).searchParams.get('state');
  setState(initial || (innerWidth <= 420 ? 'mobile' : 'weekly'), false);
})();
