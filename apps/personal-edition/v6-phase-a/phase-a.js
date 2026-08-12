(() => {
  const params = new URLSearchParams(location.search);
  const direction = ['a','b','c'].includes(params.get('direction')) ? params.get('direction') : 'a';
  const screen = ['entry','library','read'].includes(params.get('screen')) ? params.get('screen') : 'entry';
  document.body.dataset.direction = direction;
  document.body.dataset.screen = screen;

  document.querySelectorAll('[data-screen-panel]').forEach((el) => {
    el.hidden = el.dataset.screenPanel !== screen;
  });

  document.querySelectorAll('[data-dir]').forEach((a) => {
    a.classList.toggle('is-active', a.dataset.dir === direction);
    a.setAttribute('aria-current', a.dataset.dir === direction ? 'true' : 'false');
    a.href = `?direction=${a.dataset.dir}&screen=${screen}`;
  });

  document.querySelectorAll('[data-view]').forEach((a) => {
    a.classList.toggle('is-active', a.dataset.view === screen);
    a.setAttribute('aria-current', a.dataset.view === screen ? 'page' : 'false');
    a.href = `?direction=${direction}&screen=${a.dataset.view}`;
  });

  document.querySelectorAll('a[href*="direction=a&screen="]').forEach((a) => {
    a.href = a.href.replace('direction=a', `direction=${direction}`);
  });

  document.title = `B01 V6 ${direction.toUpperCase()} · ${screen} — Personal Edition`;
})();
