// 1GB 통일 1단계 — 프로젝트 파일 조각 업로드(tus 1.0.0).
// 클라이언트 라이브러리: tus-js-client 4.3.1 (MIT) — static/tus-js-client-4.3.1.min.js,
// 라이선스 전문 static/tus-js-client-4.3.1.LICENSE.txt, 고지 static/third-party-licenses.html.
// 전체 상한(1GiB)과 조각 상한(90MB)은 서버가 답하는 값(Tus-Max-Size·X-Padiem-Tus-Chunk-Max)을
// 그대로 따른다. 이 모듈은 상한 숫자를 따로 두지 않는다 — 설정이 어긋나지 않게.
//
// 화면 규칙(#2342): 이 모듈이 밖으로 던지는 오류는 전부 여기서 만든 1차 한국어 안내다.
// 서버 본문 메시지를 그대로 노출하지 않고, error.code 참조만 남긴다.
(function () {
  "use strict";

  var DEFAULT_CHUNK_BYTES = 16 * 1024 * 1024; // 90MB 서버 상한 안에서 재개 단위를 촘촘히.
  var CODE_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;
  var cachedLimits = null;

  function humanBytes(total) {
    var value = total;
    var units = ["B", "KB", "MB", "GB"];
    for (var i = 0; i < units.length; i += 1) {
      if (value < 1024 || i === units.length - 1) {
        return (i >= 2 ? Math.round(value * 10) / 10 : Math.round(value)) + units[i];
      }
      value /= 1024;
    }
    return total + "B";
  }

  function fetchLimits(projectId) {
    if (cachedLimits) return Promise.resolve(cachedLimits);
    return fetch("/api/projects/" + encodeURIComponent(projectId) + "/files/tus", {
      method: "OPTIONS",
      headers: { "Tus-Resumable": "1.0.0" },
      cache: "no-store",
    }).then(function (response) {
      if (!response.ok) throw new Error("업로드 한도를 확인하지 못했어요. 다시 시도해 주세요.");
      var maxSize = Number(response.headers.get("Tus-Max-Size"));
      var chunkMax = Number(response.headers.get("X-Padiem-Tus-Chunk-Max"));
      cachedLimits = {
        maxUploadBytes: Number.isFinite(maxSize) && maxSize > 0 ? maxSize : 0,
        chunkMaxBytes: Number.isFinite(chunkMax) && chunkMax > 0 ? chunkMax : 0,
      };
      return cachedLimits;
    }, function () {
      throw new Error("업로드 한도를 확인하지 못했어요. 다시 시도해 주세요.");
    });
  }

  function statusOf(error) {
    var response = error && error.originalResponse;
    if (response && typeof response.getStatus === "function") {
      var status = response.getStatus();
      return status >= 100 && status <= 599 ? status : 0;
    }
    return 0;
  }

  function errorCodeOf(error) {
    try {
      var response = error && error.originalResponse;
      if (response && typeof response.getBody === "function") {
        var body = response.getBody();
        if (typeof body === "string" && body) {
          var parsed = JSON.parse(body);
          var code = parsed && parsed.error && parsed.error.code;
          if (typeof code === "string" && CODE_PATTERN.test(code)) return code;
        }
      }
    } catch (ignore) {
      // 본문을 못 읽으면 코드 없이 안내만 내보낸다.
    }
    return null;
  }

  function messageFor(error) {
    var status = statusOf(error);
    return status === 413 ? "파일이 너무 커요 — 서버 한도를 넘었어요."
      : status === 401 ? "로그인이 필요해요. 로그인 후 다시 시도해 주세요."
      : (status === 403 || status === 404) ? "이 프로젝트에 파일을 올릴 권한이 없어요."
      : status === 415 || status === 422 ? "이 형식은 프로젝트 파일로 올릴 수 없어요."
      : "업로드가 끊겼어요. 네트워크를 확인하고 다시 시도해 주세요.";
  }

  function firstPartyFailure(error) {
    var failure = new Error(messageFor(error));
    failure.uiMessageSafe = true;
    var code = errorCodeOf(error);
    if (code) failure.code = code;
    return failure;
  }

  function pickupFailure(status, data) {
    var failure = new Error(
      status === 413 ? "파일이 너무 커요 — 서버 한도를 넘었어요."
        : status === 422 ? "이 형식은 프로젝트 파일로 올릴 수 없어요."
        : "업로드를 마치지 못했어요. 다시 시도해 주세요.");
    failure.uiMessageSafe = true;
    var code = data && data.error && typeof data.error.code === "string" && CODE_PATTERN.test(data.error.code)
      ? data.error.code : null;
    if (code) failure.code = code;
    return failure;
  }

  function uploadProjectFile(options) {
    var file = options.file;
    var projectId = options.projectId;
    var mediaType = options.mediaType;
    var onProgress = options.onProgress || function () {};
    if (!file || !projectId || !mediaType) {
      return Promise.reject(new Error("업로드 정보가 올바르지 않아요."));
    }
    return fetchLimits(projectId).then(function (limits) {
      if (limits.maxUploadBytes && file.size > limits.maxUploadBytes) {
        var tooBig = new Error(
          "파일이 너무 커요 — 최대 " + humanBytes(limits.maxUploadBytes) + "까지 올릴 수 있어요.");
        tooBig.uiMessageSafe = true;
        return Promise.reject(tooBig);
      }
      return new Promise(function (resolve, reject) {
        var upload = new tus.Upload(file, {
          endpoint: "/api/projects/" + encodeURIComponent(projectId) + "/files/tus",
          chunkSize: DEFAULT_CHUNK_BYTES,
          retryDelays: [0, 1000, 3000, 5000, 10000],
          // tus-js-client가 메타데이터 값을 자체적으로 base64로 감싸 보낸다(UTF-8 안전).
          // 여기서는 날값만 넘긴다 — 이중으로 인코딩하면 서버가 파일 이름을 못 알아듣는다.
          uploadMetadata: {
            filename: file.name,
            filetype: mediaType,
          },
          headers: { "Accept": "application/json" },
          onProgress: function (sent, total) { onProgress(sent, total); },
          // 끊김(응답 없음)·서버 오류(5xx)만 자동 이어 올리기. 4xx는 다시 보내도 같은 답이므로
          // 즉시 한국어 안내로 넘긴다.
          onShouldRetry: function (error) {
            var status = statusOf(error);
            return status === 0 || status >= 500 || status === 423;
          },
          onError: function (error) {
            reject(firstPartyFailure(error));
          },
          onSuccess: function () {
            // 마지막 PATCH는 204로 끝난다(tus 규격). 저장 결과(201 파일/4xx 오류)는
            // 한 번만 꺼내 쓴다 — GET이 결과를 돌려주고 서버가 임시 조각을 치운다.
            fetch(upload.url, { headers: { "Accept": "application/json" }, cache: "no-store" })
              .then(function (response) {
                return response.json().catch(function () { return null; }).then(function (data) {
                  if (!response.ok || !data || !data.file) {
                    throw pickupFailure(response.status, data);
                  }
                  resolve(data);
                });
              })
              .catch(function (error) {
                reject(error && error.uiMessageSafe ? error : (function () {
                  var failure = new Error("업로드 결과를 확인하지 못했어요. 다시 시도해 주세요.");
                  failure.uiMessageSafe = true;
                  return failure;
                })());
              });
          },
        });
        upload.start();
      });
    });
  }

  window.PadiemProjectFileUpload = {
    upload: uploadProjectFile,
    limits: fetchLimits,
  };
})();
