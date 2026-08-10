(() => {
  'use strict';

  const feedView = document.getElementById('view-feed');
  const defaultFeed = feedView && feedView.querySelector('[data-feed-variant="default"]');
  if (!feedView || !defaultFeed || feedView.querySelector('.wf-cinema-v4')) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const stage = document.createElement('section');
  stage.className = 'wf-cinema-v4';
  stage.dataset.scene = reducedMotion ? '2' : '0';
  stage.dataset.motion = reducedMotion ? 'reduced' : 'full';
  stage.setAttribute('aria-labelledby', 'wf-v4-title');
  stage.innerHTML = `
    <section class="wf-v4-entry" aria-label="World Feed 소개">
      <img class="wf-v4-entry-photo" src="https://images.unsplash.com/photo-1636649148027-5a18656382e7?auto=format&fit=crop&w=2200&q=82" alt="비에 젖은 야간 도심의 횡단보도와 불빛" fetchpriority="high">
      <div class="wf-v4-entry-shade" aria-hidden="true"></div>
      <div class="wf-v4-entry-meta">
        <span>WORLD FEED</span>
        <span>PERSONAL EDITION · SYNTHETIC DEMO</span>
      </div>
      <div class="wf-v4-entry-copy">
        <p class="wf-v4-kicker">THE WORLD, EDITED FOR YOU</p>
        <h1 id="wf-v4-title"><span>전 세계 소식 중</span><span>내가 볼 것만 골라,</span><span>오늘의 한 편으로.</span></h1>
        <p class="wf-v4-promise">관심사와 가까운 세계·지역·문화 신호를 골라 <strong>왜 나와 연결되는지 설명하고</strong>, 매일 하나의 개인 브리프로 편집합니다.</p>
        <div class="wf-v4-entry-actions">
          <button type="button" class="wf-v4-primary" data-v4-jump-scenes>오늘의 편집 과정 보기 <span aria-hidden="true">↓</span></button>
          <span class="wf-v4-outcome">고르기 · 연결 이유 · 개인 브리프</span>
        </div>
      </div>
      <p class="wf-v4-photo-credit">VISUAL · GIANPAOLO ANTONUCCI / UNSPLASH</p>
      <div class="wf-v4-scroll-cue" aria-hidden="true"><span>SCROLL TO EDIT</span><i></i></div>
    </section>

    <section class="wf-v4-scenes" aria-label="개인 브리프가 만들어지는 세 장면">
      <div class="wf-v4-sticky">
        <div class="wf-v4-scene-stack">
          <article class="wf-v4-scene" data-v4-scene="0">
            <img src="https://images.unsplash.com/photo-1534726972605-17962f8743d2?auto=format&fit=crop&w=2200&q=82" alt="야간 도심 골목의 사람들과 간판 불빛" loading="eager">
            <div class="wf-v4-scene-veil" aria-hidden="true"></div>
            <div class="wf-v4-scene-copy">
              <p><span>01</span> PLACE · WORLD</p>
              <h2>세계에서<br>장면을 발견합니다.</h2>
              <div class="wf-v4-scene-note"><strong>신호</strong><span>도시의 밤 · 보행 · 지역의 리듬</span></div>
            </div>
            <span class="wf-v4-scene-credit">LF.FRANCIZ / UNSPLASH · REPRESENTATIVE VISUAL</span>
          </article>

          <article class="wf-v4-scene" data-v4-scene="1">
            <img src="https://images.unsplash.com/photo-1648973174435-fc50d62a6198?auto=format&fit=crop&w=2200&q=82" alt="사람들이 오가는 야간 시장의 조명과 가게" loading="lazy">
            <div class="wf-v4-scene-veil" aria-hidden="true"></div>
            <div class="wf-v4-scene-copy">
              <p><span>02</span> CULTURE · LOCAL</p>
              <h2>당신의 관심과<br>가까운 것만 남깁니다.</h2>
              <div class="wf-v4-scene-note"><strong>관심</strong><span>시장 · 작은 가게 · 생활 문화</span></div>
            </div>
            <span class="wf-v4-scene-credit">ZACHARY KADOLPH / UNSPLASH · REPRESENTATIVE VISUAL</span>
          </article>

          <article class="wf-v4-scene" data-v4-scene="2">
            <img src="https://images.unsplash.com/photo-1646812965105-87821655690f?auto=format&fit=crop&w=2200&q=82" alt="한 사람이 걷는 조용한 야간 골목과 주황빛 가로등" loading="lazy">
            <div class="wf-v4-scene-veil" aria-hidden="true"></div>
            <div class="wf-v4-scene-copy">
              <p><span>03</span> WHY · PERSONAL</p>
              <h2>그리고 왜 지금<br>당신에게 맞는지 붙입니다.</h2>
              <div class="wf-v4-scene-note"><strong>연결 이유</strong><span>여행 계획보다 장소의 질감 · 영화보다 동네의 밤</span></div>
            </div>
            <span class="wf-v4-scene-credit">DYNAMIC WANG / UNSPLASH · REPRESENTATIVE VISUAL</span>
          </article>
        </div>

        <aside class="wf-v4-editorial-rail" aria-label="World Feed 편집 단계">
          <div class="wf-v4-rail-top"><span>WORLD FEED / 06</span><b>SYNTHETIC</b></div>
          <ol>
            <li data-v4-step="0"><span>01</span><strong>DISCOVER</strong><small>세계의 한 장면</small></li>
            <li data-v4-step="1"><span>02</span><strong>SELECT</strong><small>내 관심과 가까운 신호</small></li>
            <li data-v4-step="2"><span>03</span><strong>EXPLAIN</strong><small>왜 나와 연결되는지</small></li>
          </ol>
          <div class="wf-v4-progress"><i></i></div>
          <p>많이 보여주는 피드가 아니라<br><strong>오늘 볼 순서를 편집하는 피드.</strong></p>
        </aside>
      </div>
    </section>

    <section class="wf-v4-brief" aria-labelledby="wf-v4-brief-title">
      <div class="wf-v4-brief-photo">
        <img src="https://images.unsplash.com/photo-1768511813767-df4ade9ddca7?auto=format&fit=crop&w=2200&q=82" alt="사람들이 걷는 붉은 간판의 야간 거리" loading="lazy">
        <div aria-hidden="true"></div>
      </div>
      <div class="wf-v4-brief-copy">
        <p class="wf-v4-kicker">YOUR WORLD, EDITED</p>
        <div class="wf-v4-brief-index"><span>TODAY / 01</span><span>PLACE · CULTURE · LOCAL</span></div>
        <h2 id="wf-v4-brief-title">오늘 당신이<br>볼 한 장면</h2>
        <h3>낯선 항구의 저녁이<br>오늘의 첫 장면이 된 이유</h3>
        <p>여행 계획이 아니라 지금 보고 싶은 세계의 질감. 장소와 문화 신호를 당신의 관심 순서로 짧게 엮은 개인 브리프입니다.</p>
        <div class="wf-v4-brief-actions">
          <button type="button" class="wf-v4-primary" data-open-story data-story-id="harbor">오늘의 브리프 열기 <span aria-hidden="true">↗</span></button>
          <button type="button" class="wf-v4-replay" data-v4-replay>장면 다시 보기</button>
        </div>
        <small>합성 데모 콘텐츠 · 실제 뉴스·사건을 주장하지 않습니다.</small>
      </div>
    </section>

    <div class="wf-v4-workspace-marker" aria-hidden="true"><span>PRODUCT WORKSPACE</span><i></i><span>FEED · STORY · WHY · PREFERENCES</span></div>`;

  feedView.insertBefore(stage, feedView.firstChild);

  const scenes = stage.querySelector('.wf-v4-scenes');
  const rail = stage.querySelector('.wf-v4-editorial-rail');
  const progressBar = stage.querySelector('.wf-v4-progress i');
  const jumpButton = stage.querySelector('[data-v4-jump-scenes]');
  const replayButton = stage.querySelector('[data-v4-replay]');
  const sceneNodes = [...stage.querySelectorAll('[data-v4-scene]')];
  const stepNodes = [...stage.querySelectorAll('[data-v4-step]')];
  let currentScene = reducedMotion ? 2 : 0;
  let raf = 0;

  function applyScene(scene, progress = scene / 2) {
    currentScene = Math.max(0, Math.min(2, scene));
    stage.dataset.scene = String(currentScene);
    sceneNodes.forEach((node, index) => node.toggleAttribute('data-active', index === currentScene));
    stepNodes.forEach((node, index) => node.toggleAttribute('data-active', index <= currentScene));
    if (progressBar) progressBar.style.setProperty('--wf-v4-progress', `${Math.max(0, Math.min(1, progress)) * 100}%`);
    if (rail) rail.setAttribute('aria-label', `World Feed 편집 단계 ${currentScene + 1} / 3`);
  }

  function updateFromScroll() {
    raf = 0;
    if (reducedMotion || !scenes) return;
    const rect = scenes.getBoundingClientRect();
    const travel = Math.max(1, scenes.offsetHeight - window.innerHeight);
    const progress = Math.max(0, Math.min(1, -rect.top / travel));
    const scene = Math.min(2, Math.floor(progress * 3));
    applyScene(scene, progress);
  }

  function requestUpdate() {
    if (raf) return;
    raf = window.requestAnimationFrame(updateFromScroll);
  }

  function moveToScenes(replay = false) {
    if (!scenes) return;
    if (replay) applyScene(reducedMotion ? 2 : 0, reducedMotion ? 1 : 0);
    scenes.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' });
  }

  if (jumpButton) jumpButton.addEventListener('click', () => moveToScenes(false));
  if (replayButton) replayButton.addEventListener('click', () => moveToScenes(true));

  if (!reducedMotion) {
    window.addEventListener('scroll', requestUpdate, { passive: true });
    window.addEventListener('resize', requestUpdate, { passive: true });
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) stage.dataset.sceneReady = 'true';
      });
    }, { threshold: 0.12 });
    observer.observe(scenes);
    requestUpdate();
  } else {
    applyScene(2, 1);
  }
})();
