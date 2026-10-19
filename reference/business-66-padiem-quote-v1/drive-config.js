/* B66 — 내 Google Drive 런타임 설정 (#3871).
   이 파일은 배포 시점에 값이 주입되는 단일 지점이다.

   절대 규칙
   - 저장소에 실제 OAuth 클라이언트 ID/키 값을 커밋하지 않는다. 아래는 빈 기본값이다.
   - 값이 없으면 기능은 조용히 비활성되고, 기존 견적 작성·최근 견적·PDF 다운로드는 그대로 동작한다.
   - Google Drive 연결은 선택 사항이다. 고객에게 강제하지 않는다.

   주입 방법(운영 승인 후): 배포 산출물에서 이 파일의 기본값만 채운다.
     window.B66_DRIVE_CLIENT_ID          = "<owner-approved client id>.apps.googleusercontent.com"
     window.B66_DRIVE_PICKER_APP_ID      = "<project number>"        (Picker 사용 시에만)
     window.B66_DRIVE_PICKER_DEVELOPER_KEY = "<browser API key>"      (Picker 사용 시에만)

   승인된 JavaScript Origin 에 배포 오리진이 등록되어 있어야 한다.
   자세한 절차와 증거 요건은 docs/products/b66/GOOGLE_DRIVE_LIVE_VERIFICATION.md 를 따른다. */

(function (root) {
  "use strict";
  if (!root) return;

  function keepExisting(name) {
    if (typeof root[name] !== "string") root[name] = "";
  }

  keepExisting("B66_DRIVE_CLIENT_ID");
  keepExisting("B66_DRIVE_PICKER_APP_ID");
  keepExisting("B66_DRIVE_PICKER_DEVELOPER_KEY");
})(typeof self !== "undefined" ? self : this);
