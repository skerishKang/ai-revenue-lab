(() => {
  const keys = ['cover','brief','guided-run','evidence','review','skill-card','mobile'];
  const tabs = [...document.querySelectorAll('[role="tab"][data-state]')];
  const panels = [...document.querySelectorAll('[role="tabpanel"][data-state]')];
  const activate = (key, focus = false) => {
    if (!keys.includes(key)) return;
    tabs.forEach((tab) => {
      const selected = tab.dataset.state === key;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    });
    panels.forEach((panel) => {
      const active = panel.dataset.state === key;
      panel.hidden = !active;
      panel.classList.toggle('active', active);
    });
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activate(tab.dataset.state));
    tab.addEventListener('keydown', (event) => {
      let next = null;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next !== null) { event.preventDefault(); activate(tabs[next].dataset.state, true); }
    });
  });
  const root = document.querySelector('#skill-motion');
  const seal = document.querySelector('#verified-skill-seal');
  const replay = document.querySelector('#replay-skill');
  const status = document.querySelector('#motion-status');
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  const completeImmediately = () => {
    root.classList.remove('running');
    root.classList.add('complete');
    root.dataset.motionState = 'complete';
    status.textContent = 'complete · reduced motion';
  };
  const run = () => {
    if (reduce.matches) { completeImmediately(); return; }
    const scrollX = window.scrollX; const scrollY = window.scrollY;
    root.classList.remove('running','complete');
    root.dataset.motionState = 'idle';
    void root.offsetWidth;
    root.classList.add('running');
    root.dataset.motionState = 'running';
    status.textContent = 'running · task to verified skill';
    window.scrollTo(scrollX, scrollY);
  };
  replay.addEventListener('click', run);
  seal.addEventListener('animationend', (event) => {
    if (event.animationName !== 'skillSeal' || event.target !== seal) return;
    root.classList.remove('running');
    root.classList.add('complete');
    root.dataset.motionState = 'complete';
    status.textContent = 'complete · verified organizational AI skill';
  });
  reduce.addEventListener?.('change', (event) => { if (event.matches) completeImmediately(); });
  activate('cover');
})();
