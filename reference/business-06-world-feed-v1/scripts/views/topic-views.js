(() => {
  const parts = window.WorldFeedViewMarkup = window.WorldFeedViewMarkup || [];
  parts.push(String.raw`      <section class="route-view" id="view-nearby" data-route-view="nearby" aria-labelledby="nearby-title" hidden>
        <header class="topic-header"><div><p class="eyebrow">NEARBY STREAM / GWANGJU</p><h1 id="nearby-title">가까운 동네</h1><p>관광 명소보다 골목의 사용법과 저녁의 변화를 먼저 봅니다.</p></div><div class="topic-switch">
        <a class="chip is-selected" href="#nearby" data-route-link="nearby" aria-current="page">가까운 동네</a><a class="chip" href="#culture" data-route-link="culture">장소와 문화</a></div></header>
        <div class="topic-layout horizon-stage"><div class="topic-hero"><img class="lead-image" src="./assets/images/maker-studio.svg" alt="저녁 공방 합성 일러스트">
        <span class="vertical-word" aria-hidden="true">NEARBY</span></div><div class="topic-main-copy"><span class="signal signal-nearby">가까운 곳 · 시장 골목</span><h2><span>문 닫은 가게 안에서</span><span>다시 켜진 작업등</span>
        </h2><p>시장 안쪽의 작은 작업실에서 재료와 사람의 시간이 어떻게 겹치는지 보는 짧은 동네 기록입니다.</p><div class="story-source"><span>Local Field Notes</span><time>합성 · 6분</time></div>
        <button id="open-maker-from-nearby" type="button" class="solid-button stream-story-button" data-open-story data-story-id="maker">이 이야기 열기</button></div><div class="topic-stack">
        <article class="compact-post"><span class="post-number">A</span><div><span class="signal signal-nearby">가까운 곳 · 서점</span><h3>극장 옆 골목 서점의 늦은 불빛</h3></div></article><article class="compact-post">
        <span class="post-number">B</span><div><span class="signal signal-nearby">가까운 곳 · 시장</span><h3>낮에는 시장, 저녁에는 작업실이 되는 통로</h3></div></article><article class="compact-post">
        <span class="post-number">C</span><div><span class="signal signal-nearby">가까운 곳 · 산책</span><h3>저녁에만 열리는 작은 통로</h3></div></article></div></div>
      </section>

      <section class="route-view" id="view-culture" data-route-view="culture" aria-labelledby="culture-title" hidden>
        <header class="topic-header"><div><p class="eyebrow">CULTURE & PLACE STREAM</p><h1 id="culture-title">장소와 문화</h1><p>영화, 건축, 시장, 이동 장면을 장소의 기억으로 묶어 봅니다.</p></div><div class="topic-switch">
        <a class="chip" href="#nearby" data-route-link="nearby">가까운 동네</a><a class="chip is-selected" href="#culture" data-route-link="culture" aria-current="page">장소와 문화</a></div></header>
        <div class="topic-layout horizon-stage"><div class="topic-hero"><img class="lead-image" src="./assets/images/small-cinema.svg" alt="동네 소극장 합성 일러스트">
        <span class="vertical-word" aria-hidden="true">CULTURE</span></div><div class="topic-main-copy"><span class="signal signal-personal">나의 관심 · 영화와 장소</span><h2><span>상영 시간표보다</span>
        <span>동네의 밤을 바꾸는 극장</span></h2><p>한 편의 영화가 끝난 뒤에도 사람들이 흩어지지 않는 이유. 주변의 서점과 식당, 버스 정류장을 함께 보는 짧은 장소 기록입니다.</p><div class="story-source"><span>Neighborhood Screen</span><time>합성 · 7분</time></div>
        <button id="open-cinema-from-culture" type="button" class="outline-button stream-story-button" data-open-story data-story-id="cinema">이 극장 이야기 열기</button></div><div class="topic-stack">
        <article class="compact-post"><span class="post-number">A</span><div><span class="signal signal-world">세계 · 골목</span><h3>오래된 간판을 지우지 않는 새 가게들</h3></div></article><article class="compact-post">
        <span class="post-number">B</span><div><span class="signal signal-personal">나의 관심 · 공예</span><h3>완성품보다 만드는 시간을 보는 작업실</h3></div></article><article class="compact-post">
        <span class="post-number">C</span><div><span class="signal signal-world">세계 · 이동</span><h3>창문 하나로 기억되는 느린 열차</h3></div></article></div></div>
      </section>

`);
})();
