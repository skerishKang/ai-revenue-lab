(() => {
  const parts = window.WorldFeedViewMarkup = window.WorldFeedViewMarkup || [];
  parts.push(String.raw`      <section class="route-view" id="view-preferences" data-route-view="preferences" aria-labelledby="preferences-title" hidden>
        <header class="adjusted-header"><div><p class="eyebrow">PREFERENCE FEEDBACK</p><h1 id="preferences-title"><span>동네 소식의 순서를</span><span>조금 더 앞쪽으로</span></h1></div>
        <p>현재 브라우저 메모리에서만 피드 순서를 바꿉니다. 계정이나 저장 기록은 만들지 않습니다.</p></header><div class="preference-status-card"><div><span>관련 선호</span><strong>가까운 동네 이야기</strong></div>
        <p data-preference-state-label>아직 변경하지 않았습니다.</p><div class="preference-actions"><button type="button" class="solid-button" data-apply-preference>동네 소식 더 보기 적용</button>
        <button type="button" class="outline-button" data-undo-preference disabled>실행 취소</button><button type="button" class="text-button muted" data-reset-all>전체 초기화</button></div></div>
        <div class="comparison-canvas" aria-label="피드 변경 전후 미리보기"><section class="comparison-panel before-panel"><div class="compare-label"><span>BEFORE</span><span>세계 이야기 우선</span></div>
        <div class="mini-feed"><article class="mini-lead"><img src="./assets/images/hero-harbor.svg" alt=""><div><span class="signal signal-world">세계</span><h2>항구의 저녁</h2></div></article><article>
        <span class="signal signal-nearby">가까운 곳</span><h3>시장 통로의 변화</h3></article></div></section><section class="comparison-panel after-panel" data-after-preview><div class="compare-label">
        <span>AFTER</span><span>동네 이야기 우선</span></div><div class="mini-feed"><article class="mini-lead"><img src="./assets/images/maker-studio.svg" alt=""><div><span class="signal signal-nearby">가까운 곳</span>
        <h2>시장 골목의 작업등</h2></div></article><article class="after-accent"><img src="./assets/images/neighborhood-bookshop.svg" alt=""><div><span class="signal signal-nearby">가까운 곳</span><h3>극장 옆 골목 서점</h3>
        </div></article></div></section></div><div class="preference-return"><button type="button" class="outline-button" data-return-context>이전 탐색으로 돌아가기</button></div>
      </section>

`);
})();
