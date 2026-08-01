(() => {
  const keys = ['cover', 'question', 'source-map', 'procedure', 'branches', 'draft', 'mobile'];
  const tabs = [...document.querySelectorAll('[role="tab"][data-state]')];
  const panels = [...document.querySelectorAll('[role="tabpanel"][data-state]')];
  const route = document.querySelector('#route-motion');
  const seal = document.querySelector('#route-seal');
  const replay = document.querySelector('#replay-route');
  const status = document.querySelector('#motion-status');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');

  const setState = (key, focus = false) => {
    if (!keys.includes(key)) return;
    tabs.forEach((tab) => {
      const selected = tab.dataset.state === key;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    });
    panels.forEach((panel) => {
      const selected = panel.dataset.state === key;
      panel.hidden = !selected;
      panel.classList.toggle('is-active', selected);
    });
  };

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => setState(tab.dataset.state));
    tab.addEventListener('keydown', (event) => {
      let next = index;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      else return;
      event.preventDefault();
      setState(tabs[next].dataset.state, true);
    });
  });

  const completeRoute = () => {
    route.classList.remove('running');
    route.classList.add('complete');
    route.dataset.motionState = 'complete';
    status.textContent = 'motion state: complete';
  };

  const replayRoute = () => {
    route.classList.remove('complete', 'running');
    route.dataset.motionState = 'idle';
    status.textContent = 'motion state: idle';
    void route.offsetWidth;
    if (reduced.matches) {
      completeRoute();
      return;
    }
    route.classList.add('running');
    route.dataset.motionState = 'running';
    status.textContent = 'motion state: running';
  };

  seal.addEventListener('animationend', (event) => {
    if (event.animationName === 'routeSeal' && route.classList.contains('running')) completeRoute();
  });
  replay.addEventListener('click', replayRoute);
  reduced.addEventListener?.('change', () => { if (reduced.matches) completeRoute(); });
  setState('cover');
  completeRoute();
})();
