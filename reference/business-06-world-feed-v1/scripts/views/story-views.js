(() => {
  const parts = window.WorldFeedViewMarkup = window.WorldFeedViewMarkup || [];
  parts.push(String.raw`      <section class="route-view" id="view-story" data-route-view="story" aria-labelledby="story-title" hidden>
        <div class="story-detail"><button type="button" class="back-link" data-return-context>← 이전 피드로 돌아가기</button><div class="story-kicker">
        <span class="signal signal-nearby" data-story-signal>가까운 곳 · 시장 골목</span><span>짧은 이야기</span></div><h1 id="story-title" class="balanced-title" data-story-title><span>문 닫은 가게 안에서</span>
        <span>다시 켜진 작업등</span></h1><p class="story-intro" data-story-intro>이 화면은 원문을 대신하지 않습니다. World Feed가 이 장면을 발견한 맥락과 출처 상태만 짧게 보여줍니다.</p><figure class="story-figure">
        <img src="./assets/images/maker-studio.svg" alt="저녁 공방 합성 일러스트" data-story-image><figcaption data-story-caption>현재 사실을 나타내지 않는 UX 검토용 합성 장면.</figcaption></figure><div class="story-body-grid">
        <div class="story-body"><p class="dropcap" data-story-body-one>시장 문이 닫힌 뒤에도 한 점포의 작업등은 늦게까지 켜져 있습니다.</p><p data-story-body-two>이 편집면이 주목한 것은 동네 공간이 시간에 따라 다르게 쓰이는 장면입니다.</p>
        <div class="story-inline-actions"><button type="button" class="solid-button" data-route-link="why">왜 나에게 보였나요?</button>
        <a class="outline-button related-link" href="#culture" data-route-link="culture">관련 장소 더 보기</a></div></div><aside class="source-card" aria-label="출처 정보"><p class="eyebrow">SOURCE FORWARD</p>
        <h2 data-story-source>Local Field Notes</h2><dl><div><dt>형식</dt><dd data-story-format>합성 지역 관찰 메모</dd></div><div><dt>상태</dt><dd data-story-status>UX 검토용 가상 출처</dd></div><div><dt>기록 시점</dt>
        <dd data-story-time>과거 합성 기록 · 6일 전</dd></div><div><dt>편집 범위</dt><dd data-story-scope>장소 맥락 2문단</dd></div></dl><button type="button" class="source-button" data-source-action>원문 열기</button></aside>
        </div></div>
      </section>

      <section class="route-view" id="view-why" data-route-view="why" aria-labelledby="why-title" hidden>
        <div class="why-layout"><div class="why-story-preview"><img src="./assets/images/maker-studio.svg" alt="저녁 공방 합성 일러스트" data-why-image>
        <span class="signal signal-nearby" data-why-signal>가까운 곳 · 작업실</span><h2 data-why-story-title>문 닫은 가게 안에서 다시 켜진 작업등</h2><div class="story-source"><span data-why-source>Local Field Notes</span>
        <time data-why-time>합성 · 6일 전</time></div></div><div class="why-panel"><button type="button" class="back-link why-back" data-route-link="story">← 이야기로 돌아가기</button>
        <p class="eyebrow">WHY THIS APPEARED</p><h1 id="why-title">왜 나에게 보였나요?</h1><p class="why-lead" data-why-lead>최근에 본 이야기 가운데 ‘가까운 공간의 변화’와 ‘만드는 과정’이 자주 겹쳤기 때문입니다.</p><ol class="reason-list"><li>
        <span>01</span><div><strong data-reason-title="0">저장해 둔 관심</strong><p data-reason-text="0">공예, 수선, 작은 작업실 이야기를 여러 번 선택했습니다.</p></div></li><li><span>02</span><div>
        <strong data-reason-title="1">가까운 장소 선호</strong><p data-reason-text="1">멀리 있는 명소보다 동네 공간의 변화에 오래 머물렀습니다.</p></div></li><li><span>03</span><div><strong data-reason-title="2">최근 반응</strong>
        <p data-reason-text="2">짧은 장소 기록을 연달아 열어본 현재 세션의 선택이 반영됐습니다.</p></div></li></ol><p class="plain-note">점수, 가중치, 모델 내부 계산은 표시하지 않습니다. 이 설명은 현재 브라우저에서만 작동하는 합성 UX입니다.</p><div class="why-actions">
        <button type="button" class="solid-button" data-route-link="preferences">동네 소식 더 보기</button><button type="button" class="outline-button" data-return-context>이전 피드로 돌아가기</button></div></div></div>
      </section>

`);
})();
