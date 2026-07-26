(() => {
  const parts = window.WorldFeedViewMarkup = window.WorldFeedViewMarkup || [];
  parts.push(String.raw`      <section class="route-view" id="view-empty" data-route-view="empty" aria-labelledby="empty-title" hidden>
        <div class="state-surface recovery-layout"><div class="state-art" aria-hidden="true"><div><strong>0</strong><span>FILTERED STORIES</span></div></div><div class="state-card state-empty">
        <p class="eyebrow">FILTERED VIEW</p><h1 id="empty-title">이 조건에 맞는<br>이야기가 없습니다</h1><p>현재 합성 피드에는 <strong>‘심야 산책 · 광주’</strong> 조건을 동시에 만족하는 이야기가 없습니다. 피드가 고장 난 것은 아닙니다.</p><div class="state-fact">
        <span>적용한 조건</span><strong>심야 산책 · 광주</strong></div><div class="state-actions"><button id="clear-empty" type="button" class="solid-button" data-clear-empty>조건 해제하고 전체 피드 보기</button>
        <button type="button" class="outline-button" data-reset-all>전체 초기화</button></div></div></div>
      </section>

      <section class="route-view" id="view-error" data-route-view="error" aria-labelledby="error-title" hidden>
        <div class="state-surface recovery-layout" data-async-state="ready"><div class="state-art" aria-hidden="true"><div><strong>!</strong><span>SYNTHETIC INTERRUPTION</span></div></div>
        <div class="state-card"><p class="eyebrow">FEED INTERRUPTED</p><h1 id="error-title">피드 순서를<br>마무리하지 못했습니다</h1><p>현재 시제품에서 재현하는 합성 오류입니다. 외부 서비스나 실제 기사 연결 문제를 뜻하지 않습니다.</p><div class="state-fact">
        <span>복구 방식</span><strong>한 번 다시 정리하면 정상 피드로 전환</strong></div><div class="state-actions"><button id="retry-feed" type="button" class="solid-button" data-retry-feed>다시 시도</button>
        <a class="outline-button" href="#feed" data-route-link="feed">나의 피드로 이동</a></div></div></div>
      </section>

`);
})();
