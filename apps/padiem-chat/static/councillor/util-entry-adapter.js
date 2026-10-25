/*
 * #5786 의원 블로그 래퍼용 진입 어댑터 (내비게이션 1줄 분량).
 *
 * 유틸 화면의 소유권은 util-menu.js 에 그대로 두고, 목적지 프래그먼트만
 * 사이드바와 같은 클릭으로 바꿔 줍니다. 기존 #padiem-automation ·
 * #padiem-claw 라우트와 같은 계약이며, 화면·생성·저장 코드나 스타일을
 * 복제하지 않습니다.
 *
 * index.html 에서 util-menu.js 뒤쪽(defer 순서)에 로드됩니다. util-menu.js 는
 * 실행 시점에 리스너를 붙이므로, 이 어댑터의 click() 은 그 뒤에만 동작합니다.
 */
(() => {
  "use strict";

  const ROUTE = "#padiem-util";
  const TOOLS = { speech: 1, sns: 1, meeting: 1, pdfmd: 1 };

  function apply() {
    const raw = String(window.location.hash || "");
    if (raw !== ROUTE && !raw.startsWith(ROUTE + "/")) return;
    const nav = document.getElementById("utilNavButton");
    if (!nav) return;
    // util-menu.js 의 showUtil() 이 shell 상태를 열고 다른 뷰는 CSS 로 가려집니다.
    nav.click();

    const tool = raw.slice(ROUTE.length + 1).split("?")[0].split("/")[0];
    if (!tool || !Object.prototype.hasOwnProperty.call(TOOLS, tool)) return;
    const tab = document.querySelector('.util-tab[data-util="' + tool + '"]');
    if (tab) tab.click(); // 패널 전환과 lazy build(sns/meeting/pdfmd)도 원본이 처리
  }

  function start() { apply(); }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
  window.addEventListener("hashchange", apply);
})();
