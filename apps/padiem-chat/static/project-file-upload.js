// 1GB 통일 1단계 → 3단계 — 프로젝트 파일 조각 업로드(tus 1.0.0).
//
// 진행률·자동 이어 올리기·한국어 안내는 공용 화면 모듈(static/tus-upload.js)이
// 한 곳에서 맡는다. 이 파일은 프로젝트 파일 레인만의 것을 갖는다: 엔드포인트,
// 그리고 "201 파일 응답"이라는 이 레인의 결과 모양 검증.
//
// 클라이언트 라이브러리: tus-js-client 4.3.1 (MIT) — static/tus-js-client-4.3.1.min.js,
// 라이선스 전문 static/tus-js-client-4.3.1.LICENSE.txt, 고지 static/third-party-licenses.html.
(function () {
  "use strict";

  var UPLOAD_FAILED = "업로드를 마치지 못했어요. 다시 시도해 주세요.";

  function collection(projectId) {
    return "/api/projects/" + encodeURIComponent(projectId) + "/files/tus";
  }

  function failure(message) {
    var error = new Error(message);
    error.uiMessageSafe = true;
    return error;
  }

  function uploadProjectFile(options) {
    var file = options && options.file;
    var projectId = options && options.projectId;
    var mediaType = options && options.mediaType;
    if (!file || !projectId || !mediaType) {
      return Promise.reject(failure("업로드 정보가 올바르지 않아요."));
    }
    if (!window.PadiemTusUpload) {
      return Promise.reject(failure("업로드 준비를 마치지 못했어요. 페이지를 새로 고침한 뒤 다시 시도해 주세요."));
    }
    return window.PadiemTusUpload.upload({
      file: file,
      endpoint: collection(projectId),
      mediaType: mediaType,
      onProgress: options.onProgress,
      onState: options.onState,
    }).then(function (data) {
      // The project lane answers 201 with the created file; nothing else is a
      // finished upload, so a different shape is a failure rather than success.
      if (!data || !data.file) throw failure(UPLOAD_FAILED);
      return data;
    });
  }

  window.PadiemProjectFileUpload = {
    upload: uploadProjectFile,
    limits: function (projectId) { return window.PadiemTusUpload.discover(collection(projectId)); },
  };
})();
