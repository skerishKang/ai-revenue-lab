(() => {
  "use strict";
  window.familyNewspaperStates = window.familyNewspaperStates || {};
  window.familyNewspaperStates.fold = String.raw`<section aria-labelledby="fold-title" class="state-panel" data-state-panel="fold" hidden="">
<div class="fold-review">
<header class="fold-review__header">
<div>
<p class="section-label">SIGNATURE MOTION · 680MS</p>
<h2 id="fold-title">Page Fold / 지면 넘김</h2>
</div>
<button class="fold-replay" type="button">지면 넘김 재생</button>
</header>
<div aria-live="polite" class="fold-stage">
<div class="fold-rail">
<strong>우리 가족 신문</strong>
<span id="fold-location">1면 → 가족 소식면</span>
</div>
<div aria-hidden="true" class="fold-sheet fold-sheet--inside">
<p class="fold-sheet__edition">제18호 · 2면</p>
<h3>가족 소식면</h3>
<div class="fold-inside-grid">
<article><span>01</span><strong>새벽 산책길에서 첫 매미 소리를 들었다</strong></article>
<article><span>02</span><strong>마지막 아이스크림을 네 조각으로 나눴다</strong></article>
<figure><img alt="합성 장보기 메모 일러스트" src="./assets/images/kitchen-note.svg"/></figure>
</div>
</div>
<div class="fold-sheet fold-sheet--front">
<p class="fold-sheet__edition">제18호 · 1면</p>
<h3>비가 그친 저녁,<br/>베란다 식탁이 열렸다</h3>
<figure><img alt="합성 베란다 식탁 일러스트" src="./assets/images/lead-balcony-table.svg"/></figure>
<p>한 장을 넘겨도 제호와 현재 위치가 남아, 읽는 사람이 어느 호의 어느 면인지 잃지 않습니다.</p>
</div>
</div>
<p class="fold-review__note">모션 감소 설정에서는 이동 없이 안쪽 면으로 즉시 전환됩니다.</p>
</div>
</section>`;
})();
