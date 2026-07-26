(() => {
  const parts = window.WorldFeedViewMarkup = window.WorldFeedViewMarkup || [];
  parts.push(String.raw`  <a class="skip-link" href="#main">본문으로 이동</a>
  <div class="review-shell" data-route="loading" data-preference="default" data-story-id="maker" data-ux-state="loading">
    <header class="masthead">
      <a class="brand" href="#feed" data-route-link="feed" aria-label="World Feed 나의 피드로 이동">
        <span class="brand-mark" aria-hidden="true">WF</span>
        <span><strong>World Feed</strong><small>나의 세계 편집면</small></span>
      </a>
      <p class="edition-note">SEOUL EDITION · SYNTHETIC / 2026.07</p>
      <div class="masthead-meta"><span>오늘의 시선</span><strong>낯선 도시의 저녁과<br>가까운 골목의 온도</strong></div>
      <span class="issue-tag">UX 시제품</span>
    </header>

    <nav class="product-nav" aria-label="World Feed 주요 탐색">
      <a href="#feed" data-route-link="feed">나의 피드</a>
      <a href="#nearby" data-route-link="nearby">가까운 동네</a>
      <a href="#culture" data-route-link="culture">장소와 문화</a>
      <button type="button" class="nav-reset" data-reset-all>전체 초기화</button>
    </nav>

    <div class="preference-banner" data-preference-banner hidden>
      <span><strong>동네 소식 더 보기</strong>가 적용되어 가까운 이야기가 먼저 보입니다.</span>
      <button type="button" data-undo-preference>실행 취소</button>
    </div>

    <main id="main" tabindex="-1">
      <section class="route-view" id="view-loading" data-route-view="loading" aria-labelledby="loading-title" aria-busy="true">
        <div class="state-surface" data-async-state="waiting" data-loading-state="waiting">
          <header class="state-heading">
            <p class="eyebrow">PERSONAL WORLD DISPATCH</p>
            <h1 id="loading-title">오늘의 편집면을<br>정리하고 있습니다</h1>
            <p>세계와 가까운 곳의 합성 이야기를 한 사람의 관심 순서로 놓는 중입니다. 실제 네트워크 요청은 발생하지 않습니다.</p>
          </header>
          <div class="loading-layout" aria-label="나의 피드 불러오는 중">
            <div class="loading-lead">
              <div class="loading-figure skeleton-block" aria-hidden="true"></div>
              <div class="loading-copy" aria-hidden="true"><span class="skeleton-line short"></span><span class="skeleton-line title"></span><span class="skeleton-line"></span><span class="skeleton-line short">
              </span></div>
            </div>
            <div class="loading-rail" aria-hidden="true">
              <div class="rail-heading"><span>YOUR SIGNALS</span><span>03</span></div>
              <div class="loading-card"><div class="skeleton-line short"></div><div class="skeleton-line"></div><div class="skeleton-line"></div></div>
              <div class="loading-card"><div class="skeleton-line short"></div><div class="skeleton-line"></div><div class="skeleton-line short"></div></div>
            </div>
          </div>
          <div class="state-actions"><button id="complete-loading" type="button" class="solid-button" data-complete-loading>정리된 피드 보기</button></div>
        </div>
      </section>

`);
})();
