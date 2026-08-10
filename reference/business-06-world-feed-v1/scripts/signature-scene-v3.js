(() => {
  'use strict';

  const feedView = document.getElementById('view-feed');
  const defaultFeed = feedView && feedView.querySelector('[data-feed-variant="default"]');
  if (!feedView || !defaultFeed || feedView.querySelector('.wf-signal-stage')) return;

  const stage = document.createElement('section');
  stage.className = 'wf-signal-stage';
  stage.dataset.stageStep = '0';
  stage.setAttribute('aria-labelledby', 'wf-stage-title');
  stage.innerHTML = `
    <p class="wf-stage-kicker">LIVE EDITORIAL SIGNAL · SYNTHETIC DEMO</p>
    <div class="wf-stage-field" aria-label="세계와 가까운 곳의 편집 신호가 개인 브리프로 모이는 장면">
      <i class="wf-stage-axis" aria-hidden="true"></i>
      <i class="wf-stage-axis wf-stage-axis--b" aria-hidden="true"></i>
      <article class="wf-source-node" data-source="world"><b>01 / WORLD</b><span>해안 도시 · 장소의 질감</span></article>
      <article class="wf-source-node" data-source="near"><b>02 / NEAR</b><span>광주 · 시장 골목의 변화</span></article>
      <article class="wf-source-node" data-source="interest"><b>03 / INTEREST</b><span>영화 · 작은 극장과 장소</span></article>
      <article class="wf-source-node" data-source="culture"><b>04 / CULTURE</b><span>공예 · 작업실의 늦은 불빛</span></article>
      <i class="wf-pulse wf-pulse--1" aria-hidden="true"></i>
      <i class="wf-pulse wf-pulse--2" aria-hidden="true"></i>
      <i class="wf-pulse wf-pulse--3" aria-hidden="true"></i>
      <i class="wf-pulse wf-pulse--4" aria-hidden="true"></i>
      <div class="wf-stage-core" aria-hidden="true">
        <div class="wf-stage-core-label"><small>PERSONAL EDITOR</small><strong>WORLD<br>FEED</strong><em>4 SIGNALS IN</em></div>
      </div>
      <div class="wf-stage-caption">
        <h2 id="wf-stage-title">THE WORLD<br>FINDS YOU.</h2>
        <p>많은 소식을 늘어놓지 않습니다. 세계와 가까운 곳에서 들어온 신호를 읽고, 당신이 오늘 볼 한 장면으로 편집합니다.</p>
      </div>
    </div>
    <aside class="wf-stage-console" aria-label="개인 브리프 편집 과정">
      <div class="wf-stage-clock"><span>SEOUL EDITION · SYNTHETIC</span><strong>NOW EDITING</strong></div>
      <div class="wf-stage-pipeline" aria-label="Source Extract Verify Brief"><span>SOURCE</span><span>EXTRACT</span><span>VERIFY</span><span>BRIEF</span></div>
      <div class="wf-stage-readout">
        <span>INCOMING SIGNALS</span><strong>04</strong>
        <span>EDITABLE FACT CLUSTERS</span><strong>03</strong>
        <span>PERSONAL PRIORITY</span><b>PLACE / CULTURE</b>
      </div>
      <div class="wf-stage-brief">
        <h3>낯선 항구의 저녁이<br>오늘의 첫 장면이 된 이유</h3>
        <p>여행 계획이 아니라 지금 보고 싶은 세계의 질감. 장소와 문화 신호를 한 사람의 관심 순서로 짧게 엮었습니다.</p>
        <button type="button" class="text-button" data-open-story data-story-id="harbor">오늘의 브리프 열기 <span aria-hidden="true">↗</span></button>
      </div>
      <div class="wf-stage-controls">
        <span class="wf-stage-status" aria-live="polite">SIGNAL FIELD READY</span>
        <button type="button" class="wf-stage-replay">REPLAY SIGNAL</button>
      </div>
    </aside>`;

  defaultFeed.insertBefore(stage, defaultFeed.firstChild);

  const status = stage.querySelector('.wf-stage-status');
  const replay = stage.querySelector('.wf-stage-replay');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const labels = ['SIGNAL FIELD READY', 'SOURCE / 04 RECEIVED', 'EXTRACT / 03 CLUSTERS', 'VERIFY / SYNTHETIC', 'BRIEF / PERSONAL EDITION'];
  let timers = [];
  let played = false;

  function clearTimers() {
    timers.forEach((timer) => window.clearTimeout(timer));
    timers = [];
  }

  function setStep(step) {
    stage.dataset.stageStep = String(step);
    if (status) status.textContent = labels[step] || labels[0];
  }

  function play() {
    clearTimers();
    setStep(reducedMotion ? 4 : 0);
    if (reducedMotion) return;
    [1, 2, 3, 4].forEach((step, index) => {
      timers.push(window.setTimeout(() => setStep(step), 520 + (index * 1050)));
    });
  }

  if (replay) replay.addEventListener('click', play);

  if ('IntersectionObserver' in window && !reducedMotion) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting && !played) {
          played = true;
          play();
          observer.disconnect();
        }
      });
    }, { threshold: 0.28 });
    observer.observe(stage);
  } else {
    played = true;
    play();
  }
})();
