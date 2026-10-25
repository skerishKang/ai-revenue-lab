/*
 * #5786 의원 블로그 래퍼의 테마 부팅.
 *
 * ../theme-init.js 는 ?theme= 이 없으면 padiem-glass 를 기본으로 잡습니다.
 * 대표 결정(2026-10-25)은 이 페이지의 기본을 Light 로 두는 것이므로, 이 파일을
 * theme-init.js 보다 먼저 실행해 값이 없는 경우만 light 로 채웁니다. 테마 해석과
 * 메타 갱신은 기존 theme-init.js 가 그대로 담당하므로 로직을 복제하지 않습니다.
 */
(function () {
  "use strict";
  try {
    var params = new URLSearchParams(window.location.search);
    var allowed = ["light", "dark"];
    if (allowed.indexOf(params.get("theme")) === -1) {
      params.set("theme", "light");
      window.history.replaceState(window.history.state, "",
        window.location.pathname + "?" + params.toString() + (window.location.hash || ""));
    }
  } catch (_) { /* 해석 실패는 theme-init 기본값을 따른다 */ }
})();
