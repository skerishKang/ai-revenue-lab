(() => {
  const states = [...document.querySelectorAll('[data-state]')];
  const navButtons = [...document.querySelectorAll('[data-state-target]')];
  const allowed = new Set(states.map((node) => node.dataset.state));
  const params = new URLSearchParams(window.location.search);
  const initial = allowed.has(params.get('state')) ? params.get('state') : 'today';

  function installGuideLink() {
    const nav = document.querySelector('.state-nav');
    if (!nav || nav.querySelector('[data-first-use-guide]')) return;
    const guide = document.createElement('a');
    guide.href = './guide.html';
    guide.dataset.firstUseGuide = 'true';
    guide.textContent = '30초 사용법 / Guide';
    guide.setAttribute('aria-label', '나의 오디오 채널 30초 사용법 열기');
    guide.style.cssText = 'display:inline-flex;flex:0 0 auto;align-items:center;min-height:38px;padding:0 12px;border-left:1px solid currentColor;color:inherit;text-decoration:none;font:700 11px/1.2 system-ui;white-space:nowrap';
    nav.append(guide);
  }

  function showState(name, updateUrl = true) {
    if (!allowed.has(name)) return;
    states.forEach((section) => { section.hidden = section.dataset.state !== name; });
    navButtons.forEach((button) => {
      const active = button.dataset.stateTarget === name;
      if (button.closest('.state-nav')) {
        button.toggleAttribute('aria-current', active);
      }
    });
    document.body.dataset.activeState = name;
    if (updateUrl) {
      const next = new URL(window.location.href);
      next.searchParams.set('state', name);
      history.replaceState(null, '', next);
    }
    document.querySelector(`[data-state="${name}"]`)?.scrollTo?.(0, 0);
  }

  navButtons.forEach((button) => button.addEventListener('click', () => showState(button.dataset.stateTarget)));

  const listening = document.querySelector('[data-state="listening"]');
  const pulseTrigger = document.querySelector('[data-pulse-trigger]');
  const title = document.querySelector('[data-pulse-title]');
  const transcript = document.querySelector('[data-pulse-transcript]');
  const citation = document.querySelector('[data-pulse-source]');
  const row = document.querySelector('[data-pulse-row]');
  const original = {
    title: title?.textContent,
    transcript: transcript?.textContent,
    citation: citation?.innerHTML,
    row: row?.innerHTML
  };
  const alternate = {
    title: '책갈피에 남은 기차는 어디로 가는가',
    transcript: '“기차표 대신 책갈피를 남긴 여행이 있습니다. 목적지를 기록하지 못했지만, 창밖이 천천히 밝아지던 시간만큼은 또렷하게 남아 있습니다.”',
    citation: '<span>출처 05</span> 합성 책 밑줄 · 「창가의 이동 기록」 · 날짜 미상',
    row: '<span>03</span><p><b>책갈피에 남은 기차</b><small>07:10–11:58</small></p>'
  };
  let toggled = false;

  function runPulse() {
    if (!listening || !title || !transcript || !citation || !row) return;
    listening.classList.remove('chapter-pulsing');
    void listening.offsetWidth;
    listening.classList.add('chapter-pulsing');
    toggled = !toggled;
    const content = toggled ? alternate : original;
    window.setTimeout(() => {
      title.textContent = content.title;
      transcript.textContent = content.transcript;
      citation.innerHTML = content.citation;
      row.innerHTML = content.row;
    }, window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 260);
    window.setTimeout(() => listening.classList.remove('chapter-pulsing'), 740);
  }

  pulseTrigger?.addEventListener('click', runPulse);
  document.querySelector('.play-orbit')?.addEventListener('click', (event) => {
    const pressed = event.currentTarget.getAttribute('aria-pressed') === 'true';
    event.currentTarget.setAttribute('aria-pressed', String(!pressed));
    event.currentTarget.textContent = pressed ? '▶' : 'Ⅱ';
  });

  installGuideLink();
  window.__PAC_REVIEW__ = { showState, runPulse, states: [...allowed] };
  showState(initial, false);
})();
