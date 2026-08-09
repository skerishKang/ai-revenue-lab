(() => {
  const parts = window.WorldFeedViewMarkup = window.WorldFeedViewMarkup || [];
  parts.push(String.raw`      <section class="route-view" id="view-story-unavailable" data-route-view="story-unavailable" aria-labelledby="story-unavailable-title" hidden>
        <div class="state-surface recovery-layout"><div class="state-art" aria-hidden="true"><div><strong>—</strong><span>STORY UNAVAILABLE</span></div></div><div class="state-card state-unavailable">
        <p class="eyebrow">STORY STATUS</p><h1 id="story-unavailable-title">이 이야기는 지금<br>표시할 수 없습니다</h1><p>선택한 이야기의 identity와 이전 탐색 위치는 그대로 보존했습니다. 다른 이야기를 대신 열지 않습니다.</p><div class="state-fact">
        <span>선택했던 이야기</span><strong data-unavailable-story-title>문 닫은 가게 안에서 다시 켜진 작업등</strong></div><div class="story-source"><span data-unavailable-source>Local Field Notes</span>
        <time data-unavailable-time>과거 합성 기록 · 6일 전</time></div><div class="state-actions"><button type="button" class="solid-button" data-return-context>이전 탐색으로 돌아가기</button>
        <a class="outline-button" href="#feed" data-route-link="feed">다른 이야기 보기</a></div></div></div>
      </section>

      <section class="route-view" id="view-source-unavailable" data-route-view="source-unavailable" aria-labelledby="source-unavailable-title" hidden>
        <div class="state-surface recovery-layout"><div class="state-art" aria-hidden="true"><div><strong>∅</strong><span>SOURCE UNAVAILABLE</span></div></div><div class="state-card state-unavailable">
        <p class="eyebrow">SOURCE STATUS</p><h1 id="source-unavailable-title">열 수 있는 실제 원문이<br>연결되어 있지 않습니다</h1><p>이 시제품은 외부 원문을 열지 않습니다. 선택한 합성 이야기와 출처 이름은 그대로 유지하며, 잘못된 링크나 다른 story를 대신 제공하지 않습니다.</p>
        <div class="state-fact"><span>현재 이야기</span><strong data-unavailable-story-title>문 닫은 가게 안에서 다시 켜진 작업등</strong></div><div class="story-source"><span data-unavailable-source>Local Field Notes</span>
        <time data-unavailable-time>과거 합성 기록 · 6일 전</time></div><div class="state-actions"><button type="button" class="solid-button" data-return-story>이야기로 돌아가기</button>
        <button type="button" class="outline-button" data-return-context>이전 탐색으로 돌아가기</button></div></div></div>
      </section>
    </main>

    <details class="prototype-state-panel">
      <summary>UX 상태 점검 · 결정적으로 재현 가능한 합성 상태</summary>
      <nav class="prototype-state-links" aria-label="UX Slice 2 상태 점검">
        <a href="#loading" data-state-route="loading">Loading</a>
        <a href="#empty" data-state-route="empty">결과 없음</a>
        <a href="#error" data-state-route="error">오류·Retry</a>
        <a href="#story-unavailable" data-state-route="story-unavailable">Story unavailable</a>
        <a href="#source-unavailable" data-state-route="source-unavailable">Source unavailable</a>
      </nav>
    </details>

    <footer class="site-footer"><p><strong>합성 콘텐츠와 인메모리 상태로 검증하는 Phase 2 UX Slice 2입니다.</strong></p><p>Backend / API / persistence excluded</p></footer>
  </div>

  <dialog id="source-dialog" class="source-dialog" aria-labelledby="source-dialog-title"><form method="dialog"><p class="eyebrow">SYNTHETIC SOURCE ACTION</p>
  <h2 id="source-dialog-title">실제 원문은 열리지 않습니다</h2><p>이 시제품은 외부 기사나 사이트로 요청을 보내지 않습니다. 출처 이름과 상태를 확인하는 동작만 검증합니다.</p><button type="submit" class="solid-button">확인</button></form></dialog>
  <p class="sr-live" role="status" aria-live="polite" aria-atomic="true" data-live-region></p>
`);
})();
