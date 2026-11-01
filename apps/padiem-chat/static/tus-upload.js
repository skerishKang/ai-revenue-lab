// 1GB 통일 3단계 — 세 업로드 레인이 함께 쓰는 tus 1.0.0 화면 모듈.
//
// 프로토콜의 서버 정본은 app/tus_core.py 이고, 여기서는 **클라이언트 쪽 한 곳**만
// 만든다: 진행률(%), 끊기면 자동 이어 올리기, 1차 한국어 안내. 각 화면(프로젝트
// 파일·Chat 첨부·웹 XLSX)은 자기 엔드포인트·허용 형식·결과 검증만 갖는다 —
// 상한 숫자도, 재시도 규칙도, 문구 체계도 두 벌이 되지 않게.
//
// 클라이언트 라이브러리: tus-js-client 4.3.1 (MIT) — static/tus-js-client-4.3.1.min.js,
// 라이선스 전문 static/tus-js-client-4.3.1.LICENSE.txt, 고지 static/third-party-licenses.html.
//
// 화면 규칙(#2342): 이 모듈이 밖으로 던지는 오류는 전부 여기서 만든 1차 한국어
// 안내다. 서버 본문 메시지를 그대로 노출하지 않고 error.code 참조만 남긴다.
(function () {
  "use strict";

  var DEFAULT_CHUNK_BYTES = 16 * 1024 * 1024; // 90MB 서버 상한 안에서 재개 단위를 촘촘히.
  var CODE_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;
  var limitsCache = Object.create(null);

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

  function safeError(message, code) {
    var error = new Error(message);
    error.uiMessageSafe = true;
    if (typeof code === "string" && CODE_PATTERN.test(code)) error.code = code;
    return error;
  }

  function percentOf(sent, total) {
    if (!Number.isFinite(total) || total <= 0) return 0;
    return Math.max(0, Math.min(100, Math.round((sent / total) * 100)));
  }

  function statusOf(error) {
    var response = error && error.originalResponse;
    if (response && typeof response.getStatus === "function") {
      var status = response.getStatus();
      return status >= 100 && status <= 599 ? status : 0;
    }
    return 0;
  }

  function codeOf(error) {
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

  function messageFor(status, limits) {
    return status === 413
        ? "파일이 너무 커요 — 최대 " + humanBytes((limits && limits.maxUploadBytes) || 0) + "까지 올릴 수 있어요."
      : status === 401 ? "로그인이 필요해요. 로그인 후 다시 시도해 주세요."
      : (status === 403 || status === 404) ? "올릴 권한을 확인할 수 없어요. 로그인 상태를 확인한 뒤 다시 시도해 주세요."
      : status === 409 ? "올리던 위치가 맞지 않아요. 처음부터 다시 올려 주세요."
      : (status === 415 || status === 422) ? "이 형식은 올릴 수 없어요."
      : "업로드가 끊겼어요. 네트워크를 확인하고 다시 시도해 주세요.";
  }

  // 전체·조각 상한은 서버가 답하는 값만 따른다 — 화면이 숫자를 따로 들지 않는다.
  function discover(endpoint) {
    if (limitsCache[endpoint]) return Promise.resolve(limitsCache[endpoint]);
    return fetch(endpoint, {
      method: "OPTIONS",
      headers: { "Tus-Resumable": "1.0.0" },
      credentials: "same-origin",
      cache: "no-store",
    }).then(function (response) {
      if (!response.ok) throw safeError("업로드 한도를 확인하지 못했어요. 다시 시도해 주세요.");
      var maxSize = Number(response.headers.get("Tus-Max-Size"));
      var chunkMax = Number(response.headers.get("X-Padiem-Tus-Chunk-Max"));
      var limits = {
        maxUploadBytes: Number.isFinite(maxSize) && maxSize > 0 ? maxSize : 0,
        chunkMaxBytes: Number.isFinite(chunkMax) && chunkMax > 0 ? chunkMax : 0,
      };
      limitsCache[endpoint] = limits;
      return limits;
    }, function () {
      throw safeError("업로드 한도를 확인하지 못했어요. 다시 시도해 주세요.");
    });
  }

  // options: {file, endpoint, mediaType, onProgress(sent,total), onState(state)}
  //   state.phase: discovering | uploading | resuming | finalizing
  //   state.percent: 0~100
  // 돌려주는 값은 마지막 한 번의 GET 결과 본문이다(각 화면이 자기 모양으로 검증).
  function upload(options) {
    var file = options.file;
    var endpoint = options.endpoint;
    var mediaType = options.mediaType;
    var onProgress = options.onProgress || function () {};
    var onState = options.onState || function () {};
    if (!file || !endpoint || !mediaType) {
      return Promise.reject(safeError("업로드 정보가 올바르지 않아요."));
    }
    if (typeof window.tus === "undefined") {
      return Promise.reject(safeError("업로드 준비를 마치지 못했어요. 페이지를 새로 고침한 뒤 다시 시도해 주세요."));
    }
    onState({ phase: "discovering", percent: 0 });
    return discover(endpoint).then(function (limits) {
      if (limits.maxUploadBytes && file.size > limits.maxUploadBytes) {
        return Promise.reject(safeError(
          "파일이 너무 커요 — 최대 " + humanBytes(limits.maxUploadBytes) + "까지 올릴 수 있어요."));
      }
      return new Promise(function (resolve, reject) {
        var resumed = false;
        var state = function (phase, sent, total) {
          var percent = phase === "finalizing" ? 100 : percentOf(sent, total);
          onProgress(sent, total);
          onState({ phase: phase, percent: percent, sent: sent, total: total });
        };
        var current = new window.tus.Upload(file, {
          endpoint: endpoint,
          chunkSize: Math.min(DEFAULT_CHUNK_BYTES, limits.chunkMaxBytes || DEFAULT_CHUNK_BYTES),
          retryDelays: [0, 1000, 3000, 5000, 10000],
          // tus-js-client가 메타데이터 값을 자체적으로 base64로 감싸 보낸다(UTF-8 안전).
          // 여기서는 날값만 넘긴다 — 이중 인코딩하면 서버가 파일 이름을 못 알아듣는다.
          uploadMetadata: { filename: file.name, filetype: mediaType },
          headers: { "Accept": "application/json" },
          onProgress: function (sent, total) {
            state(resumed ? "resuming" : "uploading", sent, total);
          },
          onChunkComplete: function (chunkBytes, bytesAccepted, bytesTotal) {
            state(resumed ? "resuming" : "uploading", bytesAccepted, bytesTotal);
          },
          // 끊김(응답 없음)·서버 오류(5xx)·잠김(423)만 자동 이어 올리기. 4xx는 다시
          // 보내도 같은 답이므로 즉시 한국어 안내로 넘긴다.
          onShouldRetry: function (error) {
            var status = statusOf(error);
            if (status === 0 || status >= 500 || status === 423) {
              resumed = true;
              return true;
            }
            return false;
          },
          onError: function (error) {
            reject(safeError(messageFor(statusOf(error), limits), codeOf(error)));
          },
          onSuccess: function () {
            // 마지막 PATCH는 204로 끝난다(tus 규격). 저장 결과(201/4xx)는 한 번만
            // 꺼내 쓴다 — GET이 결과를 돌려주고 서버가 임시 조각을 치운다.
            state("finalizing", file.size, file.size);
            fetch(current.url, {
              credentials: "same-origin", cache: "no-store",
              headers: { "Accept": "application/json" },
            }).then(function (response) {
              return response.json().catch(function () { return null; }).then(function (data) {
                if (!response.ok || !data) {
                  throw safeError(messageFor(response.status, limits));
                }
                resolve(data);
              });
            }, function () {
              throw safeError("업로드 결과를 확인하지 못했어요. 다시 시도해 주세요.");
            }).catch(function (error) {
              reject(error && error.uiMessageSafe ? error
                : safeError("업로드 결과를 확인하지 못했어요. 다시 시도해 주세요."));
            });
          },
        });
        if (options.signal) {
          if (options.signal.aborted) {
            reject(safeError("업로드를 취소했어요."));
            return;
          }
          options.signal.addEventListener("abort", function () {
            try { current.abort(); } catch (ignore) { /* 이미 끝난 업로드 */ }
            reject(safeError("업로드를 취소했어요."));
          }, { once: true });
        }
        current.start();
      });
    });
  }

  window.PadiemTusUpload = Object.freeze({
    upload: upload,
    discover: discover,
    humanBytes: humanBytes,
  });
})();
