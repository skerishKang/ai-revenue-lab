(() => {
  const parts = window.WorldFeedViewMarkup = window.WorldFeedViewMarkup || [];
  parts.push(String.raw`      <section class="route-view" id="view-feed" data-route-view="feed" aria-labelledby="feed-title" hidden>
        <header class="journey-heading">
          <div><p class="eyebrow">PERSONAL WORLD DISPATCH</p><h1 id="feed-title">나의 피드</h1><p>세계와 가까운 곳의 이야기를 한 사람의 관심 순서로 가볍게 엮었습니다.</p></div>
          <div class="filter-summary"><span>현재 보기</span><strong data-current-filter-label>나의 피드</strong><div class="filter-links"><button type="button" data-state-route="empty">심야 산책만 보기</button>
          <button type="button" data-reset-filter>보기 초기화</button></div></div>
        </header>

        <div class="feed-variant" data-feed-variant="default">
          <div class="home-grid">
            <article class="lead-story">
              <div class="lead-image-wrap"><img class="lead-image" src="./assets/images/hero-harbor.svg" alt="해질녘 항구 도시를 표현한 합성 편집 일러스트"><div class="signal signal-world">세계 · 해안 도시</div>
              <div class="image-index" aria-hidden="true">01 / 07</div></div>
              <div class="lead-copy"><p class="eyebrow">오늘의 첫 장면</p><h2 class="feed-lead-title"><span>낯선 항구의 저녁이</span><span>오늘의 첫 장면이 된 이유</span></h2>
              <p class="dek">바다와 도시가 맞닿는 산책로와 늦게 문을 여는 작은 식당. 여행 계획이 아니라 지금 보고 싶은 세계의 질감을 짧게 모았습니다.</p><div class="story-source"><span>Atlas Letter</span><time>과거 합성 기록 · 4분</time></div><div class="lead-actions">
              <button id="open-harbor-story" type="button" class="text-button" data-open-story data-story-id="harbor">이야기 열기 <span aria-hidden="true">↗</span></button></div></div>
            </article>
            <aside class="dispatch-rail" aria-label="오늘의 편집 신호">
              <div class="rail-heading"><span>YOUR SIGNALS</span><span>03</span></div>
              <article class="signal-note local-note"><span class="signal signal-nearby">가까운 곳 · 광주</span>
              <button id="open-market-studio-from-feed" type="button" class="card-button" data-open-story data-story-id="market-studio"><h2>시장 골목의 빈 점포가 저녁 공방으로 바뀌는 중</h2></button>
              <p>책 수선, 도자기, 작은 공연이 한 골목에 모이는 합성 지역 기록.</p><div class="story-source"><span>Local Field Notes</span><time>합성 · 6일 전</time></div></article>
              <article class="signal-note image-note"><img src="./assets/images/neighborhood-bookshop.svg" alt="골목 서점의 저녁을 표현한 합성 일러스트"><div><span class="signal signal-personal">나의 관심 · 영화와 장소</span>
              <h2>영화를 고르는 대신, 동네 극장을 고르는 사람들</h2><div class="story-source"><span>Small Screen Journal</span><time>합성 · 12일 전</time></div></div></article>
            </aside>
          </div>
          <div class="section-rule"><span>오늘의 발견 05</span><span>세계 / 가까운 곳 / 나의 관심</span></div>
          <div class="feed-mosaic">
            <article class="portrait-post"><img src="./assets/images/night-market.svg" alt="밤 시장 합성 일러스트"><span class="signal signal-world">세계 · 시장</span><h2>자정 이후에 시작되는 시장의 색</h2>
            <p>간판보다 천막과 조명이 먼저 기억되는 도시 풍경.</p></article>
            <article class="text-post"><span class="post-number">02</span><span class="signal signal-personal">나의 관심 · 공예</span><h2>완성된 그릇보다 손의 속도를 보는 전시</h2><p>실패한 형태와 제작 흔적까지 한 테이블에 놓는 가상의 공예전 이야기.</p>
            </article>
            <article class="wide-post"><img src="./assets/images/sea-train.svg" alt="바닷가를 달리는 작은 기차 합성 일러스트"><div><span class="signal signal-world">세계 · 장소</span><h2>창문을 열면 바다가 먼저 들어오는 느린 열차</h2>
            <p>목적지보다 이동 장면이 오래 남는 해안선 발견.</p></div></article>
            <article class="maker-post"><img src="./assets/images/maker-studio.svg" alt="저녁 공방 합성 일러스트"><div><span class="signal signal-nearby">가까운 곳 · 작업실</span>
            <button id="open-maker-from-mosaic" type="button" class="card-button" data-open-story data-story-id="maker"><h2>문 닫은 가게 안에서 다시 켜진 작업등</h2></button><div class="story-source">
            <span>Local Field Notes</span><time>합성 · 과거 기록</time></div></div></article>
            <article class="sports-post"><img src="./assets/images/stadium-culture.svg" alt="지역 경기장 응원 문화 합성 일러스트"><div><span class="signal signal-nearby">스포츠 문화 · 지역 공동체</span><h2>경기보다 먼저 시작되는 동네의 합창</h2>
            <p>점수나 예측이 아니라 경기장 주변의 상점과 응원 노래가 만드는 지역 문화 기록.</p></div></article>
          </div>
        </div>

        <div class="feed-variant adjusted-feed" data-feed-variant="nearby" hidden>
          <div class="home-grid">
            <article class="lead-story nearby-lead"><div class="lead-image-wrap"><img class="lead-image" src="./assets/images/maker-studio.svg" alt="저녁 공방 합성 일러스트">
            <div class="signal signal-nearby">가까운 곳 · 작업실</div><div class="image-index" aria-hidden="true">동네 우선</div></div><div class="lead-copy"><p class="eyebrow">PREFERENCE UPDATED</p>
            <h2 class="feed-lead-title"><span>시장 골목의 작업등이</span><span>피드의 첫 장면이 됐습니다</span></h2><p class="dek">‘동네 소식 더 보기’ 반응을 반영해 가까운 장소와 생활 이야기를 앞쪽으로 옮겼습니다. 이 변화는 현재 브라우저 메모리에만 있습니다.</p>
            <div class="story-source"><span>Local Field Notes</span><time>합성 · 6일 전</time></div><div class="lead-actions">
            <button id="open-maker-adjusted" type="button" class="text-button" data-open-story data-story-id="maker">이야기 다시 열기</button>
            <button type="button" class="text-button muted" data-undo-preference>실행 취소</button></div></div></article>
            <aside class="dispatch-rail"><div class="rail-heading"><span>CHANGED ORDER</span><span>01</span></div><article class="signal-note image-note">
            <img src="./assets/images/neighborhood-bookshop.svg" alt="골목 서점 합성 일러스트"><div><span class="signal signal-nearby">가까운 곳 · 서점</span><h2>극장 옆 골목 서점의 늦은 불빛</h2><div class="story-source">
            <span>Neighborhood Screen</span><time>합성 · 8일 전</time></div></div></article><article class="signal-note"><span class="signal signal-world">세계 · 해안 도시</span><h2>항구의 저녁은 두 번째 묶음으로 이동했습니다</h2></article>
            </aside>
          </div>
          <div class="section-rule"><span>변경된 발견 순서</span><span>가까운 곳 / 나의 관심 / 세계</span></div>
          <div class="feed-mosaic"><article class="portrait-post"><img src="./assets/images/neighborhood-bookshop.svg" alt="골목 서점 합성 일러스트"><span class="signal signal-nearby">가까운 곳 · 서점</span>
          <h2>극장 옆 골목 서점의 늦은 불빛</h2></article><article class="text-post"><span class="post-number">02</span><span class="signal signal-nearby">가까운 곳 · 시장</span><h2>낮에는 시장, 저녁에는 작업실이 되는 통로</h2></article>
          <article class="wide-post"><img src="./assets/images/small-cinema.svg" alt="동네 소극장 합성 일러스트"><div><span class="signal signal-personal">나의 관심 · 영화와 장소</span><h2>상영 시간표보다 동네의 밤을 바꾸는 극장</h2></div>
          </article></div>
        </div>
      </section>

`);
})();
